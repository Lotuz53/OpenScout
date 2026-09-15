from datetime import date, datetime, timezone

import pytest

from docsgpt.intelligence.schemas import Coverage, IntelligenceRecord, SourceType, SyncSummary
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


def test_project_lookup_is_owner_scoped(pg_conn, project) -> None:
    repo = IntelligenceRepository(pg_conn)
    project_id = str(project["id"])

    assert repo.get_project(project_id, "owner")["repository"] == "langgenius/dify"
    assert repo.get_project(project_id, "other") is None


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


def test_save_report_is_owner_scoped(pg_conn) -> None:
    report = IntelligenceRepository(pg_conn).save_report(
        "owner",
        {"title": "Dify report", "sections": [{"heading": "Summary"}]},
    )

    assert report["user_id"] == "owner"
    assert report["report_data"]["title"] == "Dify report"
