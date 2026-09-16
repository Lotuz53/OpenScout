"""Contract tests for sanitized OpenScout report sharing."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from flask import Flask, request
from flask_restx import Api
from sqlalchemy import text

from docsgpt.api.public.intelligence import public_intelligence
from docsgpt.api.user.intelligence.routes import intelligence_ns
from docsgpt.storage.db.repositories.intelligence import IntelligenceRepository


REPORT_ID = str(uuid4())
SHARED_TOKEN = "shared-report-token"


@pytest.fixture
def app() -> Flask:
    """Build an isolated app with authenticated and public report routes."""
    app = Flask(__name__)
    app.register_blueprint(public_intelligence)
    api = Api(app)
    api.add_namespace(intelligence_ns)

    @app.before_request
    def set_test_token() -> None:
        request.decoded_token = (
            {"sub": "owner-1"} if request.headers.get("Authorization") else None
        )

    return app


@pytest.fixture
def client(app: Flask):
    """Return an isolated report-sharing client."""
    return app.test_client()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Provide the authorization header used by route contract tests."""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def shared_report() -> SimpleNamespace:
    """Return a shared report row containing fields that must be redacted."""
    return SimpleNamespace(
        token=SHARED_TOKEN,
        row={
            "report_data": {
                "title": "OpenScout AI 产品情报报告",
                "user_id": "owner-secret",
                "project_ids": ["private-project-id"],
                "trace": {"request_id": "private-trace"},
                "sections": [
                    {
                        "heading": "执行摘要",
                        "paragraphs": ["公开摘要"],
                        "bullets": ["公开要点"],
                        "internal_note": "private-section-note",
                    }
                ],
                "sources": [
                    {
                        "id": "evidence-1",
                        "title": "公开来源",
                        "url": "https://github.com/example/project/issues/1",
                        "repository": "example/project",
                        "source_type": "issue",
                        "excerpt": "private source excerpt",
                    }
                ],
                "coverage": {
                    "repositories": ["example/project"],
                    "date_from": "2026-01-01",
                    "date_to": "2026-09-01",
                    "counts": {"issue": 1},
                    "capped": False,
                    "private_coverage_note": "do not publish",
                },
            },
            "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        },
    )


@contextmanager
def _fake_db():
    """Yield a fake connection for route tests that use repositories."""
    yield object()


def _patch_public_repository(monkeypatch, repository: MagicMock) -> None:
    """Patch the public route's read-only database and repository adapter."""
    monkeypatch.setattr(
        "docsgpt.api.public.intelligence.db_readonly", _fake_db
    )
    monkeypatch.setattr(
        "docsgpt.api.public.intelligence.IntelligenceRepository",
        lambda conn: repository,
    )


def _patch_user_repository(monkeypatch, repository: MagicMock) -> None:
    """Patch authenticated route database factories and repository creation."""
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


def test_public_report_projection_redacts_internal_fields(
    client, shared_report, monkeypatch
) -> None:
    """A public report contains only the documented read-only projection."""
    repository = MagicMock()
    repository.get_public_report.return_value = shared_report.row
    _patch_public_repository(monkeypatch, repository)

    response = client.get(f"/api/public/intelligence/reports/{shared_report.token}")
    payload = response.get_json()

    assert response.status_code == 200
    assert set(payload["report"]) == {
        "title",
        "sections",
        "sources",
        "coverage",
        "created_at",
    }
    assert payload["report"]["title"] == "OpenScout AI 产品情报报告"
    assert payload["report"]["sources"] == [
        {
            "title": "公开来源",
            "url": "https://github.com/example/project/issues/1",
        }
    ]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "user_id" not in serialized
    assert "trace" not in serialized
    assert "private-project-id" not in serialized
    assert "private-section-note" not in serialized
    assert "private source excerpt" not in serialized
    repository.get_public_report.assert_called_once_with(
        hashlib.sha256(shared_report.token.encode("utf-8")).hexdigest()
    )


def test_revoked_token_returns_not_found(client, monkeypatch) -> None:
    """Revoked or unknown tokens never reveal whether a report existed."""
    repository = MagicMock()
    repository.get_public_report.return_value = None
    _patch_public_repository(monkeypatch, repository)

    response = client.get(f"/api/public/intelligence/reports/{SHARED_TOKEN}")

    assert response.status_code == 404


def test_share_requires_authentication(client) -> None:
    """Share creation and revocation remain in the authenticated namespace."""
    assert client.post(f"/api/intelligence/reports/{REPORT_ID}/share").status_code == 401
    assert client.delete(f"/api/intelligence/reports/{REPORT_ID}/share").status_code == 401


def test_owner_can_create_share_and_plaintext_is_returned_once(
    client, auth_headers, monkeypatch
) -> None:
    """Share creation stores a digest and returns a high-entropy token."""
    repository = MagicMock()
    repository.create_report_share.side_effect = [
        {"report_id": REPORT_ID, "shared_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
        {"report_id": REPORT_ID, "shared_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
    ]
    _patch_user_repository(monkeypatch, repository)

    first = client.post(
        f"/api/intelligence/reports/{REPORT_ID}/share", headers=auth_headers
    )
    second = client.post(
        f"/api/intelligence/reports/{REPORT_ID}/share", headers=auth_headers
    )

    assert first.status_code == 201
    assert second.status_code == 201
    first_token = first.get_json()["share"]["token"]
    second_token = second.get_json()["share"]["token"]
    assert len(first_token) >= 43
    assert len(second_token) >= 43
    assert first_token != second_token

    for call, token in zip(repository.create_report_share.call_args_list, [first_token, second_token]):
        assert call.args[0] == REPORT_ID
        assert call.args[1] == "owner-1"
        token_hash = call.args[2]
        assert re.fullmatch(r"[0-9a-f]{64}", token_hash)
        assert token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert token_hash != token

    assert "share_token_hash" not in json.dumps(first.get_json())
    assert first.get_json()["share"]["path"].startswith("/reports/shared/")


def test_non_owner_cannot_create_or_revoke_share(
    client, auth_headers, monkeypatch
) -> None:
    """Repository ownership checks make another user's report indistinguishable."""
    repository = MagicMock()
    repository.create_report_share.return_value = None
    repository.revoke_report_share.return_value = None
    _patch_user_repository(monkeypatch, repository)

    create_response = client.post(
        f"/api/intelligence/reports/{REPORT_ID}/share", headers=auth_headers
    )
    revoke_response = client.delete(
        f"/api/intelligence/reports/{REPORT_ID}/share", headers=auth_headers
    )

    assert create_response.status_code == 404
    assert revoke_response.status_code == 404
    repository.create_report_share.assert_called_once()
    repository.revoke_report_share.assert_called_once_with(REPORT_ID, "owner-1")


def test_owner_report_response_does_not_expose_share_digest(
    client, auth_headers, monkeypatch
) -> None:
    """The authenticated report response never returns the stored token hash."""
    repository = MagicMock()
    repository.get_report.return_value = {
        "id": REPORT_ID,
        "user_id": "owner-1",
        "report_data": {"title": "OpenScout report", "sections": [], "sources": []},
        "share_token_hash": "a" * 64,
        "shared_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
    }
    _patch_user_repository(monkeypatch, repository)

    response = client.get(
        f"/api/intelligence/reports/{REPORT_ID}", headers=auth_headers
    )

    assert response.status_code == 200
    assert "share_token_hash" not in json.dumps(response.get_json())


def test_owner_can_revoke_share(client, auth_headers, monkeypatch) -> None:
    """An owner can invalidate a token without exposing report contents."""
    repository = MagicMock()
    repository.revoke_report_share.return_value = {
        "report_id": REPORT_ID,
        "revoked_at": datetime(2026, 9, 2, tzinfo=timezone.utc),
    }
    _patch_user_repository(monkeypatch, repository)

    response = client.delete(
        f"/api/intelligence/reports/{REPORT_ID}/share", headers=auth_headers
    )

    assert response.status_code == 204
    assert response.data == b""
    repository.revoke_report_share.assert_called_once_with(REPORT_ID, "owner-1")


def test_repository_share_lifecycle_stores_only_digest_and_enforces_owner(pg_conn) -> None:
    """The migrated report table supports owner checks and revocation."""
    repository = IntelligenceRepository(pg_conn)
    report = repository.save_report(
        "owner-1",
        {
            "title": "OpenScout report",
            "sections": [],
            "sources": [],
        },
    )
    report_id = str(report["id"])
    token = "a" * 43
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    share = repository.create_report_share(report_id, "owner-1", token_hash)
    stored = pg_conn.execute(
        text(
            """
            SELECT share_token_hash, shared_at, revoked_at
            FROM intelligence_reports
            WHERE id = CAST(:report_id AS uuid)
            """
        ),
        {"report_id": report_id},
    ).mappings().one()

    assert share["report_id"] == report_id
    assert stored["share_token_hash"] == token_hash
    assert stored["shared_at"] is not None
    assert stored["revoked_at"] is None
    assert repository.get_public_report(token_hash)["report_data"]["title"] == "OpenScout report"
    assert repository.create_report_share(report_id, "other-user", token_hash) is None
    assert repository.revoke_report_share(report_id, "other-user") is None

    revoked = repository.revoke_report_share(report_id, "owner-1")

    assert revoked["report_id"] == report_id
    assert repository.get_public_report(token_hash) is None
