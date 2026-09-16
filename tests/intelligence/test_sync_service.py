from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from docsgpt.intelligence.github_client import GitHubRateLimitError
from docsgpt.intelligence.schemas import SourceType
from docsgpt.intelligence.sync_service import SyncService


PROJECT_ID = "project-1"
RESET_AT = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
RETRIEVED_AT = datetime(2026, 9, 16, 0, tzinfo=timezone.utc)
RAW_RELEASE = {
    "id": 4001,
    "tag_name": "v1.0.0",
    "name": "Release 1.0.0",
    "body": "Initial release.",
    "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
    "created_at": "2026-01-10T00:00:00Z",
    "published_at": "2026-01-10T01:00:00Z",
    "updated_at": "2026-01-10T02:00:00Z",
}


def make_repository() -> MagicMock:
    repository = MagicMock(
        spec=[
            "get_project",
            "start_sync_run",
            "finish_sync_run",
            "upsert_records",
        ]
    )
    repository.get_project.return_value = {
        "id": PROJECT_ID,
        "user_id": "u1",
        "repository": "owner/repo",
        "window_start": date(2025, 9, 14),
        "window_end": date(2026, 9, 14),
    }
    repository.start_sync_run.return_value = {"id": "run-1"}
    repository.upsert_records.return_value = [SimpleNamespace(changed=True)]
    return repository


def test_sync_commits_releases_when_issues_fail() -> None:
    repository = make_repository()
    github = MagicMock(spec=["iter_releases", "iter_issues", "iter_comments"])
    github.iter_releases.return_value = [RAW_RELEASE]
    github.iter_issues.side_effect = GitHubRateLimitError(RESET_AT)
    indexer = MagicMock()

    summary = SyncService(
        repository=repository,
        github=github,
        indexer=indexer,
        now_factory=lambda: RETRIEVED_AT,
    ).run(PROJECT_ID, "u1")

    assert summary.status == "partial"
    assert summary.counts[SourceType.RELEASE] == 1
    assert summary.counts[SourceType.ISSUE] == 0
    assert summary.failures[0].source_type == SourceType.ISSUE
    assert summary.failures[0].category == "rate_limit"
    repository.upsert_records.assert_called_once()
    indexer.replace_records.assert_called_once()
