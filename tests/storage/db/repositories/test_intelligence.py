from datetime import date, datetime, timezone
import threading

import pytest
from sqlalchemy import text

from docsgpt.intelligence.schemas import (
    Coverage,
    IntelligenceRecord,
    QueryFilters,
    SourceType,
    SyncFailure,
    SyncSummary,
)
from docsgpt.storage.db.repositories.intelligence import IntelligenceRepository


@pytest.fixture
def intelligence_record() -> IntelligenceRecord:
    return IntelligenceRecord(
        repository="langgenius/dify",
        source_type=SourceType.ISSUE,
        external_id="issue:42",
        title="Add SSO support",
        body="The community requests SSO support.",
        source_url="https://github.com/langgenius/dify/issues/42",
        state="open",
        labels=["feature"],
        comments_count=3,
        reactions_count=5,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
        content_hash="hash-42",
    )


@pytest.fixture
def project(pg_conn) -> dict:
    return IntelligenceRepository(pg_conn).create_project(
        user_id="owner",
        repository="langgenius/dify",
        window_start=date(2025, 9, 14),
        window_end=date(2026, 9, 14),
    )


def test_upsert_record_skips_unchanged_content(pg_conn, project, intelligence_record) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])

    first = repo.upsert_record(project_id, intelligence_record)
    second = repo.upsert_record(project_id, intelligence_record)

    assert first.changed is True
    assert second.changed is False
    assert second.record_id == first.record_id


def test_retrieval_hydration_and_coverage_are_owner_filter_scoped(
    pg_conn,
    project,
    intelligence_record,
) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])
    outcome = repo.upsert_record(project_id, intelligence_record)
    filters = QueryFilters(
        repositories=["langgenius/dify"],
        source_types=[SourceType.ISSUE],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 3),
    )

    rows = repo.get_records_for_retrieval(
        "owner",
        [project_id],
        filters,
        [outcome.record_id],
    )
    assert rows[0]["id"] == outcome.record_id
    assert rows[0]["body"] == intelligence_record.body

    assert repo.get_records_for_retrieval(
        "other",
        [project_id],
        filters,
        [outcome.record_id],
    ) == []
    assert repo.get_records_for_retrieval(
        "owner",
        [project_id],
        filters.model_copy(update={"source_types": [SourceType.RELEASE]}),
        [outcome.record_id],
    ) == []

    coverage = repo.coverage("owner", filters)
    assert coverage["repositories"] == ["langgenius/dify"]
    assert coverage["counts"]["issue"] == 1


def test_missing_record_requires_two_confirmations_and_can_reappear(
    pg_conn,
    project,
    intelligence_record,
) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])
    outcome = repo.upsert_record(project_id, intelligence_record)

    assert repo.record_missing(project_id, SourceType.ISSUE, set()) == 1
    assert repo.get_record(outcome.record_id)["missing_confirmations"] == 1
    assert repo.get_record(outcome.record_id)["active"] is True

    assert repo.record_missing(project_id, SourceType.ISSUE, set()) == 1
    assert repo.deactivate_confirmed_missing(project_id) == [outcome.record_id]
    assert repo.get_record(outcome.record_id)["active"] is False
    assert repo.get_record(outcome.record_id)["deactivated_at"] is not None

    repo.mark_seen(outcome.record_id, "sync-3")
    restored = repo.get_record(outcome.record_id)
    assert restored["active"] is True
    assert restored["missing_confirmations"] == 0
    assert restored["deactivated_at"] is None
    assert restored["last_seen_sync_id"] == "sync-3"


def test_project_lookup_is_owner_scoped(pg_conn, project) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])

    assert repo.get_project(project_id, "owner")["repository"] == "langgenius/dify"
    assert repo.get_project(project_id, "other") is None


