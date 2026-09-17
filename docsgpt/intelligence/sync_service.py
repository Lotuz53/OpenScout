"""Orchestrate bounded GitHub synchronization for an intelligence project."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from requests import RequestException
from sqlalchemy import text

from docsgpt.intelligence.github_client import GitHubClient, GitHubRateLimitError
from docsgpt.intelligence.graph_selection import select_graph_records
from docsgpt.intelligence.normalizer import (
    normalize_comment,
    normalize_document,
    normalize_issue,
    normalize_release,
)
from docsgpt.intelligence.schemas import (
    Coverage,
    IntelligenceRecord,
    SourceType,
    SyncFailure,
    SyncSummary,
)
from docsgpt.storage.db.repositories.intelligence import IntelligenceRepository


UTC = timezone.utc
ISSUE_LIMIT = 1000
COMMENT_LIMIT = 20

# A tuple is intentional: it can be used both by ``except`` and Celery's
# ``autoretry_for`` without changing the existing GitHub client exception.
RecoverableGitHubError = (GitHubRateLimitError, RequestException)
SessionFactory = Callable[[], AbstractContextManager[Any]]
GRAPH_ISSUE_LIMIT = 300
logger = logging.getLogger(__name__)


class SyncCursor(BaseModel):
    """High-water marks returned by a successful incremental sync."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    last_success_at: datetime
    external_updated_at: datetime | None = None


class IncrementalSyncSummary(SyncSummary):
    """Synchronization summary with incremental and deletion audit counts."""

    cursor: SyncCursor | None = None
    changed_records: int = 0
    unchanged_records: int = 0
    embedded_chunks: int = 0
    deactivated_record_ids: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class PersistBatchSummary:
    """Describe persistence and indexing outcomes for one source batch."""

    changed_records: int = 0
    unchanged_records: int = 0
    embedded_chunks: int = 0
    seen_record_ids: tuple[str, ...] = ()


