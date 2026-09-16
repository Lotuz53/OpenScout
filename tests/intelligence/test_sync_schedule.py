"""Behavioral tests for OpenScout daily and manual sync dispatch."""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

from docsgpt.api.user.scheduler_dispatcher import (
    IntelligenceSyncDispatcher,
    dispatch_daily_intelligence_syncs,
)
from docsgpt.core.settings import settings


PROJECT_ID = "project-1"
WHEN = datetime(2026, 9, 16, 8, 30, tzinfo=timezone.utc)


def test_daily_dispatch_uses_project_scoped_idempotency_key() -> None:
    """A scheduled slot must dispatch the sync task with a stable key."""
    sync_task = MagicMock()
    dispatcher = IntelligenceSyncDispatcher(sync_task=sync_task, user_id="u1")

    dispatcher.dispatch(PROJECT_ID, scheduled_at=WHEN)

    dispatched = sync_task.apply_async.call_args.kwargs["kwargs"]
    assert dispatched["project_id"] == PROJECT_ID
    assert dispatched["user_id"] == "u1"
    assert dispatched["idempotency_key"] == f"openscout-sync:{PROJECT_ID}:{WHEN.isoformat()}"


def test_dispatch_keeps_bounded_retry_on_existing_task() -> None:
    """Dispatching does not replace the task's existing Celery retry policy."""
    sync_task = MagicMock()
    dispatcher = IntelligenceSyncDispatcher(sync_task=sync_task, user_id="u1")

    dispatcher.dispatch(PROJECT_ID, scheduled_at=WHEN)

    sync_task.apply_async.assert_called_once()
    assert sync_task.apply_async.call_args.kwargs["queue"] == "docsgpt"


def test_daily_dispatch_queues_each_persisted_project(monkeypatch) -> None:
    """The RedBeat tick fans out one owner-scoped task per project."""
    sync_task = MagicMock()

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [
                {"project_id": "project-1", "user_id": "u1"},
                {"project_id": "project-2", "user_id": "u2"},
            ]

    class Connection:
        def execute(self, _query):
            return Result()

    @contextmanager
    def readonly_connection():
        yield Connection()

    monkeypatch.setattr(settings, "POSTGRES_URI", "postgresql://test")
    monkeypatch.setattr(
        "docsgpt.storage.db.session.db_readonly", readonly_connection
    )
    monkeypatch.setattr(
        "docsgpt.api.user.scheduler_dispatcher._sync_task",
        lambda: sync_task,
    )

    result = dispatch_daily_intelligence_syncs(scheduled_at=WHEN)

    assert result == {"dispatched": 2, "skipped": 0}
    assert sync_task.apply_async.call_count == 2
    dispatched_keys = [
        call.kwargs["kwargs"]["idempotency_key"]
        for call in sync_task.apply_async.call_args_list
    ]
    assert dispatched_keys == [
        f"openscout-sync:project-1:{WHEN.isoformat()}",
        f"openscout-sync:project-2:{WHEN.isoformat()}",
    ]
