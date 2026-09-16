"""Preflight validation for user-supplied public GitHub repositories."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docsgpt.intelligence.github_client import GitHubClient
from docsgpt.parser.remote.github_loader import GitHubLoader

MAX_ISSUES = 1000


@dataclass
class RepositoryPreflight:
    """Describe whether a repository can enter an OpenScout project."""

    repository: str
    default_branch: str | None = None
    archived: bool = False
    estimated_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    message: str | None = None


class RepositoryPreflightService:
    """Validate repository scope before a project is created."""

    def __init__(self, github: GitHubClient) -> None:
        """Initialize the service with a metadata-capable GitHub client.

        Args:
            github: Client used to inspect a repository without downloading
                document bodies.
        """
        self._github = github

    @staticmethod
    def _error(
        repository: str,
        error_code: str,
        message: str,
    ) -> RepositoryPreflight:
        """Build a stable preflight error result."""
        return RepositoryPreflight(
            repository=repository,
            error_code=error_code,
            message=message,
        )

    @staticmethod
    def _counts(metadata: dict[str, Any]) -> dict[str, int]:
        """Normalize non-negative count estimates from GitHub metadata."""
        raw_counts = metadata.get("estimated_counts")
        if not isinstance(raw_counts, dict):
            return {}
        counts: dict[str, int] = {}
        for key in ("issues", "releases", "documents"):
            try:
                value = int(raw_counts.get(key, 0))
            except (TypeError, ValueError):
                value = 0
            counts[key] = max(0, value)
        return counts

    def check(self, repo_url: str) -> RepositoryPreflight:
        """Classify a repository and return bounded setup information.

        Args:
            repo_url: User-supplied GitHub URL or ``owner/name`` value.

        Returns:
            A structured result suitable for both the API and setup UI.
        """
        repository = GitHubLoader.normalize_repo(repo_url)
        if not repository:
            return self._error(
                "",
                "invalid_repository",
                "请输入有效的 GitHub 公共仓库地址。",
            )

        metadata = self._github.repository_metadata(repository)
        status = int(metadata.get("status", 0))
        if status == 404:
            return self._error(repository, "not_found", "找不到该 GitHub 仓库。")
        if status != 200:
            return self._error(
                repository,
                "github_unavailable",
                "暂时无法读取该 GitHub 仓库，请稍后重试。",
            )
        if bool(metadata.get("private")):
            return self._error(
                repository,
                "private_not_supported",
                "当前阶段只支持公开 GitHub 仓库。",
            )

        warnings = [
            warning
            for warning in metadata.get("warnings", [])
            if isinstance(warning, str) and warning.strip()
        ]
        counts = self._counts(metadata)
        if bool(metadata.get("archived")):
            warnings.append("该仓库已归档，数据可能不会继续更新。")
        if bool(metadata.get("empty")):
            warnings.append("该仓库目前为空，首次同步可能没有可用内容。")
        if counts.get("issues", 0) >= MAX_ISSUES:
            warnings.append(f"Issue 数量达到 {MAX_ISSUES} 条上限，首次同步将按上限采集。")

        return RepositoryPreflight(
            repository=repository,
            default_branch=str(metadata.get("default_branch") or "main"),
            archived=bool(metadata.get("archived")),
            estimated_counts=counts,
            warnings=warnings,
        )
