"""Redis-backed rate limiting for high-cost OpenScout API operations."""

from __future__ import annotations

import hashlib
import logging
import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import wraps
from threading import Lock
from typing import Any

from flask import jsonify, make_response, request

from docsgpt.cache import get_redis_instance

logger = logging.getLogger(__name__)

_LOCAL_MAX_KEYS = 10_000
_RATE_KEY_PREFIX = "openscout:rate:v1"


@dataclass(frozen=True)
class RateLimitSpec:
    """One fixed-window limit for an API operation."""

    requests: int
    window_seconds: int
    project_requests: int = 10


_DEFAULT_LIMITS: dict[str, RateLimitSpec] = {
    "intelligence_preflight": RateLimitSpec(10, 60),
    "intelligence_sync": RateLimitSpec(5, 60, project_requests=5),
    "intelligence_query": RateLimitSpec(30, 60),
    "intelligence_comparison": RateLimitSpec(10, 60, project_requests=10),
    "intelligence_report_create": RateLimitSpec(5, 60, project_requests=5),
    "intelligence_report_pdf": RateLimitSpec(10, 60, project_requests=10),
    "public_report_read": RateLimitSpec(60, 60),
}

# ``key -> (window start, count, window length)``. This is only a bounded
# fallback for a Redis outage; it is not presented as cross-process state.
_local_windows: dict[str, tuple[float, int, int]] = {}
_local_lock = Lock()
_redis_fallback_logged = False

_RATE_LIMIT_SCRIPT = """
local retry_after = 0
for index, key in ipairs(KEYS) do
    local argument = (index - 1) * 2 + 1
    local limit = tonumber(ARGV[argument])
    local current = tonumber(redis.call('GET', key) or '0')
    if current >= limit then
        local ttl = redis.call('TTL', key)
        if ttl > retry_after then
            retry_after = ttl
        end
        return {0, retry_after}
    end
end
for index, key in ipairs(KEYS) do
    local argument = (index - 1) * 2 + 1
    redis.call('INCR', key)
    if redis.call('TTL', key) < 0 then
        redis.call('EXPIRE', key, tonumber(ARGV[argument + 1]))
    end
end
return {1, 0}
"""


@dataclass(frozen=True)
class RateLimitDecision:
    """The result of checking all scopes for one request."""

    allowed: bool
    retry_after: int = 1


def rate_limit(
    endpoint: str,
    *,
    limit: int | None = None,
    window_seconds: int | None = None,
    project_limit: int | None = None,
    when: Callable[[], bool] | None = None,
):
    """Decorate a Flask view with user/IP and optional project limits.

    Redis is the shared source of truth. If it is unavailable, requests use a
    bounded process-local fixed window and emit one warning per process. This
    keeps an outage from silently removing protection while preserving a
    useful local development fallback.
    """
    spec = _DEFAULT_LIMITS.get(endpoint)
    request_limit = limit if limit is not None else (spec.requests if spec else 1)
    request_window = window_seconds if window_seconds is not None else (
        spec.window_seconds if spec else 60
    )
    request_project_limit = project_limit if project_limit is not None else (
        spec.project_requests if spec else 10
    )

    def decorator(view: Callable[..., Any]):
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any):
            if when is not None and not when():
                return view(*args, **kwargs)
            decision = check_rate_limit(
                endpoint,
                limit=request_limit,
                window_seconds=request_window,
                project_limit=request_project_limit,
                project_ids=_request_project_ids(),
            )
            if not decision.allowed:
                response = make_response(
                    jsonify({
                        "success": False,
                        "message": "rate limit exceeded",
                    }),
                    429,
                )
                response.headers["Retry-After"] = str(decision.retry_after)
                return response
            return view(*args, **kwargs)

        return wrapped

    return decorator