def test_project_status_persists_external_cursor_in_owner_scope(pg_conn, project) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])
    last_synced_at = datetime(2026, 9, 16, 8, tzinfo=timezone.utc)
    external_updated_at = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)

    repo.set_project_status(
        project_id,
        "owner",
        "ready",
        last_synced_at,
        external_updated_at,
    )

    persisted = repo.get_project(project_id, "owner")
    assert persisted["status"] == "ready"
    assert datetime.fromisoformat(persisted["last_synced_at"]) == last_synced_at
    assert datetime.fromisoformat(persisted["external_updated_at"]) == external_updated_at

    repo.set_project_status(project_id, "owner", "partial")
    preserved = repo.get_project(project_id, "owner")
    assert datetime.fromisoformat(preserved["external_updated_at"]) == external_updated_at

    repo.set_project_status(
        project_id,
        "other",
        "failed",
        external_updated_at=last_synced_at,
    )
    assert repo.get_project(project_id, "owner")["status"] == "partial"


def test_all_projects_owned_requires_every_project_in_owner_scope(pg_conn, project) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])
    other_project = repo.create_project(
        user_id="other",
        repository="other/repo",
        window_start=date(2025, 9, 14),
        window_end=date(2026, 9, 14),
    )

    assert repo.all_projects_owned("owner", [project_id]) is True
    assert repo.all_projects_owned("owner", [str(other_project["id"])]) is False
    assert repo.all_projects_owned("owner", [project_id, str(other_project["id"])]) is False


def test_sync_run_persists_summary(pg_conn, project) -> None:
    repo = IntelligenceRepository(pg_conn)
    run = repo.start_sync_run(str(project["id"]))
    summary = SyncSummary(
        status="complete",
        counts={SourceType.ISSUE: 1},
        coverage=Coverage(
            repositories=["langgenius/dify"],
            date_from=date(2025, 9, 14),
            date_to=date(2026, 9, 14),
            counts={SourceType.ISSUE: 1},
        ),
    )

    finished = repo.finish_sync_run(str(run["id"]), summary)

    assert run["status"] == "running"
    assert finished["status"] == "complete"
    assert finished["counts"]["issue"] == 1


def test_sync_run_persists_local_failure_summary(pg_conn, project) -> None:
    repo = IntelligenceRepository(pg_conn)
    run = repo.start_sync_run(str(project["id"]))
    summary = SyncSummary(
        status="failed",
        counts={},
        failures=[
            SyncFailure(
                source_type="sync",
                category="local",
                retryable=False,
                message="FAISS save failed",
            )
        ],
        coverage=Coverage(
            repositories=["langgenius/dify"],
            date_from=date(2025, 9, 14),
            date_to=date(2026, 9, 14),
            counts={},
        ),
    )

    finished = repo.finish_sync_run(str(run["id"]), summary)

    assert finished["status"] == "failed"
    assert finished["failures"][0]["source_type"] == "sync"
    assert finished["failures"][0]["category"] == "local"


def test_claim_project_sync_creates_one_running_attempt(pg_conn, project) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])

    first = repo.claim_project_sync(project_id, "owner")
    second = repo.claim_project_sync(project_id, "owner")

    assert first is not None
    assert first["status"] == "running"
    assert second is None
    assert repo.get_project(project_id, "owner")["status"] == "syncing"


def test_claim_project_sync_allows_a_new_attempt_after_failure(pg_conn, project) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])

    first = repo.claim_project_sync(project_id, "owner")
    repo.fail_sync_run(str(first["id"]), "index persistence failed")
    repo.set_project_status(project_id, "owner", "failed")

    replacement = repo.claim_project_sync(project_id, "owner")

    assert replacement is not None
    assert str(replacement["id"]) != str(first["id"])
    assert repo.get_sync_run(str(first["id"]), "owner")["status"] == "failed"


def test_claim_project_sync_allows_a_new_attempt_after_success(pg_conn, project) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])
    first = repo.claim_project_sync(project_id, "owner")
    repo.finish_sync_run(
        str(first["id"]),
        SyncSummary(
            status="complete",
            counts={},
            coverage=Coverage(
                repositories=["langgenius/dify"],
                date_from=date(2025, 9, 14),
                date_to=date(2026, 9, 14),
                counts={},
            ),
        ),
    )
    repo.set_project_status(project_id, "owner", "ready")

    replacement = repo.claim_project_sync(project_id, "owner")

    assert replacement is not None
    assert str(replacement["id"]) != str(first["id"])