class SyncService:
    """Synchronize GitHub evidence while isolating failures by source type.

    Collection and normalization errors are recorded against their source and
    do not roll back successful source batches. Persistence and indexing errors
    are allowed to escape because they indicate a failed local transaction,
    rather than a recoverable GitHub source problem.
    """

    def __init__(
        self,
        repository: IntelligenceRepository | Any | None,
        github: GitHubClient,
        indexer: Any | None,
        *,
        session_factory: SessionFactory | None = None,
        readonly_factory: SessionFactory | None = None,
        now_factory: Callable[[], datetime] | None = None,
        graph_extractor: Any | None = None,
        graph_enabled: bool | None = None,
    ) -> None:
        """Initialize a synchronization service.

        Args:
            repository: Repository-like test double or a repository used when
                no session factory is supplied. Production callers may pass
                ``None`` and let the service create one per source transaction.
            github: Bounded GitHub API client.
            indexer: Record indexer. Production callers may pass ``None`` to
                create the configured vector indexer lazily on the first
                changed source batch.
            session_factory: Optional write transaction factory yielding a
                SQLAlchemy connection.
            readonly_factory: Optional read-only transaction factory for the
                owner-scoped project lookup.
            now_factory: Clock injection for deterministic tests.
            graph_extractor: Optional asynchronous extraction task. When
                omitted, the production Celery task is resolved lazily.
            graph_enabled: Optional GraphRAG kill-switch. ``False`` disables
                enqueueing; an injected extractor is enabled by default.
        """
        self.repository = repository
        self.github = github
        self.indexer = indexer
        self.session_factory = session_factory
        self.readonly_factory = readonly_factory
        self.now_factory = now_factory or (lambda: datetime.now(tz=UTC))
        self.graph_extractor = graph_extractor
        self.graph_enabled = graph_enabled

    def run(self, project_id: str, user_id: str) -> IncrementalSyncSummary:
        """Run the current incremental synchronization implementation.

        ``run`` remains the task-facing entry point while the explicit method
        makes the incremental behavior directly testable.
        """
        return self.run_incremental(project_id, user_id)

    def run_incremental(self, project_id: str, user_id: str) -> IncrementalSyncSummary:
        """Synchronize one owner-scoped project from its last successful cursor.

        Args:
            project_id: UUID of the intelligence project.
            user_id: Authenticated project owner.

        Returns:
            A complete, partial, or failed synchronization summary.

        Raises:
            LookupError: If the project does not exist for ``user_id``.
            Exception: Local persistence or indexing failures are propagated.
        """
        project = self._get_project(project_id, user_id)
        if project is None:
            raise LookupError("Intelligence project was not found")

        repository_name = str(_field(project, "repository"))
        window_start = _as_date(_field(project, "window_start"))
        window_end = _as_date(_field(project, "window_end"))
        if window_start > window_end:
            raise ValueError("Intelligence project window_start must not exceed window_end")

        retrieved_at = _as_utc_datetime(self.now_factory())
        previous_sync = _optional_field(project, "last_synced_at")
        since = (
            _as_utc_datetime(previous_sync)
            if previous_sync is not None
            else datetime.combine(window_start, time.min, tzinfo=UTC)
        )
        until = datetime.combine(window_end, time.max, tzinfo=UTC)
        counts = {source_type: 0 for source_type in SourceType}
        failures: list[SyncFailure] = []
        observed_dates: list[date] = []
        successful_sources: set[SourceType] = set()
        completed_batches: dict[SourceType, list[IntelligenceRecord]] = {}
        changed_records = 0
        unchanged_records = 0
        embedded_chunks = 0
        capped = False

        run_id = self._start_sync_run(project_id)
        sync_id = run_id or str(uuid4())
        try:
            self._set_project_status(project_id, user_id, "syncing")

            document_collector = getattr(self.github, "iter_documents", None)
            if callable(document_collector):
                document_ok, document_records, document_capped, document_summary = self._run_source(
                    project_id=project_id,
                    source_type=SourceType.DOCUMENTATION,
                    user_id=user_id,
                    producer=lambda: (
                        [
                            _normalize_document_item(
                                repository_name,
                                item,
                                retrieved_at,
                            )
                            for item in document_collector(repository_name, since, until)
                        ],
                        False,
                    ),
                    counts=counts,
                    failures=failures,
                    observed_dates=observed_dates,
                    sync_id=sync_id,
                )
                if document_ok:
                    successful_sources.add(SourceType.DOCUMENTATION)
                    completed_batches[SourceType.DOCUMENTATION] = document_records
                    changed_records += document_summary.changed_records
                    unchanged_records += document_summary.unchanged_records
                    embedded_chunks += document_summary.embedded_chunks
                capped = capped or document_capped

            release_ok, release_records, release_capped, release_summary = self._run_source(
                project_id=project_id,
                source_type=SourceType.RELEASE,
                user_id=user_id,
                producer=lambda: (
                    [
                        normalize_release(repository_name, raw, retrieved_at)
                        for raw in self.github.iter_releases(repository_name, since, until)
                    ],
                    False,
                ),
                counts=counts,
                failures=failures,
                observed_dates=observed_dates,
                sync_id=sync_id,
            )
            if release_ok:
                successful_sources.add(SourceType.RELEASE)
                completed_batches[SourceType.RELEASE] = release_records
                changed_records += release_summary.changed_records
                unchanged_records += release_summary.unchanged_records
                embedded_chunks += release_summary.embedded_chunks
            capped = capped or release_capped

            issue_raws: list[Mapping[str, Any]] | None = None

            def collect_issues() -> tuple[list[IntelligenceRecord], bool]:
                nonlocal issue_raws
                issue_raws = list(self.github.iter_issues(repository_name, since, until))
                return (
                    [
                        normalize_issue(repository_name, raw, retrieved_at)
                        for raw in issue_raws
                    ],
                    len(issue_raws) >= ISSUE_LIMIT,
                )

            issue_ok, issue_records, issue_capped, issue_summary = self._run_source(
                project_id=project_id,
                source_type=SourceType.ISSUE,
                user_id=user_id,
                producer=collect_issues,
                counts=counts,
                failures=failures,
                observed_dates=observed_dates,
                sync_id=sync_id,
            )
            if issue_ok:
                successful_sources.add(SourceType.ISSUE)
                completed_batches[SourceType.ISSUE] = issue_records
                changed_records += issue_summary.changed_records
                unchanged_records += issue_summary.unchanged_records
                embedded_chunks += issue_summary.embedded_chunks
            capped = capped or issue_capped

            if issue_ok and issue_raws is not None:
                comment_ok, comment_records, comment_capped, comment_summary = self._run_source(
                    project_id=project_id,
                    source_type=SourceType.ISSUE_COMMENT,
                    user_id=user_id,
                    producer=lambda: self._collect_comments(
                        repository_name,
                        issue_raws,
                        retrieved_at,
                    ),
                    counts=counts,
                    failures=failures,
                    observed_dates=observed_dates,
                    sync_id=sync_id,
                )
                if comment_ok:
                    successful_sources.add(SourceType.ISSUE_COMMENT)
                    completed_batches[SourceType.ISSUE_COMMENT] = comment_records
                    changed_records += comment_summary.changed_records
                    unchanged_records += comment_summary.unchanged_records
                    embedded_chunks += comment_summary.embedded_chunks
                capped = capped or comment_capped

            deactivated_record_ids: list[str] = []
            if not failures and not capped:
                deactivated_record_ids = self._reconcile_missing(
                    project_id,
                    completed_batches,
                )

            status = _summary_status(successful_sources, failures)
            last_synced_at = retrieved_at if not failures else None
            cursor = (
                SyncCursor(
                    last_success_at=retrieved_at,
                    external_updated_at=_latest_external_update(completed_batches.values()),
                )
                if not failures
                else None
            )
            coverage = Coverage(
                repositories=[repository_name],
                date_from=min(observed_dates) if observed_dates else window_start,
                date_to=max(observed_dates) if observed_dates else window_end,
                counts=counts,
                capped=capped,
                last_synced_at=last_synced_at,
            )
            summary = IncrementalSyncSummary(
                status=status,
                counts=counts,
                failures=failures,
                coverage=coverage,
                cursor=cursor,
                changed_records=changed_records,
                unchanged_records=unchanged_records,
                embedded_chunks=embedded_chunks,
                deactivated_record_ids=deactivated_record_ids,
            )

            if run_id is not None:
                self._finish_sync_run(run_id, summary)
            self._set_project_status(
                project_id,
                user_id,
                "ready" if status == "complete" else status,
                last_synced_at=last_synced_at,
                external_updated_at=cursor.external_updated_at if cursor else None,
            )
            return summary
        except Exception as exc:
            failure = SyncFailure(
                source_type="sync",
                category="local",
                retryable=False,
                message=str(exc),
            )
            failed_summary = self._build_local_failure_summary(
                repository_name=repository_name,
                window_start=window_start,
                window_end=window_end,
                retrieved_at=retrieved_at,
                counts=counts,
                failures=[*failures, failure],
                observed_dates=observed_dates,
                capped=capped,
                changed_records=changed_records,
                unchanged_records=unchanged_records,
                embedded_chunks=embedded_chunks,
            )
            if run_id is not None:
                try:
                    self._finish_sync_run(run_id, failed_summary)
                except Exception:
                    logger.exception("Could not mark sync run %s as failed", run_id)
            try:
                self._set_project_status(project_id, user_id, "failed")
            except Exception:
                logger.exception(
                    "Could not mark intelligence project %s as failed",
                    project_id,
                )
            raise

    def _run_source(
        self,
        *,
        project_id: str,
        source_type: SourceType,
        user_id: str,
        producer: Callable[[], tuple[list[IntelligenceRecord], bool]],
        counts: dict[SourceType, int],
        failures: list[SyncFailure],
        observed_dates: list[date],
        sync_id: str,
    ) -> tuple[bool, list[IntelligenceRecord], bool, PersistBatchSummary]:
        """Collect, normalize and persist one source batch."""
        try:
            records, capped = producer()
        except Exception as exc:
            failures.append(_to_sync_failure(source_type, exc))
            return False, [], False, PersistBatchSummary()

        # One call opens one transaction for the entire source batch. A
        # failure here is a local consistency failure and must not be recast as
        # a successful GitHub partial result.
        batch_summary = self._persist_batch(
            project_id,
            records,
            user_id=user_id,
            sync_id=sync_id,
        )
        counts[source_type] = len(records)
        observed_dates.extend(
            record_date
            for record in records
            for record_date in _record_dates(record)
        )
        return True, records, capped, batch_summary

    def _collect_comments(
        self,
        repository_name: str,
        issue_raws: Sequence[Mapping[str, Any]],
        retrieved_at: datetime,
    ) -> tuple[list[IntelligenceRecord], bool]:
        """Collect and normalize bounded comments for the issue batch."""
        records: list[IntelligenceRecord] = []
        capped = False
        for issue in issue_raws:
            issue_number = issue.get("number")
            if issue_number is None:
                raise ValueError("Issue payload is missing number")
            raw_comments = list(
                self.github.iter_comments(
                    repository_name,
                    int(issue_number),
                    limit=COMMENT_LIMIT,
                )
            )
            capped = capped or len(raw_comments) >= COMMENT_LIMIT
            records.extend(
                normalize_comment(
                    repository_name,
                    int(issue_number),
                    raw,
                    retrieved_at,
                )
                for raw in raw_comments
            )
        return records, capped

    def _persist_batch(
        self,
        project_id: str,
        records: Sequence[IntelligenceRecord],
        *,
        user_id: str | None = None,
        sync_id: str | None = None,
    ) -> PersistBatchSummary:
        """Upsert and index a source batch inside one write transaction."""
        if not records:
            return PersistBatchSummary()
        with self._repository_context() as repository:
            upsert_many = getattr(repository, "upsert_records", None)
            if callable(upsert_many):
                if sync_id is None:
                    result = upsert_many(project_id, records)
                else:
                    try:
                        result = upsert_many(project_id, records, sync_id=sync_id)
                    except TypeError:
                        result = upsert_many(project_id, records)
                changed_records = _changed_records(records, result)
                changed_count = _changed_count(records, result, changed_records)
                unchanged_count = max(0, len(records) - changed_count)
                seen_record_ids = _outcome_record_ids(records, result)
            else:
                changed_records = []
                changed_count = 0
                unchanged_count = 0
                seen_record_ids = []
                for record in records:
                    try:
                        outcome = repository.upsert_record(
                            project_id,
                            record,
                            sync_id=sync_id,
                        )
                    except TypeError:
                        outcome = repository.upsert_record(project_id, record)
                    record_id = _outcome_record_id(outcome)
                    if record_id is not None:
                        seen_record_ids.append(record_id)
                    if _outcome_changed(outcome):
                        changed_records.append(_record_with_outcome_id(record, outcome))
                        changed_count += 1
                    else:
                        unchanged_count += 1

            marker = getattr(repository, "mark_seen", None)
            if callable(marker) and sync_id is not None:
                for record_id in seen_record_ids:
                    marker(record_id, sync_id)

            index_summary: Any | None = None
            if changed_records:
                indexer = self._get_indexer(project_id, repository)
                if indexer is not None:
                    index_summary = indexer.replace_records(project_id, changed_records)
                    self._enqueue_graph_extraction(
                        project_id,
                        user_id,
                        changed_records,
                        index_summary,
                    )

            return PersistBatchSummary(
                changed_records=changed_count,
                unchanged_records=unchanged_count,
                embedded_chunks=_embedded_chunk_count(index_summary),
                seen_record_ids=tuple(seen_record_ids),
            )

    def _reconcile_missing(
        self,
        project_id: str,
        completed_batches: Mapping[SourceType, Sequence[IntelligenceRecord]],
    ) -> list[str]:
        """Confirm complete-source omissions and remove only deactivated chunks."""
        with self._repository_context() as repository:
            recorder = getattr(repository, "record_missing", None)
            deactivator = getattr(repository, "deactivate_confirmed_missing", None)
            if not callable(recorder) or not callable(deactivator):
                return []

            for source_type, records in completed_batches.items():
                recorder(
                    project_id,
                    source_type,
                    {record.external_id for record in records},
                )

            deactivated_ids = [
                str(record_id)
                for record_id in (deactivator(project_id) or [])
            ]
            if deactivated_ids:
                indexer = self._get_indexer(project_id, repository)
                deleter = getattr(indexer, "delete_records", None)
                if callable(deleter):
                    deleter(project_id, deactivated_ids)
                else:
                    logger.warning(
                        "Indexer cannot delete deactivated records for project %s",
                        project_id,
                    )
            return deactivated_ids

    def _enqueue_graph_extraction(
        self,
        project_id: str,
        user_id: str | None,
        records: Sequence[IntelligenceRecord],
        index_summary: Any,
    ) -> None:
        """Queue selected indexed chunks for asynchronous GraphRAG extraction.

        Graph extraction is deliberately best-effort. A broker or graph
        configuration failure must not turn a successfully committed GitHub
        batch into a failed synchronization result.
        """
        if not records or not self._graph_is_enabled():
            return
        chunks = self._graph_chunks(project_id, records, index_summary)
        if not chunks:
            return

        try:
            extractor = self.graph_extractor or self._default_graph_extractor()
            config = self._graph_config()
            delay = getattr(extractor, "delay", None)
            if callable(delay):
                delay(
                    project_id,
                    user_id,
                    chunks,
                    config=config.model_dump(mode="json"),
                    request_id=None,
                )
                return
            apply_async = getattr(extractor, "apply_async", None)
            if callable(apply_async):
                apply_async(
                    args=(project_id, user_id, chunks),
                    kwargs={
                        "config": config.model_dump(mode="json"),
                        "request_id": None,
                    },
                )
                return
            logger.warning("GraphRAG extractor has no asynchronous enqueue method")
        except Exception:
            logger.warning(
                "Could not enqueue GraphRAG extraction for project %s",
                project_id,
                exc_info=True,
            )

    def _graph_is_enabled(self) -> bool:
        """Resolve the GraphRAG gate without importing it on every sync."""
        if self.graph_enabled is not None:
            return self.graph_enabled
        if self.graph_extractor is not None:
            return True
        try:
            from docsgpt.graphrag import graphrag_available

            return bool(graphrag_available())
        except Exception:
            logger.debug("GraphRAG availability check failed", exc_info=True)
            return False

    def _default_graph_extractor(self) -> Any:
        """Resolve the intelligence-specific Celery extraction task lazily."""
        from docsgpt.intelligence.tasks import extract_intelligence_graph

        return extract_intelligence_graph

    @staticmethod
    def _graph_config() -> Any:
        """Build the default graph extraction configuration for intelligence data."""
        from docsgpt.storage.db.source_config import SourceConfig

        return SourceConfig(kind="graphrag")

    @staticmethod
    def _graph_chunks(
        project_id: str,
        records: Sequence[IntelligenceRecord],
        index_summary: Any,
    ) -> list[dict[str, Any]]:
        """Attach returned vector ids to chunks from the selected records."""
        del project_id
        chunk_ids = getattr(index_summary, "chunk_ids", None)
        if not isinstance(chunk_ids, list) or not chunk_ids:
            return []

        from docsgpt.intelligence.indexing import chunks_for_record

        selected = select_graph_records(records, issue_limit=GRAPH_ISSUE_LIMIT)
        selected_ids = {
            record.id or f"{record.source_type.value}:{record.external_id}"
            for record in selected
        }
        chunks: list[dict[str, Any]] = []
        id_offset = 0
        for record in records:
            record_chunks = chunks_for_record(record)
            record_ids = chunk_ids[id_offset : id_offset + len(record_chunks)]
            id_offset += len(record_chunks)
            record_id = record.id or f"{record.source_type.value}:{record.external_id}"
            if record_id not in selected_ids:
                continue
            chunks.extend(
                {
                    "doc_id": str(chunk_id),
                    "text": chunk.page_content,
                    "metadata": chunk.metadata,
                }
                for chunk, chunk_id in zip(record_chunks, record_ids)
            )
        return chunks

    def _get_indexer(self, project_id: str, repository: Any) -> Any | None:
        """Return the injected indexer or build the production one lazily."""
        if self.indexer is not None:
            return self.indexer
        if self.session_factory is None or self.repository is not None:
            return None

        from docsgpt.core.settings import settings
        from docsgpt.intelligence.indexing import IntelligenceIndexer
        from docsgpt.vectorstore.vector_creator import VectorCreator

        vector_store_kwargs: dict[str, Any] = {
            "source_id": project_id,
            "embeddings_key": settings.EMBEDDINGS_KEY,
        }
        if str(settings.VECTOR_STORE).lower() == "faiss":
            vector_store_kwargs["create_if_missing"] = True

        vector_store = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE,
            **vector_store_kwargs,
        )
        self.indexer = IntelligenceIndexer(repository, vector_store)
        return self.indexer

    def _get_project(self, project_id: str, user_id: str) -> Any:
        """Read an owner-scoped project through the configured repository."""
        with self._readonly_repository_context() as repository:
            return repository.get_project(project_id, user_id)

    def _start_sync_run(self, project_id: str) -> str | None:
        """Create a running sync row when the repository supports it."""
        with self._repository_context() as repository:
            starter = getattr(repository, "start_sync_run", None)
            if not callable(starter):
                return None
            try:
                row = starter(project_id)
            except TypeError:
                row = starter()
            return _row_id(row)

    def _finish_sync_run(self, run_id: str, summary: SyncSummary) -> None:
        """Persist the terminal state of a sync run."""
        with self._repository_context() as repository:
            finisher = getattr(repository, "finish_sync_run", None)
            if callable(finisher):
                finisher(run_id, summary)

    def _set_project_status(
        self,
        project_id: str,
        user_id: str,
        status: str,
        *,
        last_synced_at: datetime | None = None,
        external_updated_at: datetime | None = None,
    ) -> None:
        """Persist the project lifecycle state when supported."""
        with self._repository_context() as repository:
            updater = getattr(repository, "set_project_status", None)
            if callable(updater):
                try:
                    updater(
                        project_id,
                        user_id,
                        status,
                        last_synced_at,
                        external_updated_at,
                    )
                except TypeError:
                    try:
                        updater(project_id, user_id, status, last_synced_at)
                    except TypeError:
                        updater(project_id, status, last_synced_at)
                return

            if isinstance(repository, IntelligenceRepository):
                repository._conn.execute(
                    text(
                        """
                        UPDATE intelligence_projects
                        SET status = :status,
                            last_synced_at = COALESCE(:last_synced_at, last_synced_at),
                            external_updated_at = COALESCE(
                                :external_updated_at,
                                external_updated_at
                            )
                        WHERE id = CAST(:project_id AS uuid)
                          AND user_id = :user_id
                        """
                    ),
                    {
                        "project_id": project_id,
                        "user_id": user_id,
                        "status": status,
                        "last_synced_at": last_synced_at,
                        "external_updated_at": external_updated_at,
                    },
                )

    def _build_local_failure_summary(
        self,
        *,
        repository_name: str,
        window_start: date,
        window_end: date,
        retrieved_at: datetime,
        counts: dict[SourceType, int],
        failures: list[SyncFailure],
        observed_dates: list[date],
        capped: bool,
        changed_records: int,
        unchanged_records: int,
        embedded_chunks: int,
    ) -> IncrementalSyncSummary:
        """Build a terminal summary for a local synchronization failure."""
        del retrieved_at
        coverage = Coverage(
            repositories=[repository_name],
            date_from=min(observed_dates) if observed_dates else window_start,
            date_to=max(observed_dates) if observed_dates else window_end,
            counts=counts,
            capped=capped,
            last_synced_at=None,
        )
        return IncrementalSyncSummary(
            status="failed",
            counts=counts,
            failures=failures,
            coverage=coverage,
            cursor=None,
            changed_records=changed_records,
            unchanged_records=unchanged_records,
            embedded_chunks=embedded_chunks,
            deactivated_record_ids=[],
        )

    @contextmanager
    def _repository_context(self) -> Any:
        """Yield the injected repository or a repository bound to one tx."""
        if self.session_factory is None:
            if self.repository is None:
                raise RuntimeError("A repository or session_factory is required")
            yield self.repository
            return

        with self.session_factory() as connection:
            if isinstance(connection, IntelligenceRepository):
                yield connection
            else:
                yield IntelligenceRepository(connection)

    @contextmanager
    def _readonly_repository_context(self) -> Any:
        """Yield a repository for the owner-scoped project lookup."""
        if self.session_factory is None and self.readonly_factory is None:
            if self.repository is None:
                raise RuntimeError("A repository or session_factory is required")
            yield self.repository
            return

        factory = self.readonly_factory or self.session_factory
        if factory is None:
            raise RuntimeError("A repository or session factory is required")
        with factory() as connection:
            if isinstance(connection, IntelligenceRepository):
                yield connection
            else:
                yield IntelligenceRepository(connection)


