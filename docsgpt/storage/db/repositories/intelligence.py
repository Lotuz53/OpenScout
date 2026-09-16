"""Persistence for OpenScout intelligence projects and evidence."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from docsgpt.intelligence.analytics import (
    ALLOWED_DIMENSIONS,
    ALLOWED_METRICS,
    ALLOWED_ORDERS,
)
from docsgpt.intelligence.schemas import IntelligenceRecord, QueryFilters, SyncSummary
from docsgpt.storage.db.base_repository import row_to_dict


_OCCURRED_AT_SQL = (
    "COALESCE(r.published_at, r.created_at, r.updated_at, r.retrieved_at)"
)
_DIMENSION_SQL = {
    "repository": ("r.repository", "r.repository", ""),
    "source_type": ("r.source_type", "r.source_type", ""),
    "label": (
        "labels.label",
        "labels.label",
        "CROSS JOIN LATERAL jsonb_array_elements_text(r.labels) AS labels(label)",
    ),
    "month": (
        f"to_char(date_trunc('month', {_OCCURRED_AT_SQL}), 'YYYY-MM')",
        f"to_char(date_trunc('month', {_OCCURRED_AT_SQL}), 'YYYY-MM')",
        "",
    ),
    "state": ("COALESCE(r.state, 'unknown')", "COALESCE(r.state, 'unknown')", ""),
}
_METRIC_SQL = {
    "count": "COUNT(*)",
    "median_comments": "percentile_cont(0.5) WITHIN GROUP (ORDER BY r.comments_count)",
    "sum_reactions": "COALESCE(SUM(r.reactions_count), 0)",
}
_ORDER_SQL = {
    "value_asc": "value ASC, dimension ASC",
    "value_desc": "value DESC, dimension ASC",
    "period_asc": "dimension ASC, value DESC",
}


@dataclass(frozen=True)
class UpsertOutcome:
    """Describe whether an intelligence record changed during an upsert."""

    record_id: str
    changed: bool


class IntelligenceRepository:
    """SQL repository for owner-scoped OpenScout persistence."""

    def __init__(self, conn: Connection) -> None:
        """Initialize the repository with an active SQLAlchemy connection.

        Args:
            conn: Connection whose transaction is controlled by the caller.
        """
        self._conn = conn

    def create_project(
        self,
        user_id: str,
        repository: str,
        window_start: date,
        window_end: date,
    ) -> dict[str, Any]:
        """Create an owner-scoped intelligence project.

        Args:
            user_id: Authenticated owner identifier.
            repository: GitHub ``owner/name`` repository slug.
            window_start: Inclusive data window start.
            window_end: Inclusive data window end.

        Returns:
            The inserted project row.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO intelligence_projects
                    (user_id, repository, window_start, window_end)
                VALUES (:user_id, :repository, :window_start, :window_end)
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "repository": repository,
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        return row_to_dict(result.fetchone())


    def get_project(self, project_id: str, user_id: str) -> dict[str, Any] | None:
        """Return a project only when it belongs to ``user_id``.

        Args:
            project_id: UUID of the intelligence project.
            user_id: Authenticated owner identifier.

        Returns:
            The project row or ``None`` when it is missing or not owned by the user.
        """
        result = self._conn.execute(
            text(
                """
                SELECT *
                FROM intelligence_projects
                WHERE id = CAST(:project_id AS uuid)
                  AND user_id = :user_id
                """
            ),
            {"project_id": project_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def find_project(self, user_id: str, repository: str) -> dict[str, Any] | None:
        """Return an owner's project for a repository, if it already exists."""
        result = self._conn.execute(
            text(
                """
                SELECT *
                FROM intelligence_projects
                WHERE user_id = :user_id
                  AND repository = :repository
                ORDER BY created_at ASC
                LIMIT 1
                """
            ),
            {"user_id": user_id, "repository": repository},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_projects(self, user_id: str) -> list[dict[str, Any]]:
        """List all intelligence projects owned by ``user_id``."""
        result = self._conn.execute(
            text(
                """
                SELECT *
                FROM intelligence_projects
                WHERE user_id = :user_id
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"user_id": user_id},
        )
        return [row_to_dict(row) for row in result.fetchall()]

    def get_sync_run(self, run_id: str, user_id: str) -> dict[str, Any] | None:
        """Return a synchronization run only through an owned project."""
        result = self._conn.execute(
            text(
                """
                SELECT r.*
                FROM intelligence_sync_runs AS r
                JOIN intelligence_projects AS p ON p.id = r.project_id
                WHERE r.id = CAST(:run_id AS uuid)
                  AND p.user_id = :user_id
                """
            ),
            {"run_id": run_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def overview(self, user_id: str) -> dict[str, Any]:
        """Return owner-scoped record counts and synchronization coverage."""
        totals = self._conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT p.id) AS projects,
                       COUNT(r.id) AS records,
                       MIN(p.window_start) AS date_from,
                       MAX(p.window_end) AS date_to,
                       MAX(p.last_synced_at) AS last_synced_at
                FROM intelligence_projects AS p
                LEFT JOIN intelligence_records AS r ON r.project_id = p.id
                WHERE p.user_id = :user_id
                """
            ),
            {"user_id": user_id},
        ).fetchone()
        counts = self._conn.execute(
            text(
                """
                SELECT r.source_type, COUNT(*) AS count
                FROM intelligence_records AS r
                JOIN intelligence_projects AS p ON p.id = r.project_id
                WHERE p.user_id = :user_id
                GROUP BY r.source_type
                """
            ),
            {"user_id": user_id},
        ).fetchall()
        statuses = self._conn.execute(
            text(
                """
                SELECT p.status, COUNT(*) AS count
                FROM intelligence_projects AS p
                WHERE p.user_id = :user_id
                GROUP BY p.status
                """
            ),
            {"user_id": user_id},
        ).fetchall()

        totals_row = row_to_dict(totals)
        return {
            "projects": int(totals_row.get("projects") or 0),
            "records": int(totals_row.get("records") or 0),
            "counts": {
                str(row._mapping["source_type"]): int(row._mapping["count"])
                for row in counts
            },
            "coverage": {
                "date_from": totals_row.get("date_from"),
                "date_to": totals_row.get("date_to"),
            },
            "last_synced_at": totals_row.get("last_synced_at"),
            "statuses": {
                str(row._mapping["status"]): int(row._mapping["count"])
                for row in statuses
            },
        }

    def aggregate(
        self,
        user_id: str,
        project_ids: Sequence[str],
        query: Any,
    ) -> dict[str, Any]:
        """Run one owner-scoped aggregate using a fixed SQL whitelist.

        Args:
            user_id: Authenticated owner whose projects are in scope.
            project_ids: Optional project UUIDs to narrow the owner scope.
            query: Validated aggregate query with metric, dimension, order,
                limit, and ``QueryFilters`` attributes.

        Returns:
            Aggregate rows, exact SQL coverage, and whether the row limit
            truncated the grouped result.

        Raises:
            ValueError: If the aggregate selector or project id is invalid.
        """
        metric = str(query.metric)
        dimension = str(query.dimension)
        order = str(query.order)
        if metric not in ALLOWED_METRICS:
            raise ValueError(f"metric {metric!r} is not allowed")
        if dimension not in ALLOWED_DIMENSIONS:
            raise ValueError(f"dimension {dimension!r} is not allowed")
        if order not in ALLOWED_ORDERS:
            raise ValueError(f"order {order!r} is not allowed")

        filters = getattr(query, "filters", QueryFilters())
        where, params = _analytics_scope(user_id, project_ids, filters)
        params["aggregate_limit"] = max(1, min(100, int(query.limit)))
        dimension_sql, group_sql, join_sql = _DIMENSION_SQL[dimension]
        metric_sql = _METRIC_SQL[metric]
        order_sql = _ORDER_SQL[order]
        result = self._conn.execute(
            text(
                f"""
                SELECT {dimension_sql} AS dimension,
                       {metric_sql} AS value,
                       COUNT(*) OVER () AS total_groups
                FROM intelligence_records AS r
                JOIN intelligence_projects AS p ON p.id = r.project_id
                {join_sql}
                WHERE {' AND '.join(where)}
                GROUP BY {group_sql}
                ORDER BY {order_sql}
                LIMIT :aggregate_limit
                """
            ),
            params,
        )
        rows: list[dict[str, Any]] = []
        total_groups = 0
        for row in result.fetchall():
            mapping = row._mapping
            total_groups = max(total_groups, int(mapping.get("total_groups") or 0))
            rows.append(
                {
                    "dimension": mapping.get("dimension"),
                    "value": mapping.get("value"),
                }
            )

        return {
            "rows": rows,
            "coverage": self._aggregate_coverage(user_id, project_ids, filters),
            "capped": total_groups > params["aggregate_limit"],
        }

    def representative_evidence(
        self,
        user_id: str,
        project_ids: Sequence[str],
        query: Any,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return owner-scoped evidence after an aggregate has been computed.

        Args:
            user_id: Authenticated owner whose projects are in scope.
            project_ids: Optional project UUIDs to narrow the owner scope.
            query: Aggregate query carrying the same metadata filters.
            limit: Maximum number of representative records.

        Returns:
            Evidence-shaped rows ordered by deterministic community signal.
        """
        filters = getattr(query, "filters", QueryFilters())
        where, params = _analytics_scope(user_id, project_ids, filters)
        params["representative_limit"] = max(1, min(100, int(limit)))
        occurred_at_sql = _OCCURRED_AT_SQL
        result = self._conn.execute(
            text(
                f"""
                SELECT r.id::text AS id,
                       r.id::text AS record_id,
                       r.repository,
                       r.source_type,
                       r.title,
                       LEFT(r.body, 500) AS excerpt,
                       r.source_url,
                       {occurred_at_sql} AS occurred_at
                FROM intelligence_records AS r
                JOIN intelligence_projects AS p ON p.id = r.project_id
                WHERE {' AND '.join(where)}
                ORDER BY r.comments_count DESC,
                         r.reactions_count DESC,
                         {occurred_at_sql} DESC NULLS LAST,
                         r.id::text ASC
                LIMIT :representative_limit
                """
            ),
            params,
        )
        return [
            {
                key: value
                for key, value in row_to_dict(row).items()
                if key != "_id"
            }
            for row in result.fetchall()
        ]

    def _aggregate_coverage(
        self,
        user_id: str,
        project_ids: Sequence[str],
        filters: QueryFilters,
    ) -> dict[str, Any]:
        """Compute coverage counts from the same owner-scoped SQL predicate."""
        where, params = _analytics_scope(user_id, project_ids, filters)
        result = self._conn.execute(
            text(
                f"""
                SELECT array_agg(DISTINCT r.repository ORDER BY r.repository) AS repositories,
                       MIN({_OCCURRED_AT_SQL})::date AS date_from,
                       MAX({_OCCURRED_AT_SQL})::date AS date_to,
                       COUNT(*) FILTER (WHERE r.source_type = 'documentation') AS documentation_count,
                       COUNT(*) FILTER (WHERE r.source_type = 'issue') AS issue_count,
                       COUNT(*) FILTER (WHERE r.source_type = 'issue_comment') AS issue_comment_count,
                       COUNT(*) FILTER (WHERE r.source_type = 'release') AS release_count
                FROM intelligence_records AS r
                JOIN intelligence_projects AS p ON p.id = r.project_id
                WHERE {' AND '.join(where)}
                """
            ),
            params,
        )
        row = result.fetchone()
        mapping = row._mapping if row is not None else {}
        return {
            "repositories": list(mapping.get("repositories") or []),
            "date_from": mapping.get("date_from"),
            "date_to": mapping.get("date_to"),
            "counts": {
                "documentation": int(mapping.get("documentation_count") or 0),
                "issue": int(mapping.get("issue_count") or 0),
                "issue_comment": int(mapping.get("issue_comment_count") or 0),
                "release": int(mapping.get("release_count") or 0),
            },
        }

    def upsert_record(self, project_id: str, record: IntelligenceRecord) -> UpsertOutcome:
        """Insert or update a normalized record using its stable content hash.

        Args:
            project_id: UUID of the owning intelligence project.
            record: Normalized GitHub evidence record.

        Returns:
            The database record id and whether its stored content changed.
        """
        params = record.to_repository_params(project_id)
        params["source_type"] = record.source_type.value
        params["labels"] = json.dumps(record.labels, ensure_ascii=False)
        result = self._conn.execute(
            text(
                """
                WITH changed AS (
                    INSERT INTO intelligence_records
                        (project_id, repository, source_type, external_id, title, body,
                         source_url, state, labels, comments_count, reactions_count, version,
                         created_at, updated_at, published_at, retrieved_at, content_hash, metadata)
                    VALUES
                        (CAST(:project_id AS uuid), :repository, :source_type, :external_id,
                         :title, :body, :source_url, :state, CAST(:labels AS jsonb),
                         :comments_count, :reactions_count, :version, :created_at, :updated_at,
                         :published_at, :retrieved_at, :content_hash, CAST(:metadata AS jsonb))
                    ON CONFLICT (project_id, source_type, external_id) DO UPDATE SET
                        repository = EXCLUDED.repository,
                        title = EXCLUDED.title,
                        body = EXCLUDED.body,
                        source_url = EXCLUDED.source_url,
                        state = EXCLUDED.state,
                        labels = EXCLUDED.labels,
                        comments_count = EXCLUDED.comments_count,
                        reactions_count = EXCLUDED.reactions_count,
                        version = EXCLUDED.version,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at,
                        published_at = EXCLUDED.published_at,
                        retrieved_at = EXCLUDED.retrieved_at,
                        content_hash = EXCLUDED.content_hash,
                        metadata = EXCLUDED.metadata
                    WHERE intelligence_records.content_hash <> EXCLUDED.content_hash
                    RETURNING id
                )
                SELECT id, true AS changed FROM changed
                UNION ALL
                SELECT id, false AS changed
                FROM intelligence_records
                WHERE project_id = CAST(:project_id AS uuid)
                  AND source_type = :source_type
                  AND external_id = :external_id
                ORDER BY changed DESC
                LIMIT 1
                """
            ),
            params,
        )
        row = result.mappings().one()
        return UpsertOutcome(record_id=str(row["id"]), changed=bool(row["changed"]))

    def start_sync_run(self, project_id: str) -> dict[str, Any]:
        """Create a running synchronization record for a project.

        Args:
            project_id: UUID of the intelligence project.

        Returns:
            The inserted synchronization run row.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO intelligence_sync_runs (project_id, status, started_at)
                VALUES (CAST(:project_id AS uuid), 'running', now())
                RETURNING *
                """
            ),
            {"project_id": project_id},
        )
        return row_to_dict(result.fetchone())

    def finish_sync_run(self, run_id: str, summary: SyncSummary) -> dict[str, Any]:
        """Persist a synchronization summary and mark the run terminal.

        Args:
            run_id: UUID of the synchronization run.
            summary: Completed, partial, or failed synchronization summary.

        Returns:
            The updated synchronization run row.
        """
        data = summary.model_dump(mode="json")
        result = self._conn.execute(
            text(
                """
                UPDATE intelligence_sync_runs
                SET status = :status,
                    counts = CAST(:counts AS jsonb),
                    failures = CAST(:failures AS jsonb),
                    coverage = CAST(:coverage AS jsonb),
                    finished_at = now()
                WHERE id = CAST(:run_id AS uuid)
                RETURNING *
                """
            ),
            {
                "run_id": run_id,
                "status": summary.status,
                "counts": json.dumps(data["counts"], ensure_ascii=False),
                "failures": json.dumps(data["failures"], ensure_ascii=False),
                "coverage": json.dumps(data["coverage"], ensure_ascii=False),
            },
        )
        return row_to_dict(result.fetchone())

    def save_report(self, user_id: str, report_data: dict[str, Any]) -> dict[str, Any]:
        """Save a structured report owned by ``user_id``.

        Args:
            user_id: Authenticated report owner identifier.
            report_data: JSON-serializable report document.

        Returns:
            The inserted report row.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO intelligence_reports (user_id, report_data)
                VALUES (:user_id, CAST(:report_data AS jsonb))
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "report_data": json.dumps(report_data, ensure_ascii=False),
            },
        )
        return row_to_dict(result.fetchone())


def _analytics_scope(
    user_id: str,
    project_ids: Sequence[str],
    filters: QueryFilters,
) -> tuple[list[str], dict[str, Any]]:
    """Build a parameterized owner and metadata scope for analytics SQL."""
    where = ["p.user_id = :user_id"]
    params: dict[str, Any] = {"user_id": user_id}

    project_parameters: list[str] = []
    for index, project_id in enumerate(project_ids or []):
        try:
            normalized_project_id = str(UUID(str(project_id)))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("project_ids must contain UUIDs") from exc
        parameter = f"project_id_{index}"
        params[parameter] = normalized_project_id
        project_parameters.append(f"CAST(:{parameter} AS uuid)")
    if project_parameters:
        where.append(f"p.id IN ({', '.join(project_parameters)})")

    repositories = list(filters.repositories or [])
    if repositories:
        placeholders = _bind_values(repositories, "repository", params)
        where.append(f"r.repository IN ({placeholders})")

    source_types = [
        getattr(source_type, "value", str(source_type))
        for source_type in (filters.source_types or [])
    ]
    if source_types:
        placeholders = _bind_values(source_types, "source_type", params)
        where.append(f"r.source_type IN ({placeholders})")

    if filters.date_from is not None:
        params["date_from"] = filters.date_from
        where.append(f"{_OCCURRED_AT_SQL}::date >= :date_from")
    if filters.date_to is not None:
        params["date_to"] = filters.date_to
        where.append(f"{_OCCURRED_AT_SQL}::date <= :date_to")
    return where, params


def _bind_values(
    values: Sequence[Any],
    prefix: str,
    params: dict[str, Any],
) -> str:
    """Bind a list without interpolating user values into SQL text."""
    placeholders: list[str] = []
    for index, value in enumerate(values):
        parameter = f"{prefix}_{index}"
        params[parameter] = value
        placeholders.append(f":{parameter}")
    return ", ".join(placeholders)
