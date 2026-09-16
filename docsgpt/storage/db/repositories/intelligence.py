"""Persistence for OpenScout intelligence projects and evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from docsgpt.intelligence.schemas import IntelligenceRecord, SyncSummary
from docsgpt.storage.db.base_repository import row_to_dict


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
