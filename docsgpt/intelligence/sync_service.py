"""Orchestrate bounded GitHub synchronization for an intelligence project."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date, datetime, time, timezone
from typing import Any

from requests import RequestException
from sqlalchemy import text

from docsgpt.intelligence.github_client import GitHubClient, GitHubRateLimitError
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
    ) -> None:
        """Initialize a synchronization service.

        Args:
            repository: Repository-like test double or a repository used when
                no session factory is supplied. Production callers may pass
                ``None`` and let the service create one per source transaction.
            github: Bounded GitHub API client.
            indexer: Record indexer. ``None`` is allowed until indexing is
                wired by the following implementation stage.
            session_factory: Optional write transaction factory yielding a
                SQLAlchemy connection.
            readonly_factory: Optional read-only transaction factory for the
                owner-scoped project lookup.
            now_factory: Clock injection for deterministic tests.
        """
        self.repository = repository
        self.github = github
        self.indexer = indexer
        self.session_factory = session_factory
        self.readonly_factory = readonly_factory
        self.now_factory = now_factory or (lambda: datetime.now(tz=UTC))

    def run(self, project_id: str, user_id: str) -> SyncSummary:
        """Synchronize one owner-scoped project and return its summary.

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
        since = datetime.combine(window_start, time.min, tzinfo=UTC)
        until = datetime.combine(window_end, time.max, tzinfo=UTC)
        counts = {source_type: 0 for source_type in SourceType}
        failures: list[SyncFailure] = []
        observed_dates: list[date] = []
        successful_sources: set[SourceType] = set()
        capped = False

        run_id = self._start_sync_run(project_id)
        self._set_project_status(project_id, user_id, "syncing")

        document_collector = getattr(self.github, "iter_documents", None)
        if callable(document_collector):
            document_ok, _, document_capped = self._run_source(
                project_id=project_id,
                source_type=SourceType.DOCUMENTATION,
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
            )
            if document_ok:
                successful_sources.add(SourceType.DOCUMENTATION)
            capped = capped or document_capped

        release_ok, _, release_capped = self._run_source(
            project_id=project_id,
            source_type=SourceType.RELEASE,
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
        )
        if release_ok:
            successful_sources.add(SourceType.RELEASE)
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

        issue_ok, _, issue_capped = self._run_source(
            project_id=project_id,
            source_type=SourceType.ISSUE,
            producer=collect_issues,
            counts=counts,
            failures=failures,
            observed_dates=observed_dates,
        )
        if issue_ok:
            successful_sources.add(SourceType.ISSUE)
        capped = capped or issue_capped

        if issue_ok and issue_raws is not None:
            comment_ok, _, comment_capped = self._run_source(
                project_id=project_id,
                source_type=SourceType.ISSUE_COMMENT,
                producer=lambda: self._collect_comments(
                    repository_name,
                    issue_raws,
                    retrieved_at,
                ),
                counts=counts,
                failures=failures,
                observed_dates=observed_dates,
            )
            if comment_ok:
                successful_sources.add(SourceType.ISSUE_COMMENT)
            capped = capped or comment_capped

        status = _summary_status(successful_sources, failures)
        last_synced_at = retrieved_at if successful_sources else None
        coverage = Coverage(
            repositories=[repository_name],
            date_from=min(observed_dates) if observed_dates else window_start,
            date_to=max(observed_dates) if observed_dates else window_end,
            counts=counts,
            capped=capped,
            last_synced_at=last_synced_at,
        )
        summary = SyncSummary(
            status=status,
            counts=counts,
            failures=failures,
            coverage=coverage,
        )

        if run_id is not None:
            self._finish_sync_run(run_id, summary)
        self._set_project_status(
            project_id,
            user_id,
            "ready" if status == "complete" else status,
            last_synced_at=last_synced_at,
        )
        return summary

    def _run_source(
        self,
        *,
        project_id: str,
        source_type: SourceType,
        producer: Callable[[], tuple[list[IntelligenceRecord], bool]],
        counts: dict[SourceType, int],
        failures: list[SyncFailure],
        observed_dates: list[date],
    ) -> tuple[bool, list[IntelligenceRecord], bool]:
        """Collect, normalize and persist one source batch."""
        try:
            records, capped = producer()
        except Exception as exc:
            failures.append(_to_sync_failure(source_type, exc))
            return False, [], False

        # One call opens one transaction for the entire source batch. A
        # failure here is a local consistency failure and must not be recast as
        # a successful GitHub partial result.
        self._persist_batch(project_id, records)
        counts[source_type] = len(records)
        observed_dates.extend(
            record_date
            for record in records
            for record_date in _record_dates(record)
        )
        return True, records, capped

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
    ) -> None:
        """Upsert and index a source batch inside one write transaction."""
        if not records:
            return
        with self._repository_context() as repository:
            upsert_many = getattr(repository, "upsert_records", None)
            if callable(upsert_many):
                result = upsert_many(project_id, records)
                changed_records = _changed_records(records, result)
            else:
                changed_records = []
                for record in records:
                    outcome = repository.upsert_record(project_id, record)
                    if _outcome_changed(outcome):
                        changed_records.append(record)

            if self.indexer is not None and changed_records:
                self.indexer.replace_records(project_id, changed_records)

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
            row = starter(project_id)
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
    ) -> None:
        """Persist the project lifecycle state when supported."""
        with self._repository_context() as repository:
            updater = getattr(repository, "set_project_status", None)
            if callable(updater):
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
                            last_synced_at = COALESCE(:last_synced_at, last_synced_at)
                        WHERE id = CAST(:project_id AS uuid)
                          AND user_id = :user_id
                        """
                    ),
                    {
                        "project_id": project_id,
                        "user_id": user_id,
                        "status": status,
                        "last_synced_at": last_synced_at,
                    },
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
    if outcome is None:
        return True
    return bool(getattr(outcome, "changed", True))


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
        record
        for record, outcome in zip(records, outcomes)
        if _outcome_changed(outcome)
    ]