def check_rate_limit(
    endpoint: str,
    *,
    identity: str | None = None,
    project_ids: Iterable[str] = (),
    limit: int | None = None,
    window_seconds: int | None = None,
    project_limit: int | None = None,
) -> RateLimitDecision:
    """Check user/IP and project scopes for one high-cost operation."""
    spec = _DEFAULT_LIMITS.get(endpoint)
    request_limit = limit if limit is not None else (spec.requests if spec else 1)
    request_window = window_seconds if window_seconds is not None else (
        spec.window_seconds if spec else 60
    )
    request_project_limit = project_limit if project_limit is not None else (
        spec.project_requests if spec else 10
    )
    if request_limit <= 0:
        return RateLimitDecision(True)

    identity_value = identity or _request_identity()
    scopes: list[tuple[str, int, int]] = [
        (
            _redis_key("user", f"{endpoint}:{identity_value}"),
            request_limit,
            max(1, request_window),
        )
    ]
    seen_projects: set[str] = set()
    if request_project_limit > 0:
        for project_id in project_ids:
            normalized = str(project_id).strip()
            if not normalized or normalized in seen_projects:
                continue
            seen_projects.add(normalized)
            scopes.append(
                (
                    _redis_key("project", normalized),
                    request_project_limit,
                    max(1, request_window),
                )
            )

    redis_client = None
    try:
        redis_client = get_redis_instance()
    except Exception as exc:  # pragma: no cover - defensive accessor boundary
        _log_redis_fallback(f"Redis accessor failed: {exc}")
    if redis_client is not None:
        try:
            return _check_redis(redis_client, scopes)
        except Exception as exc:
            _log_redis_fallback(f"Redis rate-limit check failed: {exc}")
    else:
        _log_redis_fallback("Redis unavailable")
    return _check_local(scopes)


def _check_redis(redis_client: Any, scopes: list[tuple[str, int, int]]) -> RateLimitDecision:
    """Atomically check and increment every Redis scope."""
    keys = [scope[0] for scope in scopes]
    arguments = [value for _, limit, window in scopes for value in (str(limit), str(window))]
    result = redis_client.eval(_RATE_LIMIT_SCRIPT, len(keys), *keys, *arguments)
    if not isinstance(result, (list, tuple)) or len(result) < 2:
        raise ValueError("unexpected Redis rate-limit response")
    allowed = int(result[0]) == 1
    retry_after = max(1, int(result[1] or 1))
    return RateLimitDecision(allowed, retry_after)


def _check_local(scopes: list[tuple[str, int, int]]) -> RateLimitDecision:
    """Check all scopes in a bounded process-local fixed window."""
    now = time.monotonic()
    with _local_lock:
        _prune_local_windows(now)
        new_keys = {key for key, _, _ in scopes if key not in _local_windows}
        if len(_local_windows) + len(new_keys) > _LOCAL_MAX_KEYS:
            return RateLimitDecision(False, max(window for _, _, window in scopes))

        for key, limit, window in scopes:
            current = _local_windows.get(key)
            if current is None:
                continue
            started, count, current_window = current
            if now - started >= current_window:
                continue
            if count >= limit:
                return RateLimitDecision(False, _retry_after(started, current_window, now))

        for key, _, window in scopes:
            current = _local_windows.get(key)
            if current is None or now - current[0] >= current[2]:
                _local_windows[key] = (now, 1, window)
            else:
                _local_windows[key] = (current[0], current[1] + 1, current[2])
    return RateLimitDecision(True)


def _prune_local_windows(now: float) -> None:
    """Remove expired fallback entries while holding ``_local_lock``."""
    expired = [
        key
        for key, (started, _, window) in _local_windows.items()
        if now - started >= window
    ]
    for key in expired:
        _local_windows.pop(key, None)


def _request_identity() -> str:
    """Return the authenticated user or loopback-safe client address."""
    decoded = getattr(request, "decoded_token", None)
    if isinstance(decoded, dict) and decoded.get("sub"):
        return f"user:{decoded['sub']}"
    return f"ip:{request.remote_addr or 'unknown'}"


def _request_project_ids() -> list[str]:
    """Extract bounded project identifiers without replacing route validation."""
    values: list[str] = []
    view_args = request.view_args or {}
    if view_args.get("project_id"):
        values.append(str(view_args["project_id"]))
    payload = request.get_json(silent=True)
    if isinstance(payload, dict) and isinstance(payload.get("project_ids"), list):
        values.extend(str(value) for value in payload["project_ids"][:64] if value)
    return list(dict.fromkeys(values))


def _redis_key(scope: str, value: str) -> str:
    """Hash untrusted identity values before putting them into Redis keys."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{_RATE_KEY_PREFIX}:{scope}:{digest}"


def _retry_after(started: float, window: int, now: float) -> int:
    """Return a positive Retry-After value for a local window."""
    return max(1, math.ceil(started + window - now))


def _log_redis_fallback(reason: str) -> None:
    """Record the explicit bounded fallback policy once per process."""
    global _redis_fallback_logged
    with _local_lock:
        if _redis_fallback_logged:
            return
        _redis_fallback_logged = True
    logger.warning(
        "Redis unavailable for OpenScout rate limiting; using bounded local fallback: %s",
        reason,
    )


__all__ = ["RateLimitDecision", "RateLimitSpec", "check_rate_limit", "rate_limit"]
