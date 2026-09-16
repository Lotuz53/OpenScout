"""Owner-scoped OpenScout intelligence API routes."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import logging
from datetime import date, datetime, timezone
import secrets
from typing import Any

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from pydantic import ValidationError

from docsgpt.intelligence.comparison import ComparisonService
from docsgpt.intelligence.github_client import GitHubClient
from docsgpt.intelligence.preflight import RepositoryPreflightService
from docsgpt.intelligence.query_service import QueryService
from docsgpt.intelligence.report_service import (
    ReportExportError,
    ReportNotFoundError,
    ReportService,
)
from docsgpt.intelligence.schemas import QueryFilters, QueryRequest
from docsgpt.intelligence.topics import topic_trends
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.intelligence import IntelligenceRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

# Resolved lazily because the task module imports the shared idempotency
# decorator, which loads the user API package during Celery autodiscovery.
sync_intelligence_project: Any | None = None

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


def _sync_task() -> Any:
    """Return the Celery sync task while preserving test/application patches."""
    global sync_intelligence_project
    if sync_intelligence_project is None:
        from docsgpt.intelligence.tasks import sync_intelligence_project as task

        sync_intelligence_project = task
    return sync_intelligence_project


def _json_row(row: dict[str, Any] | None) -> dict[str, Any]:
    """Render a repository row without exposing the legacy duplicate id."""
    if not row:
        return {}
    rendered = dict(row)
    rendered.pop("_id", None)
    rendered.pop("share_token_hash", None)
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


def _split_query_values(*names: str) -> list[str]:
    """Read comma-separated or repeated query values without duplicates."""
    values: list[str] = []
    for name in names:
        for raw_value in request.args.getlist(name):
            values.extend(
                value.strip()
                for value in raw_value.split(",")
                if value.strip()
            )
    return list(dict.fromkeys(values))


def _parse_topic_query() -> tuple[list[str], QueryFilters]:
    """Parse topic project ids and record filters from query parameters."""
    project_ids = _split_query_values("project_ids", "project_id")
    for project_id in project_ids:
        if not looks_like_uuid(project_id):
            raise ValueError("project_ids must contain UUIDs")
    raw_filters: dict[str, Any] = {
        "repositories": _split_query_values("repositories", "repository"),
        "source_types": _split_query_values("source_types", "source_type"),
    }
    for field in ("date_from", "date_to"):
        value = request.args.get(field)
        if value:
            raw_filters[field] = value
    try:
        filters = QueryFilters.model_validate(raw_filters)
    except ValidationError as exc:
        raise ValueError(exc.errors()[0]["msg"]) from exc
    return project_ids, filters


def _parse_comparison_payload() -> tuple[list[str], list[str], QueryFilters]:
    """Validate project ids, comparison dimensions, and explicit filters."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")

    project_ids = payload.get("project_ids")
    if not isinstance(project_ids, list) or not project_ids:
        raise ValueError("project_ids must be a non-empty list")
    if any(not isinstance(project_id, str) or not looks_like_uuid(project_id) for project_id in project_ids):
        raise ValueError("project_ids must contain UUIDs")

    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ValueError("dimensions must be a non-empty list")
    if any(not isinstance(dimension, str) or not dimension.strip() for dimension in dimensions):
        raise ValueError("dimensions must contain non-empty strings")

    try:
        filters = QueryFilters.model_validate(payload.get("filters") or {})
    except ValidationError as exc:
        raise ValueError(exc.errors()[0]["msg"]) from exc
    return list(dict.fromkeys(project_ids)), list(dict.fromkeys(dimensions)), filters


