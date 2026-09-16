from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from docsgpt.intelligence.github_client import GitHubRateLimitError
from docsgpt.intelligence.schemas import IntelligenceRecord, SourceType
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


def test_sync_enqueues_graph_after_indexing_selected_chunks() -> None:
    repository = MagicMock(spec=["upsert_records"])
    repository.upsert_records.return_value = [SimpleNamespace(changed=True)]
    indexer = MagicMock()
    graph_extractor = MagicMock()
    call_order: list[str] = []
    indexer.replace_records.side_effect = lambda *args: (
        call_order.append("index"),
        SimpleNamespace(chunk_ids=["chunk-1"]),
    )[1]
    graph_extractor.delay.side_effect = lambda *args, **kwargs: call_order.append("graph")
    record = IntelligenceRecord(
        id="release:1",
        repository="owner/repo",
        source_type=SourceType.RELEASE,
        external_id="v1.0.0",
        title="Release 1.0.0",
        body="Initial release.",
        source_url="https://github.com/owner/repo/releases/tag/v1.0.0",
        published_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        retrieved_at=RETRIEVED_AT,
        content_hash="release-hash",
    )

    SyncService(
        repository=repository,
        github=MagicMock(),
        indexer=indexer,
        graph_extractor=graph_extractor,
        graph_enabled=True,
    )._persist_batch(PROJECT_ID, [record], user_id="u1")

    assert call_order == ["index", "graph"]
    graph_extractor.delay.assert_called_once()
    args, kwargs = graph_extractor.delay.call_args
    assert args[:2] == (PROJECT_ID, "u1")
    assert args[2][0]["doc_id"] == "chunk-1"
    assert kwargs["config"]["kind"] == "graphrag"
