"""Small, shared helpers for the Flask and ASGI CORS policies."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5173",
    "http://localhost:5174",
)
SECURE_AUTH_TYPES = frozenset({"simple_jwt", "session_jwt", "oidc"})
CORS_ALLOWED_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
CORS_ALLOWED_HEADERS = ("Content-Type", "Authorization", "Idempotency-Key")


def parse_cors_allowed_origins(configured_origins: str | None) -> tuple[str, ...]:
    """Return the exact origin strings configured for browser access."""
    if configured_origins is None or not configured_origins.strip():
        return DEFAULT_CORS_ALLOWED_ORIGINS

    origins = tuple(origin.strip() for origin in configured_origins.split(",") if origin.strip())
    if "*" in origins:
        raise ValueError("CORS_ALLOWED_ORIGINS must not contain the wildcard '*'")
    return origins


def is_loopback_origin(origin: str) -> bool:
    """Return whether an origin points at a loopback host."""
    try:
        parsed = urlsplit(origin)
        hostname = parsed.hostname
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    mapped_address = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or bool(mapped_address and mapped_address.is_loopback)


def cors_allowed_origins(configured_origins: str | None, auth_type: str | None) -> tuple[str, ...]:
    """Apply the local-only default when the application has no secure auth."""
    origins = parse_cors_allowed_origins(configured_origins)
    if auth_type in SECURE_AUTH_TYPES:
        return origins
    return tuple(origin for origin in origins if is_loopback_origin(origin))


def is_allowed_cors_origin(origin: str, configured_origins: str | None, auth_type: str | None) -> bool:
    """Check an Origin header using exact matching and the auth-mode policy."""
    return origin in cors_allowed_origins(configured_origins, auth_type)


def is_loopback_client(remote_addr: str | None) -> bool:
    """Return whether a request came from a loopback IP address."""
    if not remote_addr:
        return False
    if remote_addr.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(remote_addr.split("%", 1)[0])
    except ValueError:
        return False
    mapped_address = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or bool(mapped_address and mapped_address.is_loopback)
