"""Contract tests for the OpenScout intelligence API."""

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from flask import Flask, request
from flask_restx import Api

from docsgpt.api.user.intelligence.routes import intelligence_ns
from docsgpt.intelligence.comparison import ComparisonCell, ComparisonResult, ComparisonRow
from docsgpt.intelligence.preflight import RepositoryPreflight
from docsgpt.intelligence.report_service import ReportService
from docsgpt.intelligence.schemas import (
    Claim,
    ClaimKind,
    Confidence,
    Coverage,
    Evidence,
    QueryFilters,
    QueryResult,
    QueryIntent,
    RetrievalStrategy,
    SourceType,
)
from docsgpt.intelligence.topics import TopicTrend
from docsgpt.seed.intelligence_projects import (
    STAGE_A_WINDOW_END,
    STAGE_A_WINDOW_START,
    seed_stage_a_projects,
    stage_a_projects,
)


@pytest.fixture
def app() -> Flask:
    """Build an isolated Flask application with the intelligence namespace."""
    app = Flask(__name__)
    api = Api(app)
    api.add_namespace(intelligence_ns)

    @app.before_request
    def set_test_token() -> None:
        request.decoded_token = (
            {"sub": "user-1"} if request.headers.get("Authorization") else None
        )

    return app


@pytest.fixture
def client(app: Flask):
    """Return a client for the isolated intelligence API."""
    return app.test_client()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Provide the authorization header used by the route contract tests."""
    return {"Authorization": "Bearer test_token"}


@pytest.fixture
def mock_query_service(monkeypatch) -> MagicMock:
    """Stub the query application service while retaining its response shape."""
    result = QueryResult(
        answer="Dify added SSO.",
        claims=[
            Claim(
                id="claim-1",
                text="Dify added SSO.",
                kind=ClaimKind.FACT,
                evidence_ids=["evidence-1"],
                confidence=Confidence.HIGH,
            )
        ],
        evidence=[
            Evidence(
                id="evidence-1",
                record_id="release:1",
                repository="langgenius/dify",
                source_type=SourceType.RELEASE,
                title="Dify 1.0",
                excerpt="Added SSO support.",
                source_url="https://github.com/langgenius/dify/releases/tag/v1.0",
            )
        ],
        coverage=Coverage(
            repositories=["langgenius/dify"],
            date_from=date(2025, 9, 14),
            date_to=date(2026, 9, 14),
            counts={SourceType.RELEASE: 1},
        ),
        latency_ms=1,
        trace={
            "intent": QueryIntent.FACTUAL,
            "strategy": RetrievalStrategy.HYBRID,
            "applied_filters": {"repositories": ["langgenius/dify"]},
        },
    )
    service = MagicMock()
    service.query.return_value = result
    monkeypatch.setattr(
        "docsgpt.api.user.intelligence.routes.build_query_service",
        lambda: service,
    )
    return service


@contextmanager
def _fake_db():
    """Yield a fake connection for route tests that exercise repositories."""
    yield object()


def _patch_repository(monkeypatch, repository: MagicMock) -> None:
    """Patch both route transaction factories and repository construction."""
    monkeypatch.setattr(
        "docsgpt.api.user.intelligence.routes.db_readonly", _fake_db
    )
    monkeypatch.setattr(
        "docsgpt.api.user.intelligence.routes.db_session", _fake_db
    )
    monkeypatch.setattr(
        "docsgpt.api.user.intelligence.routes.IntelligenceRepository",
        lambda conn: repository,
    )


def test_query_requires_auth(client) -> None:
    response = client.post("/api/intelligence/query", json={"question": "x"})

    assert response.status_code == 401


def test_preflight_requires_auth(client) -> None:
    response = client.post(
        "/api/intelligence/preflight",
        json={"repository": "https://github.com/o/r"},
    )

    assert response.status_code == 401


def test_preflight_returns_setup_contract(client, auth_headers, monkeypatch) -> None:
    service = MagicMock()
    service.check.return_value = RepositoryPreflight(
        repository="o/r",
        default_branch="main",
        estimated_counts={"issues": 10, "releases": 2, "documents": 5},
    )
    monkeypatch.setattr(
        "docsgpt.api.user.intelligence.routes.build_preflight_service",
        lambda: service,
    )

    response = client.post(
        "/api/intelligence/preflight",
        headers=auth_headers,
        json={"repository": "https://github.com/o/r.git"},
    )

    assert response.status_code == 200
    assert response.json["preflight"]["repository"] == "o/r"
    assert response.json["preflight"]["estimated_counts"]["issues"] == 10
    service.check.assert_called_once_with("https://github.com/o/r.git")


def test_query_shape(client, auth_headers, mock_query_service) -> None:
    response = client.post(
        "/api/intelligence/query",
        headers=auth_headers,
        json={
            "question": "Which product added SSO?",
            "filters": {"repositories": ["langgenius/dify"]},
        },
    )

    assert response.status_code == 200
    assert set(response.json) == {
        "answer",
        "claims",
        "evidence",
        "coverage",
        "latency_ms",
        "trace",
    }
    mock_query_service.query.assert_called_once()


def test_query_rejects_invalid_request(client, auth_headers, mock_query_service) -> None:
    response = client.post(
        "/api/intelligence/query",
        headers=auth_headers,
        json={"question": ""},
    )

    assert response.status_code == 400
    mock_query_service.query.assert_not_called()


def test_topics_requires_auth(client) -> None:
    response = client.get("/api/intelligence/topics")

    assert response.status_code == 401


def test_topics_returns_owner_scoped_trends(client, auth_headers, monkeypatch) -> None:
    project_id = str(uuid4())
    repository = MagicMock()
    _patch_repository(monkeypatch, repository)
    trend_reader = MagicMock(
        return_value=[
            TopicTrend(
                cluster_id="topic-1",
                label="sso",
                repository="langgenius/dify",
                month="2026-01",
                count=3,
                snapshot_id="snapshot-1",
            )
        ]
    )
    monkeypatch.setattr(
        "docsgpt.api.user.intelligence.routes.topic_trends",
        trend_reader,
    )

    response = client.get(
        f"/api/intelligence/topics?project_ids={project_id}&source_types=issue"
        "&date_from=2026-01-01&date_to=2026-03-01",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json["trends"][0]["cluster_id"] == "topic-1"
    trend_reader.assert_called_once()
    project_ids, filters = trend_reader.call_args.args[:2]
    assert project_ids == [project_id]
    assert filters.source_types == [SourceType.ISSUE]
    assert filters.date_from == date(2026, 1, 1)
    assert filters.date_to == date(2026, 3, 1)
    assert trend_reader.call_args.kwargs["user_id"] == "user-1"
    assert trend_reader.call_args.kwargs["repository"] is repository


def test_comparison_returns_owner_scoped_matrix(client, auth_headers, monkeypatch) -> None:
    project_id = str(uuid4())
    repository = MagicMock()
    _patch_repository(monkeypatch, repository)
    service = MagicMock()
    service.compare.return_value = ComparisonResult(
        repositories=["langgenius/dify"],
        rows=[
            ComparisonRow(
                dimension="enterprise_sso",
                cells={
                    "langgenius/dify": ComparisonCell(
                        status="unknown",
                        display_label="尚未确认",
                    )
                },
            )
        ],
    )
    monkeypatch.setattr(
        "docsgpt.api.user.intelligence.routes.ComparisonService",
        lambda current_repository, user_id: service,
    )

    response = client.post(
        "/api/intelligence/comparison",
        headers=auth_headers,
        json={
            "project_ids": [project_id],
            "dimensions": ["enterprise_sso"],
            "filters": {"repositories": ["langgenius/dify"]},
        },
    )

    assert response.status_code == 200
    assert response.json["comparison"]["rows"][0]["cells"]["langgenius/dify"]["display_label"] == "尚未确认"
    service.compare.assert_called_once_with(
        [project_id],
        ["enterprise_sso"],
        QueryFilters(repositories=["langgenius/dify"]),
    )


def test_project_lookup_is_owner_scoped(client, auth_headers, monkeypatch) -> None:
    repository = MagicMock()
    repository.get_project.return_value = None
    _patch_repository(monkeypatch, repository)
    project_id = str(uuid4())

    response = client.get(
        f"/api/intelligence/projects/{project_id}", headers=auth_headers
    )

    assert response.status_code == 404
    repository.get_project.assert_called_once_with(project_id, "user-1")


def test_project_routes_reject_malformed_uuid(client, auth_headers, monkeypatch) -> None:
    repository = MagicMock()
    _patch_repository(monkeypatch, repository)

    response = client.get(
        "/api/intelligence/projects/not-a-uuid", headers=auth_headers
    )

    assert response.status_code == 400
    repository.get_project.assert_not_called()


def test_create_project_validates_request_before_db(client, auth_headers, monkeypatch) -> None:
    repository = MagicMock()
    _patch_repository(monkeypatch, repository)

    response = client.post(
        "/api/intelligence/projects",
        headers=auth_headers,
        json={
            "repository": "langgenius/dify",
            "window_start": "2026-01-01",
            "window_end": "2025-01-01",
        },
    )

    assert response.status_code == 400
    repository.create_project.assert_not_called()


def test_create_project_is_owner_scoped(client, auth_headers, monkeypatch) -> None:
    project_id = str(uuid4())
    repository = MagicMock()
    repository.create_project.return_value = {
        "id": project_id,
        "user_id": "user-1",
        "repository": "langgenius/dify",
        "window_start": date(2025, 9, 14),
        "window_end": date(2026, 9, 14),
    }
    _patch_repository(monkeypatch, repository)

    response = client.post(
        "/api/intelligence/projects",
        headers=auth_headers,
        json={
            "repository": "https://github.com/langgenius/dify.git",
            "window_start": "2025-09-14",
            "window_end": "2026-09-14",
        },
    )

    assert response.status_code == 201
    assert response.json["project"]["id"] == project_id
    repository.create_project.assert_called_once_with(
        user_id="user-1",
        repository="langgenius/dify",
        window_start=date(2025, 9, 14),
        window_end=date(2026, 9, 14),
    )


def test_sync_dispatches_owner_scoped_task(client, auth_headers, monkeypatch) -> None:
    project_id = str(uuid4())
    repository = MagicMock()
    repository.get_project.return_value = {
        "id": project_id,
        "user_id": "user-1",
        "repository": "langgenius/dify",
    }
    _patch_repository(monkeypatch, repository)
    task = MagicMock(id="task-1")
    sync_task = MagicMock()
    sync_task.delay.return_value = task
    monkeypatch.setattr(
        "docsgpt.api.user.intelligence.routes.sync_intelligence_project", sync_task
    )

    response = client.post(
        f"/api/intelligence/projects/{project_id}/sync",
        headers={**auth_headers, "Idempotency-Key": "sync-key-1"},
        json={},
    )

    assert response.status_code == 202
    assert response.json["task_id"] == "task-1"
    sync_task.delay.assert_called_once_with(
        project_id=project_id,
        user_id="user-1",
        idempotency_key="sync-key-1",
    )


def test_sync_run_and_overview_are_owner_scoped(
    client, auth_headers, monkeypatch
) -> None:
    run_id = str(uuid4())
    repository = MagicMock()
    repository.get_sync_run.return_value = {"id": run_id, "status": "complete"}
    repository.overview.return_value = {"projects": 1, "records": 3}
    _patch_repository(monkeypatch, repository)

    run_response = client.get(
        f"/api/intelligence/sync-runs/{run_id}", headers=auth_headers
    )
    overview_response = client.get(
        "/api/intelligence/overview", headers=auth_headers
    )

    assert run_response.status_code == 200
    assert run_response.json["sync_run"]["id"] == run_id
    assert overview_response.status_code == 200
    assert overview_response.json["overview"]["records"] == 3
    repository.get_sync_run.assert_called_once_with(run_id, "user-1")
    repository.overview.assert_called_once_with("user-1")


def test_list_projects_is_owner_scoped(client, auth_headers, monkeypatch) -> None:
    project_id = str(uuid4())
    repository = MagicMock()
    repository.list_projects.return_value = [
        {"id": project_id, "user_id": "user-1", "repository": "langgenius/dify"}
    ]
    _patch_repository(monkeypatch, repository)

    response = client.get("/api/intelligence/projects", headers=auth_headers)

    assert response.status_code == 200
    assert response.json["projects"][0]["id"] == project_id
    repository.list_projects.assert_called_once_with("user-1")


def test_reports_require_auth(client) -> None:
    """Report creation and retrieval must use the existing auth boundary."""
    assert client.post("/api/intelligence/reports", json={}).status_code == 401
    assert client.get(f"/api/intelligence/reports/{uuid4()}").status_code == 401
    assert (
        client.get(f"/api/intelligence/reports/{uuid4()}/download?format=pdf").status_code
        == 401
    )


def test_report_create_and_get_are_owner_scoped(
    client, auth_headers, mock_query_service, monkeypatch
) -> None:
    """Report JSON is saved and looked up through the authenticated owner."""
    project_id = str(uuid4())
    report_id = str(uuid4())
    repository = MagicMock()
    repository.save_report.return_value = {
        "id": report_id,
        "user_id": "user-1",
        "report_data": ReportService()
        .create(
            "user-1",
            [project_id],
            [mock_query_service.query.return_value],
        ),
    }
    repository.get_report.return_value = repository.save_report.return_value
    _patch_repository(monkeypatch, repository)
    result_data = mock_query_service.query.return_value.model_dump(mode="json")

    response = client.post(
        "/api/intelligence/reports",
        headers=auth_headers,
        json={"project_ids": [project_id], "results": [result_data]},
    )

    assert response.status_code == 201
    repository.save_report.assert_called_once()
    assert repository.save_report.call_args.args[0] == "user-1"
    assert repository.save_report.call_args.args[1]["project_ids"] == [project_id]

    lookup = client.get(
        f"/api/intelligence/reports/{report_id}", headers=auth_headers
    )

    assert lookup.status_code == 200
    assert lookup.json["report"]["id"] == report_id
    repository.get_report.assert_called_once_with(report_id, "user-1")


def test_report_downloads_saved_document_without_query(
    client, auth_headers, mock_query_service, monkeypatch
) -> None:
    """Markdown and PDF downloads use the saved report document directly."""
    project_id = str(uuid4())
    report_id = str(uuid4())
    report_data = ReportService().create(
        "user-1",
        [project_id],
        [mock_query_service.query.return_value],
    )
    repository = MagicMock()
    repository.get_report.return_value = {
        "id": report_id,
        "user_id": "user-1",
        "report_data": report_data,
    }
    _patch_repository(monkeypatch, repository)

    markdown_response = client.get(
        f"/api/intelligence/reports/{report_id}/download?format=markdown",
        headers=auth_headers,
    )
    pdf_response = client.get(
        f"/api/intelligence/reports/{report_id}/download?format=pdf",
        headers=auth_headers,
    )

    assert markdown_response.status_code == 200
    assert markdown_response.mimetype == "text/markdown"
    assert "filename*=UTF-8''" in markdown_response.headers["Content-Disposition"]
    assert "执行摘要" in markdown_response.data.decode("utf-8")
    assert pdf_response.status_code == 200
    assert pdf_response.mimetype == "application/pdf"
    assert pdf_response.data.startswith(b"%PDF")
    assert mock_query_service.query.call_count == 0


def test_report_export_failure_is_retryable_and_keeps_row(
    client, auth_headers, monkeypatch
) -> None:
    """A rendering error returns 500 without deleting the saved report."""
    report_id = str(uuid4())
    repository = MagicMock()
    repository.get_report.return_value = {
        "id": report_id,
        "user_id": "user-1",
        "report_data": {
            "title": "OpenScout AI 产品情报报告",
            "user_id": "user-1",
            "project_ids": [],
            "sections": [],
            "sources": [],
        },
    }
    _patch_repository(monkeypatch, repository)

    def fail_export(_report):
        raise RuntimeError("font unavailable")

    monkeypatch.setattr(
        "docsgpt.intelligence.report_service.render_pdf", fail_export
    )
    response = client.get(
        f"/api/intelligence/reports/{report_id}/download?format=pdf",
        headers=auth_headers,
    )

    assert response.status_code == 500
    assert response.json["success"] is False
    assert "retry" in response.json["message"]
    repository.get_report.assert_called_once_with(report_id, "user-1")
    repository.delete_report.assert_not_called()


def test_stage_a_seed_contains_exact_repositories() -> None:
    assert [item.repository for item in stage_a_projects()] == [
        "langgenius/dify",
        "infiniflow/ragflow",
        "labring/FastGPT",
    ]


def test_stage_a_seed_uses_fixed_window() -> None:
    assert STAGE_A_WINDOW_START.isoformat() == "2025-09-14"
    assert STAGE_A_WINDOW_END.isoformat() == "2026-09-14"
    assert all(
        item.window_start == STAGE_A_WINDOW_START
        and item.window_end == STAGE_A_WINDOW_END
        for item in stage_a_projects()
    )


def test_stage_a_seed_is_idempotent() -> None:
    class Repository:
        def __init__(self) -> None:
            self.rows: list[dict[str, object]] = []

        def find_project(self, user_id: str, repository: str):
            return next(
                (
                    row
                    for row in self.rows
                    if row["user_id"] == user_id and row["repository"] == repository
                ),
                None,
            )

        def create_project(self, user_id, repository, window_start, window_end):
            row = {
                "user_id": user_id,
                "repository": repository,
                "window_start": window_start,
                "window_end": window_end,
            }
            self.rows.append(row)
            return row

    repository = Repository()

    seed_stage_a_projects(repository, "user-1")
    seed_stage_a_projects(repository, "user-1")

    assert len(repository.rows) == 3
