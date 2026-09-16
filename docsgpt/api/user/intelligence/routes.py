"""Owner-scoped OpenScout intelligence API routes."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from pydantic import ValidationError

from docsgpt.intelligence.github_client import GitHubClient
from docsgpt.intelligence.query_service import QueryService
from docsgpt.intelligence.schemas import QueryRequest
from docsgpt.intelligence.tasks import sync_intelligence_project
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.intelligence import IntelligenceRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

intelligence_ns = Namespace(
    "intelligence",
    description="OpenScout product intelligence",
    path="/api",
)


def _ok(data: Any, status: int = 200):
    """Return a JSON response with the requested status code."""
    return make_response(jsonify(data), status)


def _error(message: str, status: int = 400):
    """Return the stable error envelope used by intelligence routes."""
    return _ok({"success": False, "message": message}, status)


def _current_user() -> str | None:
    """Read the authenticated subject populated by the auth boundary."""
    decoded = getattr(request, "decoded_token", None)
    if not isinstance(decoded, dict):
        return None
    subject = decoded.get("sub")
    return str(subject) if subject else None


def _json_row(row: dict[str, Any] | None) -> dict[str, Any]:
    """Render a repository row without exposing the legacy duplicate id."""
    if not row:
        return {}
    rendered = dict(row)
    rendered.pop("_id", None)
    for key, value in list(rendered.items()):
        if hasattr(value, "isoformat"):
            rendered[key] = value.isoformat()
        elif value is not None and key == "id":
            rendered[key] = str(value)
    return rendered


def _model_json(value: Any) -> Any:
    """Convert a Pydantic result or plain mapping to JSON-compatible data."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _parse_project_payload() -> tuple[str, date, date]:
    """Validate and normalize a project creation payload."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")

    raw_repository = payload.get("repository", "")
    if not isinstance(raw_repository, str):
        raise ValueError("repository must be a valid GitHub repository")
    repository = GitHubClient._normalize_repo(raw_repository)
    if not repository:
        raise ValueError("repository must be a valid GitHub repository")

    try:
        window_start = date.fromisoformat(str(payload["window_start"]))
        window_end = date.fromisoformat(str(payload["window_end"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("window_start and window_end must be ISO dates") from exc
    if window_end < window_start:
        raise ValueError("window_end must not be before window_start")
    return repository, window_start, window_end


def build_query_service() -> QueryService:
    """Build the default hybrid-only query service.

    The service accepts concrete retriever and generator implementations so
    application wiring can supply the configured HybridRetriever. The default
    instance remains safe when no intelligence index has been configured yet.
    """
    return QueryService()


@intelligence_ns.route("/intelligence/projects")
class IntelligenceProjects(Resource):
    """Create and list the caller's intelligence projects."""

    def get(self):
        """List projects owned by the authenticated caller."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        try:
            with db_readonly() as conn:
                rows = IntelligenceRepository(conn).list_projects(user_id)
            return _ok({"projects": [_json_row(row) for row in rows]})
        except Exception:
            logger.exception("Could not list intelligence projects")
            return _error("internal error", 500)

    def post(self):
        """Create one owner-scoped intelligence project."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        try:
            repository, window_start, window_end = _parse_project_payload()
        except ValueError as exc:
            return _error(str(exc), 400)

        try:
            with db_session() as conn:
                row = IntelligenceRepository(conn).create_project(
                    user_id=user_id,
                    repository=repository,
                    window_start=window_start,
                    window_end=window_end,
                )
            return _ok({"project": _json_row(row)}, 201)
        except Exception:
            logger.exception("Could not create intelligence project")
            return _error("internal error", 500)


@intelligence_ns.route("/intelligence/projects/<string:project_id>")
class IntelligenceProject(Resource):
    """Read one owner-scoped intelligence project."""

    def get(self, project_id: str):
        """Return a project only when it belongs to the caller."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        if not looks_like_uuid(project_id):
            return _error("project_id must be a UUID", 400)
        try:
            with db_readonly() as conn:
                row = IntelligenceRepository(conn).get_project(project_id, user_id)
            if row is None:
                return _error("project not found", 404)
            return _ok({"project": _json_row(row)})
        except Exception:
            logger.exception("Could not get intelligence project")
            return _error("internal error", 500)


@intelligence_ns.route("/intelligence/projects/<string:project_id>/sync")
class IntelligenceProjectSync(Resource):
    """Dispatch an owner-checked project synchronization task."""

    def post(self, project_id: str):
        """Queue a synchronization after verifying project ownership."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        if not looks_like_uuid(project_id):
            return _error("project_id must be a UUID", 400)

        try:
            with db_readonly() as conn:
                row = IntelligenceRepository(conn).get_project(project_id, user_id)
            if row is None:
                return _error("project not found", 404)
        except Exception:
            logger.exception("Could not verify intelligence project for sync")
            return _error("internal error", 500)

        payload = request.get_json(silent=True)
        payload_key = payload.get("idempotency_key") if isinstance(payload, dict) else None
        idempotency_key = request.headers.get("Idempotency-Key") or payload_key
        try:
            task = sync_intelligence_project.delay(
                project_id=project_id,
                user_id=user_id,
                idempotency_key=idempotency_key,
            )
            return _ok({"task_id": str(task.id)}, 202)
        except Exception:
            logger.exception("Could not dispatch intelligence sync")
            return _error("internal error", 500)


@intelligence_ns.route("/intelligence/sync-runs/<string:run_id>")
class IntelligenceSyncRun(Resource):
    """Read one synchronization run through its owning project."""

    def get(self, run_id: str):
        """Return a synchronization run only for its project owner."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        if not looks_like_uuid(run_id):
            return _error("run_id must be a UUID", 400)
        try:
            with db_readonly() as conn:
                row = IntelligenceRepository(conn).get_sync_run(run_id, user_id)
            if row is None:
                return _error("sync run not found", 404)
            return _ok({"sync_run": _json_row(row)})
        except Exception:
            logger.exception("Could not get intelligence sync run")
            return _error("internal error", 500)


@intelligence_ns.route("/intelligence/overview")
class IntelligenceOverview(Resource):
    """Return owner-scoped intelligence coverage aggregates."""

    def get(self):
        """Return the overview for all projects owned by the caller."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        try:
            with db_readonly() as conn:
                overview = IntelligenceRepository(conn).overview(user_id)
            return _ok({"overview": _json_row(overview)})
        except Exception:
            logger.exception("Could not get intelligence overview")
            return _error("internal error", 500)


@intelligence_ns.route("/intelligence/query")
class IntelligenceQuery(Resource):
    """Answer a first-version hybrid-only intelligence query."""

    def post(self):
        """Validate the query contract and delegate to QueryService."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        try:
            query_request = QueryRequest.model_validate(request.get_json(silent=True) or {})
        except ValidationError as exc:
            return _error(exc.errors()[0]["msg"], 400)

        try:
            result = build_query_service().query(query_request, user_id)
            return _ok(_model_json(result))
        except ValueError as exc:
            return _error(str(exc), 400)
        except Exception:
            logger.exception("Could not answer intelligence query")
            return _error("internal error", 500)


__all__ = [
    "IntelligenceOverview",
    "IntelligenceProject",
    "IntelligenceProjectSync",
    "IntelligenceProjects",
    "IntelligenceQuery",
    "IntelligenceSyncRun",
    "build_query_service",
    "intelligence_ns",
]