def _parse_report_payload() -> tuple[list[str], list[Any]]:
    """Validate project ids and saved structured results for a report."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")

    project_ids = payload.get("project_ids")
    if not isinstance(project_ids, list) or not project_ids:
        raise ValueError("project_ids must be a non-empty list")
    if any(not isinstance(project_id, str) or not looks_like_uuid(project_id) for project_id in project_ids):
        raise ValueError("project_ids must contain UUIDs")

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("results must be a non-empty list")
    if any(not isinstance(result, dict) for result in results):
        raise ValueError("results must contain JSON objects")
    return list(dict.fromkeys(project_ids)), results


def build_query_service() -> QueryService:
    """Build the default hybrid-only query service.

    The service accepts concrete retriever and generator implementations so
    application wiring can supply the configured HybridRetriever. The default
    instance remains safe when no intelligence index has been configured yet.
    """
    return QueryService()


def build_report_service(repository: Any, user_id: str) -> ReportService:
    """Build an owner-scoped report service for one request transaction."""
    return ReportService(repository=repository, user_id=user_id)


def build_preflight_service() -> RepositoryPreflightService:
    """Build the GitHub repository preflight service for one request."""
    return RepositoryPreflightService(GitHubClient())


@intelligence_ns.route("/intelligence/preflight")
class IntelligencePreflight(Resource):
    """Inspect a user-supplied repository before project creation."""

    def post(self):
        """Return public repository scope, estimates, and setup warnings."""
        if not _current_user():
            return _error("unauthorized", 401)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("repository"), str):
            return _error("repository must be a valid GitHub repository", 400)
        try:
            result = build_preflight_service().check(payload["repository"])
            return _ok({"preflight": asdict(result)})
        except Exception:
            logger.exception("Could not preflight GitHub repository")
            return _error("GitHub repository preflight is unavailable", 502)


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
        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or payload_key
            or f"openscout-sync:{project_id}:{datetime.now(timezone.utc).isoformat()}"
        )
        try:
            task = _sync_task().delay(
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


@intelligence_ns.route("/intelligence/topics")
class IntelligenceTopics(Resource):
    """Return owner-scoped monthly issue topic trends."""

    def get(self):
        """Read persisted topic trends for selected projects and filters."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        try:
            project_ids, filters = _parse_topic_query()
        except ValueError as exc:
            return _error(str(exc), 400)

        try:
            with db_readonly() as conn:
                trends = topic_trends(
                    project_ids,
                    filters,
                    repository=IntelligenceRepository(conn),
                    user_id=user_id,
                )
            return _ok({"trends": [_model_json(trend) for trend in trends]})
        except ValueError as exc:
            return _error(str(exc), 400)
        except Exception:
            logger.exception("Could not read intelligence topic trends")
            return _error("internal error", 500)


@intelligence_ns.route("/intelligence/comparison")
class IntelligenceComparison(Resource):
    """Return an owner-scoped evidence-backed product comparison."""

    def post(self):
        """Build a comparison matrix from explicit project and feature inputs."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        try:
            project_ids, dimensions, filters = _parse_comparison_payload()
        except ValueError as exc:
            return _error(str(exc), 400)

        try:
            with db_readonly() as conn:
                result = ComparisonService(
                    IntelligenceRepository(conn), user_id=user_id
                ).compare(project_ids, dimensions, filters)
            return _ok({"comparison": _model_json(result)})
        except ValueError as exc:
            return _error(str(exc), 400)
        except Exception:
            logger.exception("Could not build intelligence comparison")
            return _error("internal error", 500)


@intelligence_ns.route("/intelligence/reports")
class IntelligenceReports(Resource):
    """Create owner-scoped reports from already-saved intelligence results."""

    def post(self):
        """Persist the structured report document before any rendering."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        try:
            project_ids, results = _parse_report_payload()
        except ValueError as exc:
            return _error(str(exc), 400)

        try:
            with db_session() as conn:
                row = build_report_service(
                    IntelligenceRepository(conn), user_id
                ).create(user_id, project_ids, results)
            return _ok({"report": _json_row(row)}, 201)
        except (TypeError, ValueError) as exc:
            return _error(str(exc), 400)
        except Exception:
            logger.exception("Could not create intelligence report")
            return _error("internal error", 500)


