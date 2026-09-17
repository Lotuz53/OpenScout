"""Behavioral tests for incremental OpenScout synchronization."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from docsgpt.intelligence.github_client import GitHubRateLimitError
from docsgpt.intelligence.normalizer import normalize_release
from docsgpt.intelligence.schemas import SourceType
from docsgpt.intelligence.sync_service import SyncService


PROJECT_ID = "project-1"
PREVIOUS_SYNC = datetime(2026, 9, 15, tzinfo=timezone.utc)
CURRENT_SYNC = datetime(2026, 9, 16, tzinfo=timezone.utc)
RESET_AT = datetime(2026, 9, 17, tzinfo=timezone.utc)


def release_payload(body: str = "Initial release.") -> dict[str, object]:
    """Build one GitHub release payload with a stable external id."""
    return {
        "id": 4001,
        "tag_name": "v1.0.0",
        "name": "Release 1.0.0",
        "body": body,
        "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
        "created_at": "2026-01-10T00:00:00Z",
        "published_at": "2026-01-10T01:00:00Z",
        "updated_at": "2026-01-10T02:00:00Z",
    }


class MemoryRepository:
    """Small stateful repository double for sync lifecycle assertions."""

    def __init__(
        self,
        record=None,
        *,
        last_synced_at=PREVIOUS_SYNC,
        external_updated_at=None,
        finish_error=None,
    ) -> None:
        self.project = {
            "id": PROJECT_ID,
            "user_id": "u1",
            "repository": "owner/repo",
            "window_start": date(2025, 9, 14),
            "window_end": date(2026, 9, 14),
            "last_synced_at": last_synced_at,
            "external_updated_at": external_updated_at,
        }
        self.records = {record["id"]: dict(record)} if record else {}
        self._run_number = 0
        self.finished_runs = {}
        self.finish_error = finish_error
        self.status_calls = []

    def get_project(self, project_id: str, user_id: str):
        assert (project_id, user_id) == (PROJECT_ID, "u1")
        return self.project

    def start_sync_run(self):
        self._run_number += 1
        return {"id": f"sync-{self._run_number}"}

    def finish_sync_run(self, run_id, summary):
        if self.finish_error is not None:
            raise self.finish_error
        self.finished_runs[run_id] = summary
        return {"id": run_id, "status": summary.status}

    def upsert_record(self, project_id, record, *, sync_id=None):
        key = (record.source_type.value, record.external_id)
        existing = next(
            (row for row in self.records.values() if row["key"] == key),
            None,
        )
        if existing is None:
            record_id = f"record-{len(self.records) + 1}"
            self.records[record_id] = {
                "id": record_id,
                "key": key,
                "project_id": project_id,
                "source_type": record.source_type.value,
                "external_id": record.external_id,
                "content_hash": record.content_hash,
                "active": True,
                "missing_confirmations": 0,
                "deactivated_at": None,
                "last_seen_sync_id": sync_id,
            }
            return SimpleNamespace(record_id=record_id, changed=True)

        changed = existing["content_hash"] != record.content_hash or not existing["active"]
        existing["content_hash"] = record.content_hash
        if sync_id:
            existing["last_seen_sync_id"] = sync_id
        return SimpleNamespace(record_id=existing["id"], changed=changed)

    def mark_seen(self, record_id: str, sync_id: str) -> None:
        row = self.records[record_id]
        row.update(
            last_seen_sync_id=sync_id,
            missing_confirmations=0,
            active=True,
            deactivated_at=None,
        )

    def record_missing(self, project_id: str, source_type: SourceType, seen_ids: set[str]) -> int:
        missing = 0
        for row in self.records.values():
            if (
                row["project_id"] == project_id
                and row["source_type"] == source_type.value
                and row["active"]
                and row["external_id"] not in seen_ids
            ):
                row["missing_confirmations"] += 1
                missing += 1
        return missing

    def deactivate_confirmed_missing(self, project_id: str) -> list[str]:
        deactivated = []
        for row in self.records.values():
            if (
                row["project_id"] == project_id
                and row["active"]
                and row["missing_confirmations"] >= 2
            ):
                row["active"] = False
                row["deactivated_at"] = CURRENT_SYNC
                deactivated.append(row["id"])
        return deactivated

    def set_project_status(
        self,
        project_id,
        user_id,
        status,
        last_synced_at=None,
        external_updated_at=None,
    ):
        self.status_calls.append(
            (project_id, user_id, status, last_synced_at, external_updated_at)
        )
        self.project["status"] = status
        if last_synced_at is not None:
            self.project["last_synced_at"] = last_synced_at
        if external_updated_at is not None:
            self.project["external_updated_at"] = external_updated_at

    def get_record(self, record_id: str):
        return self.records[record_id]


class FakeGitHub:
    """GitHub source double that records the incremental time window."""

    def __init__(self, releases=(), *, issue_error=None):
        self.releases = list(releases)
        self.issue_error = issue_error
        self.release_since = []

    def iter_releases(self, repository, since, until):
        self.release_since.append(since)
        return iter(self.releases)

    def iter_issues(self, repository, since, until):
        if self.issue_error:
            raise self.issue_error
        return iter([])

    def iter_comments(self, repository, issue_number, limit=20):
        return iter([])


def stored_release(body: str = "Initial release.") -> dict[str, object]:
    """Create one persisted release matching the normalizer output."""
    record = normalize_release(
        "owner/repo",
        release_payload(body),
        CURRENT_SYNC,
    )
    return {
        "id": "record-1",
        "key": (SourceType.RELEASE.value, record.external_id),
        "project_id": PROJECT_ID,
        "source_type": SourceType.RELEASE.value,
        "external_id": record.external_id,
        "content_hash": record.content_hash,
        "active": True,
        "missing_confirmations": 0,
        "deactivated_at": None,
        "last_seen_sync_id": None,
    }


def make_service(repository, github, indexer=None) -> SyncService:
    """Build a deterministic incremental service for the tests."""
    return SyncService(
        repository=repository,
        github=github,
        indexer=indexer or MagicMock(),
        now_factory=lambda: CURRENT_SYNC,
        graph_enabled=False,
    )


def test_changed_record_is_reindexed() -> None:
    repository = MemoryRepository(stored_release())
    github = FakeGitHub([release_payload(body="Changed release.")])
    indexer = MagicMock()
    indexer.replace_records.return_value = SimpleNamespace(embedded_chunks=1)

    summary = make_service(repository, github, indexer).run_incremental(PROJECT_ID, "u1")

    assert summary.changed_records == 1
    indexer.replace_records.assert_called_once()
    assert github.release_since == [PREVIOUS_SYNC]
    assert summary.cursor is not None
    assert repository.project["external_updated_at"] == summary.cursor.external_updated_at


def test_unchanged_record_is_not_reindexed() -> None:
    repository = MemoryRepository(stored_release())
    github = FakeGitHub([release_payload()])
    indexer = MagicMock()

    summary = make_service(repository, github, indexer).run_incremental(PROJECT_ID, "u1")

    assert summary.unchanged_records == 1
    assert summary.embedded_chunks == 0
    indexer.replace_records.assert_not_called()


def test_record_deactivates_only_after_two_complete_misses() -> None:
    repository = MemoryRepository(stored_release())
    github = FakeGitHub([])
    indexer = MagicMock()

    first = make_service(repository, github, indexer).run_incremental(PROJECT_ID, "u1")
    assert repository.get_record("record-1")["active"] is True
    assert first.deactivated_record_ids == []

    second = make_service(repository, github, indexer).run_incremental(PROJECT_ID, "u1")

    assert repository.get_record("record-1")["active"] is False
    assert second.deactivated_record_ids == ["record-1"]
    indexer.delete_records.assert_called_once_with(PROJECT_ID, ["record-1"])


def test_partial_sync_does_not_confirm_missing_records() -> None:
    previous_external_update = datetime(2026, 1, 1, tzinfo=timezone.utc)
    repository = MemoryRepository(
        stored_release(),
        external_updated_at=previous_external_update,
    )
    github = FakeGitHub([], issue_error=GitHubRateLimitError(RESET_AT))
    indexer = MagicMock()

    summary = make_service(repository, github, indexer).run_incremental(PROJECT_ID, "u1")

    assert summary.status == "partial"
    assert repository.get_record("record-1")["missing_confirmations"] == 0
    assert repository.get_record("record-1")["active"] is True
    assert repository.project["external_updated_at"] == previous_external_update
    indexer.delete_records.assert_not_called()


def test_local_index_failure_finishes_run_and_project_as_failed() -> None:
    repository = MemoryRepository()
    github = FakeGitHub([release_payload()])
    indexer = MagicMock()
    indexer.replace_records.side_effect = RuntimeError("FAISS save failed")

    with pytest.raises(RuntimeError, match="FAISS save failed"):
        make_service(repository, github, indexer).run_incremental(PROJECT_ID, "u1")

    assert repository.project["status"] == "failed"
    failed_summary = repository.finished_runs["sync-1"]
    assert failed_summary.status == "failed"
    assert failed_summary.failures[-1].source_type == "sync"
    assert failed_summary.failures[-1].category == "local"
    assert "FAISS save failed" in failed_summary.failures[-1].message


def test_local_failure_still_updates_project_when_run_finalization_fails() -> None:
    repository = MemoryRepository(finish_error=RuntimeError("finish failed"))
    github = FakeGitHub([release_payload()])
    indexer = MagicMock()
    indexer.replace_records.side_effect = RuntimeError("FAISS save failed")

    with pytest.raises(RuntimeError, match="FAISS save failed"):
        make_service(repository, github, indexer).run_incremental(PROJECT_ID, "u1")

    assert (PROJECT_ID, "u1", "failed") in [
        call[:3] for call in repository.status_calls
    ]