def test_claim_project_sync_is_atomic_under_concurrency(pg_engine) -> None:
    project_id = None
    with pg_engine.begin() as conn:
        project = IntelligenceRepository(conn).create_project(
            user_id="owner",
            repository="langgenius/dify",
            window_start=date(2025, 9, 14),
            window_end=date(2026, 9, 14),
        )
        project_id = str(project["id"])

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def claim() -> None:
        try:
            with pg_engine.begin() as conn:
                barrier.wait(timeout=10)
                results.append(
                    IntelligenceRepository(conn).claim_project_sync(project_id, "owner")
                )
        except Exception as exc:  # pragma: no cover - assertion reports the cause
            errors.append(exc)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert errors == []
    assert len(results) == 2
    assert sum(result is not None for result in results) == 1


def test_claim_project_sync_reaps_an_expired_attempt(pg_conn, project) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])
    stale = repo.start_sync_run(project_id)
    repo.set_project_status(project_id, "owner", "syncing")
    pg_conn.execute(
        text(
            "UPDATE intelligence_sync_runs "
            "SET started_at = now() - interval '1 hour' "
            "WHERE id = CAST(:run_id AS uuid)"
        ),
        {"run_id": str(stale["id"])},
    )

    replacement = repo.claim_project_sync(
        project_id,
        "owner",
        stale_after_seconds=60,
    )

    assert replacement is not None
    assert str(replacement["id"]) != str(stale["id"])
    assert repo.get_sync_run(str(stale["id"]), "owner")["status"] == "failed"
    assert repo.get_sync_run(str(replacement["id"]), "owner")["status"] == "running"


def test_overview_includes_latest_owner_sync_run(
    pg_conn,
    project,
    intelligence_record,
) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])
    issue = repo.upsert_record(project_id, intelligence_record)
    release = IntelligenceRecord(
        repository="langgenius/dify",
        source_type=SourceType.RELEASE,
        external_id="release:v1.2.3",
        title="v1.2.3",
        body="Release notes",
        source_url="https://github.com/langgenius/dify/releases/tag/v1.2.3",
        version="v1.2.3",
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        published_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 2, 2, tzinfo=timezone.utc),
        content_hash="release-v1.2.3",
    )
    repo.upsert_record(project_id, release)
    repo.save_topic_run(
        project_id=project_id,
        snapshot_id="snapshot-1",
        algorithm_version="spherical-kmeans-v1",
        clusters=[
            {
                "id": "topic-1",
                "label": "SSO",
                "record_ids": [issue.record_id],
                "centroid": [1.0],
                "snapshot_id": "snapshot-1",
            }
        ],
    )
    run = repo.start_sync_run(str(project["id"]))
    summary = SyncSummary(
        status="partial",
        counts={SourceType.ISSUE: 1},
        failures=[
            SyncFailure(
                source_type=SourceType.RELEASE,
                category="network",
                retryable=True,
                message="temporary failure",
            )
        ],
        coverage=Coverage(
            repositories=["langgenius/dify"],
            date_from=date(2025, 9, 14),
            date_to=date(2026, 9, 14),
            counts={SourceType.ISSUE: 1},
            capped=True,
        ),
    )
    repo.finish_sync_run(str(run["id"]), summary)

    overview = repo.overview("owner")

    latest_run = overview["latest_sync_run"]
    assert str(latest_run["id"]) == str(run["id"])
    assert latest_run["status"] == "partial"
    assert latest_run["failures"][0]["category"] == "network"
    assert overview["capped"] is True
    assert overview["latest_version"] == "v1.2.3"
    assert overview["topics"][0]["label"] == "SSO"


def test_save_report_is_owner_scoped(pg_conn) -> None:
    report = IntelligenceRepository(pg_conn).save_report(
        "owner",
        {"title": "Dify report", "sections": [{"heading": "Summary"}]},
    )

    assert report["user_id"] == "owner"
    assert report["report_data"]["title"] == "Dify report"
