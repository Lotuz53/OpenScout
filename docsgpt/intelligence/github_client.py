"""Bounded GitHub API collection for OpenScout intelligence records."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Iterator, Mapping, Sequence

from requests import Response

from docsgpt.parser.remote.github_loader import GitHubLoader, GitHubRateLimitError

__all__ = ["GitHubClient", "GitHubRateLimitError"]


UTC = timezone.utc
GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Collect bounded issues, comments and releases through GitHub's API."""

    def __init__(self, loader: GitHubLoader | None = None) -> None:
        """Initialize the client with the existing authenticated loader.

        Args:
            loader: Optional loader injected by tests or callers that already
                own a configured GitHub request boundary.
        """
        self._loader = loader or GitHubLoader()

    @staticmethod
    def _normalize_repo(repo: str) -> str:
        """Normalize and validate a GitHub repository identifier."""
        normalized = GitHubLoader.normalize_repo(repo)
        if not normalized:
            raise ValueError(f"Not a valid GitHub repository: {repo!r}")
        return normalized

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        """Parse a GitHub ISO-8601 timestamp as an aware UTC datetime."""
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime.combine(value, time.min)
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @classmethod
    def _within_window(
        cls,
        raw: Mapping[str, Any],
        since: datetime,
        until: datetime,
        fields: Sequence[str],
    ) -> bool:
        """Return whether any available source timestamp is in the window."""
        start = cls._parse_datetime(since)
        end = cls._parse_datetime(until)
        if start is None or end is None:
            raise ValueError("since and until must be valid timestamps")
        timestamps = [cls._parse_datetime(raw.get(field)) for field in fields]
        timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
        return bool(timestamps) and any(start <= timestamp <= end for timestamp in timestamps)

    def _request(self, url: str, params: dict[str, object]) -> Response:
        """Call the shared loader request boundary with query parameters."""
        return self._loader._make_request(url, params=params)

    def _iter_pages(
        self,
        url: str,
        params: dict[str, object],
    ) -> Iterator[dict[str, Any]]:
        """Yield JSON objects from bounded GitHub API pages."""
        for batch in self._iter_page_batches(url, params):
            yield from batch

    def _iter_page_batches(
        self,
        url: str,
        params: dict[str, object],
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield bounded GitHub API pages as batches."""
        page = 1
        while True:
            response = self._request(
                url,
                params={**params, "per_page": 100, "page": page},
            )
            batch = response.json()
            if not batch:
                return
            if not isinstance(batch, list):
                raise ValueError(f"Expected a list from GitHub API, got {type(batch).__name__}")
            yield batch
            link = response.headers.get("Link", "")
            if 'rel="next"' not in link:
                return
            page += 1

    def iter_issues(
        self,
        repo: str,
        since: datetime,
        until: datetime,
        limit: int = 1000,
    ) -> Iterator[dict[str, Any]]:
        """Yield non-Pull Request issues in the requested time window.

        Args:
            repo: GitHub repository URL or ``owner/name``.
            since: Inclusive lower bound for issue creation or update time.
            until: Inclusive upper bound for issue creation or update time.
            limit: Maximum number of non-Pull Request issues to yield.

        Yields:
            Raw GitHub issue objects.
        """
        if limit <= 0:
            return
        repo_name = self._normalize_repo(repo)
        yielded = 0
        for raw in self._iter_pages(
            f"{GITHUB_API}/repos/{repo_name}/issues",
            {"state": "all"},
        ):
            if "pull_request" in raw:
                continue
            if not self._within_window(raw, since, until, ("created_at", "updated_at")):
                continue
            yield raw
            yielded += 1
            if yielded >= limit:
                return

    def iter_comments(
        self,
        repo: str,
        issue_number: int,
        limit: int = 20,
    ) -> Iterator[dict[str, Any]]:
        """Yield the oldest comments for one issue, capped by ``limit``."""
        if limit <= 0:
            return
        repo_name = self._normalize_repo(repo)
        comments: list[dict[str, Any]] = []
        for batch in self._iter_page_batches(
            f"{GITHUB_API}/repos/{repo_name}/issues/{issue_number}/comments",
            {"sort": "created", "direction": "asc"},
        ):
            comments.extend(batch)
            if len(comments) >= limit:
                break
        comments.sort(
            key=lambda comment: self._parse_datetime(comment.get("created_at")) or datetime.max.replace(tzinfo=UTC)
        )
        yield from comments[:limit]

    def iter_releases(
        self,
        repo: str,
        since: datetime,
        until: datetime,
    ) -> Iterator[dict[str, Any]]:
        """Yield releases published or created in the requested time window."""
        repo_name = self._normalize_repo(repo)
        for raw in self._iter_pages(f"{GITHUB_API}/repos/{repo_name}/releases", {}):
            if self._within_window(raw, since, until, ("published_at", "created_at")):
                yield raw
