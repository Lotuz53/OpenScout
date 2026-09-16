"""Bounded GitHub API collection for OpenScout intelligence records."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timezone
from typing import Any, Iterator, Mapping, Sequence

from requests import HTTPError, Response

from docsgpt.parser.remote.github_loader import GitHubLoader, GitHubRateLimitError

__all__ = ["GitHubClient", "GitHubRateLimitError"]


logger = logging.getLogger(__name__)
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

    @staticmethod
    def _link_total(response: Response) -> int:
        """Read a collection total from GitHub's pagination link header."""
        link = response.headers.get("Link", "")
        match = re.search(r"[?&]page=(\d+)[^>]*>;\s*rel=\"last\"", link)
        if match:
            return int(match.group(1))
        payload = response.json()
        return len(payload) if isinstance(payload, list) else 0

    def _estimate_collection_count(
        self,
        url: str,
        params: dict[str, object] | None = None,
    ) -> tuple[int, str | None]:
        """Estimate a GitHub collection size with one metadata-only page."""
        try:
            response = self._request(url, {**(params or {}), "per_page": 1})
            return self._link_total(response), None
        except Exception:
            logger.warning("Could not estimate GitHub collection size for %s", url, exc_info=True)
            return 0, "部分数量估算暂不可用"

    def repository_metadata(self, repo: str) -> dict[str, Any]:
        """Return public repository metadata and bounded count estimates.

        Args:
            repo: GitHub repository URL or ``owner/name``.

        Returns:
            Repository metadata with ``status``, privacy/archive flags, the
            default branch, bounded collection estimates, and non-sensitive
            warnings. A missing repository returns ``status=404`` instead of
            raising so preflight can classify it for the user.
        """
        repo_name = self._normalize_repo(repo)
        try:
            response = self._request(f"{GITHUB_API}/repos/{repo_name}", {})
        except HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None:
                return {
                    "status": int(status),
                    "private": False,
                    "archived": False,
                    "default_branch": None,
                    "estimated_counts": {},
                    "warnings": [],
                }
            raise

        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("GitHub repository metadata must be a JSON object")

        is_private = bool(payload.get("private"))
        default_branch = str(payload.get("default_branch") or "main")
        metadata: dict[str, Any] = {
            "status": int(response.status_code),
            "private": is_private,
            "archived": bool(payload.get("archived")),
            "empty": bool(payload.get("size") == 0 and not payload.get("default_branch")),
            "default_branch": default_branch,
            "estimated_counts": {},
            "warnings": [],
        }
        if is_private:
            return metadata

        issues, issues_warning = self._estimate_collection_count(
            f"{GITHUB_API}/repos/{repo_name}/issues",
            {"state": "all"},
        )
        releases, releases_warning = self._estimate_collection_count(
            f"{GITHUB_API}/repos/{repo_name}/releases",
        )
        documents = 0
        documents_warning: str | None = None
        try:
            entries, truncated = self._loader.fetch_repo_tree(repo_name, default_branch)
            documents = len(self._loader.select_files(entries))
            if truncated:
                documents_warning = "文档数量估算受 GitHub 树接口上限影响"
        except Exception:
            logger.warning("Could not estimate documentation count for %s", repo_name, exc_info=True)
            documents_warning = "文档数量估算暂不可用"

        metadata["estimated_counts"] = {
            "issues": issues,
            "releases": releases,
            "documents": documents,
        }
        metadata["warnings"] = [
            warning
            for warning in (issues_warning, releases_warning, documents_warning)
            if warning
        ]
        return metadata

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
