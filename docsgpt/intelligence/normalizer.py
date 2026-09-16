"""Normalize GitHub objects into traceable OpenScout intelligence records."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, datetime, time, timezone
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from docsgpt.intelligence.schemas import IntelligenceRecord, SourceType
from docsgpt.parser.remote.github_loader import GitHubLoader


UTC = timezone.utc
TEXT_EXTENSIONS = frozenset({".adoc", ".asciidoc", ".markdown", ".md", ".mdx", ".rst", ".txt"})


def is_supported_document(path: str) -> bool:
    """Return whether a repository path is in the Stage A document scope.

    Args:
        path: A repository-relative POSIX path.

    Returns:
        ``True`` for a root README or a text file below ``docs/``.
    """
    if not isinstance(path, str):
        return False
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized.startswith("/"):
        return False

    parts = PurePosixPath(normalized).parts
    if not parts or ".." in parts:
        return False
    filename = parts[-1]
    suffix = PurePosixPath(filename).suffix.lower()
    if len(parts) == 1:
        return filename.lower() == "readme" or (
            filename.lower().startswith("readme.") and suffix in TEXT_EXTENSIONS
        )
    return parts[0].lower() == "docs" and suffix in TEXT_EXTENSIONS


def content_hash(body: str, metadata: Mapping[str, Any]) -> str:
    """Return a deterministic SHA-256 hash for content and metadata.

    Args:
        body: The record body. Outer whitespace is ignored.
        metadata: JSON-compatible metadata whose key order should not affect the hash.

    Returns:
        A hexadecimal SHA-256 digest.
    """
    canonical = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{body.strip()}\n{canonical}".encode("utf-8")).hexdigest()


def normalize_document(
    repository: str,
    path: str,
    body: str,
    source_url: str,
    retrieved_at: datetime,
) -> IntelligenceRecord:
    """Normalize a supported README or documentation file.

    Args:
        repository: GitHub repository URL or ``owner/name`` identifier.
        path: Repository-relative document path.
        body: Markdown or other supported text content.
        source_url: The GitHub HTML URL for the file.
        retrieved_at: UTC time at which the file was collected.

    Returns:
        A normalized documentation record.

    Raises:
        ValueError: If the path, source URL, or timestamp is invalid.
    """
    if not is_supported_document(path):
        raise ValueError(f"Document path is outside the intelligence scope: {path!r}")
    repository_name = _normalize_repository(repository)
    normalized_path = _normalize_path(path)
    normalized_body = _clean_body(body)
    title = _document_title(normalized_path, normalized_body)
    return _build_record(
        repository=repository_name,
        source_type=SourceType.DOCUMENTATION,
        external_id=normalized_path,
        title=title,
        body=normalized_body,
        source_url=_require_html_url(source_url),
        retrieved_at=retrieved_at,
    )


def normalize_issue(
    repository: str,
    raw: Mapping[str, Any],
    retrieved_at: datetime,
) -> IntelligenceRecord:
    """Normalize a non-Pull Request GitHub Issue object.

    Args:
        repository: GitHub repository URL or ``owner/name`` identifier.
        raw: Raw GitHub Issue API object.
        retrieved_at: UTC time at which the object was collected.

    Returns:
        A normalized Issue record.
    """
    if "pull_request" in raw:
        raise ValueError("Pull Requests are outside the intelligence Issue scope")
    repository_name = _normalize_repository(repository)
    number = raw.get("number")
    external_id = _external_id(raw, str(number) if number is not None else "")
    title = _text(raw.get("title")) or f"Issue #{number or external_id}"
    body = _clean_body(raw.get("body"))
    created_at = _parse_datetime(raw.get("created_at"))
    updated_at = _parse_datetime(raw.get("updated_at"))
    fallback_url = f"https://github.com/{repository_name}/issues/{number or external_id}"
    return _build_record(
        repository=repository_name,
        source_type=SourceType.ISSUE,
        external_id=external_id,
        title=title,
        body=body,
        source_url=_raw_html_url(raw, fallback_url),
        state=_optional_text(raw.get("state")),
        labels=_label_names(raw.get("labels")),
        comments_count=_count(raw.get("comments")),
        reactions_count=_reaction_count(raw.get("reactions")),
        created_at=created_at,
        updated_at=updated_at,
        retrieved_at=retrieved_at,
    )


def normalize_comment(
    repository: str,
    issue_number: int,
    raw: Mapping[str, Any],
    retrieved_at: datetime,
) -> IntelligenceRecord:
    """Normalize a GitHub Issue comment.

    Args:
        repository: GitHub repository URL or ``owner/name`` identifier.
        issue_number: Number of the parent Issue.
        raw: Raw GitHub Issue comment API object.
        retrieved_at: UTC time at which the object was collected.

    Returns:
        A normalized Issue comment record.
    """
    repository_name = _normalize_repository(repository)
    try:
        normalized_issue_number = int(issue_number)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid issue number: {issue_number!r}") from exc
    created_at = _parse_datetime(raw.get("created_at"))
    fallback_id = f"{normalized_issue_number}:{_isoformat(created_at) or 'unknown'}"
    external_id = _external_id(raw, fallback_id)
    fallback_url = (
        f"https://github.com/{repository_name}/issues/{normalized_issue_number}#issuecomment-{external_id}"
    )
    return _build_record(
        repository=repository_name,
        source_type=SourceType.ISSUE_COMMENT,
        external_id=external_id,
        title=f"Comment on issue #{normalized_issue_number}",
        body=_clean_body(raw.get("body")),
        source_url=_raw_html_url(raw, fallback_url),
        reactions_count=_reaction_count(raw.get("reactions")),
        created_at=created_at,
        updated_at=_parse_datetime(raw.get("updated_at")),
        retrieved_at=retrieved_at,
    )


def normalize_release(
    repository: str,
    raw: Mapping[str, Any],
    retrieved_at: datetime,
) -> IntelligenceRecord:
    """Normalize a GitHub Release object.

    Args:
        repository: GitHub repository URL or ``owner/name`` identifier.
        raw: Raw GitHub Release API object.
        retrieved_at: UTC time at which the object was collected.

    Returns:
        A normalized Release record.
    """
    repository_name = _normalize_repository(repository)
    version = _text(raw.get("tag_name")) or _text(raw.get("name"))
    external_id = _external_id(raw, version)
    title = _text(raw.get("name")) or version or f"Release {external_id}"
    fallback_url = f"https://github.com/{repository_name}/releases/tag/{version or external_id}"
    return _build_record(
        repository=repository_name,
        source_type=SourceType.RELEASE,
        external_id=external_id,
        title=title,
        body=_clean_body(raw.get("body")),
        source_url=_raw_html_url(raw, fallback_url),
        state=_release_state(raw),
        comments_count=_count(raw.get("comments")),
        reactions_count=_reaction_count(raw.get("reactions")),
        version=version or None,
        created_at=_parse_datetime(raw.get("created_at")),
        updated_at=_parse_datetime(raw.get("updated_at")),
        published_at=_parse_datetime(raw.get("published_at")),
        retrieved_at=retrieved_at,
    )


def _build_record(
    *,
    repository: str,
    source_type: SourceType,
    external_id: str,
    title: str,
    body: str,
    source_url: str,
    retrieved_at: datetime,
    state: str | None = None,
    labels: list[str] | None = None,
    comments_count: int = 0,
    reactions_count: int = 0,
    version: str | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    published_at: datetime | None = None,
) -> IntelligenceRecord:
    """Build a record and hash all stable source fields except retrieval time."""
    normalized_retrieved_at = _parse_datetime(retrieved_at, required=True)
    normalized_labels = labels or []
    normalized_body = body.strip()
    stable_metadata = {
        "repository": repository,
        "source_type": source_type.value,
        "external_id": external_id,
        "title": title,
        "source_url": source_url,
        "state": state,
        "labels": normalized_labels,
        "comments_count": comments_count,
        "reactions_count": reactions_count,
        "version": version,
        "created_at": _isoformat(created_at),
        "updated_at": _isoformat(updated_at),
        "published_at": _isoformat(published_at),
    }
    return IntelligenceRecord(
        repository=repository,
        source_type=source_type,
        external_id=external_id,
        title=title,
        body=normalized_body,
        source_url=source_url,
        state=state,
        labels=normalized_labels,
        comments_count=comments_count,
        reactions_count=reactions_count,
        version=version,
        created_at=created_at,
        updated_at=updated_at,
        published_at=published_at,
        retrieved_at=normalized_retrieved_at,
        content_hash=content_hash(normalized_body, stable_metadata),
    )


def _normalize_repository(repository: str) -> str:
    """Return the canonical ``owner/name`` repository identifier."""
    normalized = GitHubLoader.normalize_repo(repository)
    if not normalized:
        raise ValueError(f"Not a valid GitHub repository: {repository!r}")
    return normalized


def _normalize_path(path: str) -> str:
    """Return a normalized repository-relative path."""
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _parse_datetime(value: Any, *, required: bool = False) -> datetime | None:
    """Parse a timestamp and normalize it to UTC."""
    if value is None or value == "":
        if required:
            raise ValueError("timestamp is required")
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            if required:
                raise ValueError(f"Invalid timestamp: {value!r}") from None
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _isoformat(value: datetime | None) -> str | None:
    """Serialize a normalized timestamp for deterministic metadata."""
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_html_url(value: str) -> str:
    """Validate that a source URL points to GitHub's HTML site."""
    if not isinstance(value, str):
        raise ValueError("source_url must be a GitHub HTML URL")
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "github.com":
        raise ValueError("source_url must be a GitHub HTML URL, not an API URL")
    return value.strip()