def _field(value: Any, name: str) -> Any:
    """Read a field from a mapping or an object with attributes."""
    if isinstance(value, Mapping):
        return value[name]
    return getattr(value, name)


def _optional_field(value: Any, name: str) -> Any | None:
    """Read an optional field from a mapping or an object with attributes."""
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _as_date(value: Any) -> date:
    """Normalize a project date value."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid project date: {value!r}") from exc


def _as_utc_datetime(value: Any) -> datetime:
    """Normalize a timestamp to an aware UTC datetime."""
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid synchronization timestamp: {value!r}") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_document_item(
    repository_name: str,
    item: Any,
    retrieved_at: datetime,
) -> IntelligenceRecord:
    """Adapt an optional document collector item to the normalizer contract."""
    if isinstance(item, IntelligenceRecord):
        return item

    metadata: Mapping[str, Any] = {}
    if isinstance(item, Mapping):
        path = item.get("path") or item.get("doc_id")
        body = item.get("body") or item.get("text") or ""
        source_url = item.get("source_url") or item.get("url")
    else:
        metadata_value = getattr(item, "extra_info", {})
        metadata = metadata_value if isinstance(metadata_value, Mapping) else {}
        path = getattr(item, "path", None) or getattr(item, "doc_id", None)
        body = getattr(item, "body", None) or getattr(item, "text", None) or ""
        source_url = getattr(item, "source_url", None) or getattr(item, "url", None)

    if not path:
        raise ValueError("Document payload is missing path")
    source_url = source_url or metadata.get("source") or metadata.get("source_url")
    if not source_url:
        source_url = f"https://github.com/{repository_name}/blob/main/{path}"
    return normalize_document(
        repository_name,
        str(path),
        str(body),
        str(source_url),
        retrieved_at,
    )


def _record_dates(record: IntelligenceRecord) -> list[date]:
    """Return all source dates available for coverage calculation."""
    return [
        timestamp.date()
        for timestamp in (
            record.created_at,
            record.updated_at,
            record.published_at,
        )
        if timestamp is not None
    ]


def _summary_status(successful_sources: set[SourceType], failures: Sequence[SyncFailure]) -> str:
    """Calculate the terminal status from source-level outcomes."""
    if failures and successful_sources:
        return "partial"
    if failures:
        return "failed"
    return "complete"


def _to_sync_failure(source_type: SourceType, error: Exception) -> SyncFailure:
    """Map a source collection error to the stable failure contract."""
    category = "network"
    retryable = True
    if isinstance(error, GitHubRateLimitError):
        category = "rate_limit"
    elif isinstance(error, RequestException):
        status_code = getattr(getattr(error, "response", None), "status_code", None)
        if status_code in {401, 403}:
            category = "auth"
        elif status_code == 404:
            category = "not_found"
            retryable = False
    elif isinstance(error, (KeyError, TypeError, ValueError)):
        category = "invalid_payload"
        retryable = False
    else:
        message = str(error).lower()
        if "not found" in message or "404" in message:
            category = "not_found"
            retryable = False
        elif "auth" in message or "token" in message or "permission" in message:
            category = "auth"

    return SyncFailure(
        source_type=source_type,
        category=category,
        retryable=retryable,
        message=str(error),
    )


def _row_id(row: Any) -> str | None:
    """Extract a sync-run identifier from a repository result."""
    if row is None:
        return None
    value = row.get("id") if isinstance(row, Mapping) else getattr(row, "id", row)
    return str(value) if value is not None else None


def _outcome_changed(outcome: Any) -> bool:
    """Interpret repository upsert outcomes conservatively."""
    if isinstance(outcome, bool):
        return outcome
    if isinstance(outcome, Mapping):
        return bool(outcome.get("changed", True))
    if outcome is None:
        return True
    return bool(getattr(outcome, "changed", True))


def _outcome_record_id(outcome: Any) -> str | None:
    """Extract a persisted record id from an upsert outcome."""
    if isinstance(outcome, Mapping):
        record_id = outcome.get("record_id") or outcome.get("id")
    else:
        record_id = getattr(outcome, "record_id", None) or getattr(outcome, "id", None)
    return str(record_id) if record_id is not None else None


def _outcome_record_ids(
    records: Sequence[IntelligenceRecord],
    outcomes: Any,
) -> list[str]:
    """Extract all persisted ids returned by a batch upsert."""
    if not isinstance(outcomes, (list, tuple)):
        return [str(record.id) for record in records if record.id]

    ids: list[str] = []
    for record, outcome in zip(records, outcomes):
        record_id = _outcome_record_id(outcome) or (str(record.id) if record.id else None)
        if record_id is not None:
            ids.append(record_id)
    return ids


def _changed_count(
    records: Sequence[IntelligenceRecord],
    outcomes: Any,
    changed_records: Sequence[IntelligenceRecord],
) -> int:
    """Count changed records from either a batch result or mapped records."""
    if not isinstance(outcomes, (list, tuple)):
        return len(changed_records)
    if outcomes and all(isinstance(item, IntelligenceRecord) for item in outcomes):
        return len(changed_records)
    return sum(_outcome_changed(outcome) for outcome in outcomes[: len(records)])


def _embedded_chunk_count(index_summary: Any | None) -> int:
    """Read an integer embedding count without trusting test doubles."""
    value = getattr(index_summary, "embedded_chunks", 0)
    return int(value) if isinstance(value, int) else 0


def _latest_external_update(
    batches: Sequence[Sequence[IntelligenceRecord]],
) -> datetime | None:
    """Return the latest external update timestamp in the collected batches."""
    timestamps = [
        record.updated_at
        for records in batches
        for record in records
        if record.updated_at is not None
    ]
    return max(timestamps) if timestamps else None


def _record_with_outcome_id(
    record: IntelligenceRecord,
    outcome: Any,
) -> IntelligenceRecord:
    """Attach the persisted id to a changed record when the repository returns it."""
    record_id = _outcome_record_id(outcome)
    if record_id is None:
        return record
    return record.model_copy(update={"id": record_id})


def _changed_records(
    records: Sequence[IntelligenceRecord],
    outcomes: Any,
) -> list[IntelligenceRecord]:
    """Map batch upsert outcomes back to the records that need indexing."""
    if outcomes is None or not isinstance(outcomes, (list, tuple)):
        return list(records)
    if outcomes and all(isinstance(item, IntelligenceRecord) for item in outcomes):
        return list(outcomes)
    return [
        _record_with_outcome_id(record, outcome)
        for record, outcome in zip(records, outcomes)
        if _outcome_changed(outcome)
    ]
