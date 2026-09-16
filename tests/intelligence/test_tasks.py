from datetime import date
from unittest.mock import MagicMock

from docsgpt.intelligence.github_client import GitHubRateLimitError
from docsgpt.intelligence import tasks
from docsgpt.intelligence.schemas import Coverage, SourceType, SyncSummary
from docsgpt import celeryconfig


def test_sync_task_is_registered_with_durable_retry_policy() -> None:
    task = tasks.sync_intelligence_project

    assert "docsgpt.intelligence.tasks" in celeryconfig.imports
    assert GitHubRateLimitError in task.autoretry_for
    assert task.retry_backoff is True
    assert task.retry_kwargs["max_retries"] == 4


def test_sync_task_serializes_summary(monkeypatch) -> None:
    service = MagicMock()
    service.run.return_value = SyncSummary(
        status="complete",
        counts={source_type: 0 for source_type in SourceType},
        coverage=Coverage(
            repositories=["owner/repo"],
            date_from=date(2025, 9, 14),
            date_to=date(2026, 9, 14),
            counts={source_type: 0 for source_type in SourceType},
        ),
    )
    monkeypatch.setattr(tasks, "build_sync_service", lambda: service)

    task_body = tasks.sync_intelligence_project.run.__wrapped__.__wrapped__
    result = task_body(
        tasks.sync_intelligence_project,
        project_id="project-1",
        user_id="u1",
    )

    assert result["status"] == "complete"
    service.run.assert_called_once_with("project-1", "u1")
