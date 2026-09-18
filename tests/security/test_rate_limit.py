"""Tests for the shared high-cost API rate limiter."""

from unittest.mock import MagicMock

import pytest
from flask import Flask, jsonify, request

import docsgpt.security.rate_limit as rate_limit_module
from docsgpt.security.rate_limit import rate_limit


@pytest.fixture(autouse=True)
def reset_rate_limit_state(monkeypatch):
    rate_limit_module._local_windows.clear()
    monkeypatch.setattr(rate_limit_module, "_redis_fallback_logged", False)
    yield
    rate_limit_module._local_windows.clear()


@pytest.fixture
def app() -> Flask:
    app = Flask(__name__)

    @app.before_request
    def set_test_identity():
        user_id = request.headers.get("X-Test-User")
        request.decoded_token = {"sub": user_id} if user_id else None

    @app.get("/projects/<project_id>")
    @rate_limit("test", limit=2, window_seconds=60, project_limit=1)
    def project_route(project_id: str):
        return jsonify({"project_id": project_id})

    return app


def test_rate_limit_returns_429_and_retry_after(app, monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module, "get_redis_instance", lambda: None)
    client = app.test_client()

    first = client.get("/projects/project-1", headers={"X-Test-User": "user-1"})
    second = client.get("/projects/project-1", headers={"X-Test-User": "user-1"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.get_json() == {
        "success": False,
        "message": "rate limit exceeded",
    }
    assert int(second.headers["Retry-After"]) >= 1


def test_authenticated_limit_uses_user_and_project_scope(app, monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module, "get_redis_instance", lambda: None)
    client = app.test_client()

    first = client.get("/projects/project-1", headers={"X-Test-User": "user-1"})
    other_project = client.get(
        "/projects/project-2", headers={"X-Test-User": "user-1"}
    )
    same_project_other_user = client.get(
        "/projects/project-1", headers={"X-Test-User": "user-2"}
    )

    assert first.status_code == 200
    assert other_project.status_code == 200
    assert same_project_other_user.status_code == 429


def test_no_auth_limit_uses_client_ip(app, monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module, "get_redis_instance", lambda: None)
    client = app.test_client()

    first = client.get("/projects/project-1", environ_base={"REMOTE_ADDR": "10.0.0.1"})
    second = client.get("/projects/project-1", environ_base={"REMOTE_ADDR": "10.0.0.1"})
    other_ip = client.get("/projects/project-2", environ_base={"REMOTE_ADDR": "10.0.0.2"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert other_ip.status_code == 200


def test_redis_denial_is_returned_with_redis_retry_after(app, monkeypatch) -> None:
    redis_client = MagicMock()
    redis_client.eval.return_value = [0, 7]
    monkeypatch.setattr(rate_limit_module, "get_redis_instance", lambda: redis_client)

    response = app.test_client().get(
        "/projects/project-1", headers={"X-Test-User": "user-1"}
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    redis_client.eval.assert_called_once()


def test_redis_failure_uses_bounded_local_fallback_and_logs(app, monkeypatch, caplog) -> None:
    redis_client = MagicMock()
    redis_client.eval.side_effect = RuntimeError("redis down")
    monkeypatch.setattr(rate_limit_module, "get_redis_instance", lambda: redis_client)

    with caplog.at_level("WARNING", logger="docsgpt.security.rate_limit"):
        client = app.test_client()
        first = client.get("/projects/project-1", headers={"X-Test-User": "user-1"})
        second = client.get("/projects/project-1", headers={"X-Test-User": "user-1"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert "local fallback" in caplog.text
