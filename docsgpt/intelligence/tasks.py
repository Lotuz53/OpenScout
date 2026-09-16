"""Celery tasks for OpenScout intelligence synchronization."""

from __future__ import annotations

from typing import Any

from docsgpt.api.user.idempotency import with_idempotency
from docsgpt.celery_init import celery
from docsgpt.intelligence.github_client import GitHubClient
from docsgpt.intelligence.sync_service import RecoverableGitHubError, SyncService
from docsgpt.storage.db.session import db_readonly, db_session


def build_sync_service() -> SyncService:
    """Build the production synchronization service for a Celery worker."""
    return SyncService(
        repository=None,
        github=GitHubClient(),
        indexer=None,
        session_factory=db_session,
        readonly_factory=db_readonly,
    )


@celery.task(bind=True, acks_late=True)
def extract_intelligence_graph(
    self: Any,
    source_id: str,
    user_id: str | None,
    chunks: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, int]:
    """Extract a selected intelligence graph in a separate worker task."""
    from docsgpt.graphrag.extraction import extract_graph_for_source
    from docsgpt.storage.db.source_config import SourceConfig

    source_config = SourceConfig.parse(config)
    return extract_graph_for_source(
        str(source_id),
        user_id,
        chunks,
        config=source_config,
        request_id=request_id or getattr(self.request, "id", None),
    )


@celery.task(
    bind=True,
    acks_late=True,
    autoretry_for=RecoverableGitHubError,
    retry_backoff=True,
    retry_kwargs={"max_retries": 4},
)
@with_idempotency(task_name="sync_intelligence_project")
def sync_intelligence_project(
    self: Any,
    *,
    project_id: str,
    user_id: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Synchronize a project and return a JSON-serializable summary."""
    del self
    summary = build_sync_service().run(project_id, user_id)
    return summary.model_dump(mode="json")


__all__ = [
    "build_sync_service",
    "extract_intelligence_graph",
    "sync_intelligence_project",
]