@intelligence_ns.route("/intelligence/reports/<string:report_id>")
class IntelligenceReport(Resource):
    """Read one owner-scoped structured report."""

    def get(self, report_id: str):
        """Return persisted report JSON without invoking a query service."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        if not looks_like_uuid(report_id):
            return _error("report_id must be a UUID", 400)
        try:
            with db_readonly() as conn:
                row = build_report_service(
                    IntelligenceRepository(conn), user_id
                ).get(report_id)
            return _ok({"report": _json_row(row)})
        except ReportNotFoundError:
            return _error("report not found", 404)
        except Exception:
            logger.exception("Could not get intelligence report")
            return _error("internal error", 500)


@intelligence_ns.route("/intelligence/reports/<string:report_id>/share")
class IntelligenceReportShare(Resource):
    """Create or revoke one owner-scoped public report link."""

    def post(self, report_id: str):
        """Create a new share token and return its plaintext once."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        if not looks_like_uuid(report_id):
            return _error("report_id must be a UUID", 400)

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        try:
            with db_session() as conn:
                row = IntelligenceRepository(conn).create_report_share(
                    report_id, user_id, token_hash
                )
            if row is None:
                return _error("report not found", 404)
            return _ok(
                {
                    "share": {
                        "token": token,
                        "path": f"/reports/shared/{token}",
                        "shared_at": _json_row(row).get("shared_at"),
                    }
                },
                201,
            )
        except Exception:
            logger.exception("Could not create intelligence report share")
            return _error("internal error", 500)

    def delete(self, report_id: str):
        """Revoke a public report link without returning report contents."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        if not looks_like_uuid(report_id):
            return _error("report_id must be a UUID", 400)
        try:
            with db_session() as conn:
                row = IntelligenceRepository(conn).revoke_report_share(
                    report_id, user_id
                )
            if row is None:
                return _error("report not found", 404)
            return make_response("", 204)
        except Exception:
            logger.exception("Could not revoke intelligence report share")
            return _error("internal error", 500)


@intelligence_ns.route("/intelligence/reports/<string:report_id>/download")
class IntelligenceReportDownload(Resource):
    """Download a saved report as Markdown or PDF."""

    def get(self, report_id: str):
        """Render only the saved report document and return an attachment."""
        user_id = _current_user()
        if not user_id:
            return _error("unauthorized", 401)
        if not looks_like_uuid(report_id):
            return _error("report_id must be a UUID", 400)
        format_name = request.args.get("format", "markdown")
        if format_name not in {"markdown", "pdf"}:
            return _error("format must be markdown or pdf", 400)

        try:
            with db_readonly() as conn:
                content = build_report_service(
                    IntelligenceRepository(conn), user_id
                ).export(report_id, format_name)
            extension = "md" if format_name == "markdown" else "pdf"
            response = make_response(content, 200)
            response.headers["Content-Disposition"] = (
                f'attachment; filename="openscout-report-{report_id}.{extension}"; '
                f"filename*=UTF-8''openscout-report-{report_id}.{extension}"
            )
            response.headers["Content-Type"] = (
                "text/markdown; charset=utf-8"
                if format_name == "markdown"
                else "application/pdf"
            )
            return response
        except ReportNotFoundError:
            return _error("report not found", 404)
        except ValueError as exc:
            return _error(str(exc), 400)
        except ReportExportError:
            logger.exception("Could not export intelligence report")
            return _error("report export failed; retryable", 500)
        except Exception:
            logger.exception("Could not download intelligence report")
            return _error("internal error", 500)


__all__ = [
    "IntelligencePreflight",
    "IntelligenceOverview",
    "IntelligenceReport",
    "IntelligenceReportDownload",
    "IntelligenceReportShare",
    "IntelligenceReports",
    "IntelligenceProject",
    "IntelligenceProjectSync",
    "IntelligenceProjects",
    "IntelligenceComparison",
    "IntelligenceQuery",
    "IntelligenceSyncRun",
    "IntelligenceTopics",
    "build_preflight_service",
    "build_query_service",
    "build_report_service",
    "intelligence_ns",
]