def _raw_html_url(raw: Mapping[str, Any], fallback: str) -> str:
    """Use a raw object's HTML URL, falling back from API URLs when needed."""
    candidate = raw.get("html_url") or raw.get("url") or fallback
    parsed = urlparse(str(candidate).strip())
    if parsed.hostname == "api.github.com":
        candidate = fallback
    return _require_html_url(str(candidate))


def _document_title(path: str, body: str) -> str:
    """Extract the first Markdown H1 or use the file stem."""
    for line in body.splitlines():
        match = re.match(r"^\s{0,3}#\s+(.+?)\s*#*\s*$", line)
        if match:
            return match.group(1).strip()
    return PurePosixPath(path).stem


def _clean_body(value: Any) -> str:
    """Convert a nullable external body to trimmed text."""
    return "" if value is None else str(value).strip()


def _text(value: Any) -> str:
    """Convert a value to non-empty text."""
    return "" if value is None else str(value).strip()


def _optional_text(value: Any) -> str | None:
    """Convert a nullable value to optional text."""
    text = _text(value)
    return text or None


def _external_id(raw: Mapping[str, Any], fallback: str) -> str:
    """Extract a stable external object identifier."""
    for key in ("id", "node_id"):
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value)
    if not fallback:
        raise ValueError("GitHub object has no external identifier")
    return fallback


def _label_names(value: Any) -> list[str]:
    """Extract label names from GitHub's object-or-string label values."""
    if not isinstance(value, list):
        return []
    names = []
    for label in value:
        name = label.get("name") if isinstance(label, Mapping) else label
        normalized = _text(name)
        if normalized:
            names.append(normalized)
    return names


def _count(value: Any) -> int:
    """Convert a non-negative GitHub count to an integer."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _reaction_count(value: Any) -> int:
    """Extract GitHub's total reaction count."""
    return _count(value.get("total_count")) if isinstance(value, Mapping) else 0


def _release_state(raw: Mapping[str, Any]) -> str:
    """Map GitHub release flags to a stable state label."""
    if raw.get("draft"):
        return "draft"
    if raw.get("prerelease"):
        return "prerelease"
    return "published"
