# OpenScout AI Stage A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portfolio-ready OpenScout AI release that ingests the fixed Dify, RAGFlow, and FastGPT GitHub datasets, answers five classes of questions with traceable evidence, compares products, exports reports, and publishes reproducible RAG experiments.

**Architecture:** Add a bounded `docsgpt/intelligence/` vertical slice on top of DocsGPT. PostgreSQL stores normalized GitHub facts and deterministic analytics; pgvector/HybridRetriever stores and retrieves chunks; existing GraphRAG handles only selected relational questions; a React feature folder consumes one typed `/api/intelligence` contract. Keep GitHub collection, normalization, persistence, indexing, routing, evidence validation, and presentation as separate units.

**Tech Stack:** Python 3.12, Flask-RESTX, SQLAlchemy Core, Alembic, PostgreSQL/pgvector, Redis/Celery, Pydantic 2, pytest, React 18, TypeScript, Redux Toolkit, Vite/Vitest, ReportLab.

**Spec:** `docs/superpowers/specs/2026-09-14-openscout-ai-design.md`

## Global Constraints

- Stage A repositories are exactly `langgenius/dify`, `infiniflow/ragflow`, and `labring/FastGPT`.
- Initial data window is exactly `2025-09-14` through `2026-09-14`; later runs interpret it as a rolling 12-month window.
- Keep at most 1,000 non-PR Issues per repository and the first 20 comments by creation time per Issue.
- Only root README files, text files under `docs/`, Releases, Issues, and Issue comments are in scope.
- The idempotency key is `repository + source_type + external_id`; unchanged `content_hash` records must not be re-embedded.
- GraphRAG receives docs, Releases, and at most 300 high-signal Issues per repository; it never supplies counts or trends.
- Router confidence below `0.65` falls back to Hybrid retrieval.
- Explicit UI filters override filters inferred from question text.
- Every factual claim has at least one evidence id; unsupported content is labeled `inference` or refused.
- PostgreSQL performs exact statistics; the LLM never performs exact counting.
- Backend additions use type hints, Google-style docstrings, and lines no longer than 120 characters.
- New frontend code lives in `frontend/src/intelligence/`, uses Redux for shared state, and does not broadly refactor DocsGPT UI.
- Metrics and resume claims use measured values only; secrets, GitHub tokens, and raw user identity are never committed.

## File Structure

| Area | Files | Responsibility |
|---|---|---|
| Domain contracts | `docsgpt/intelligence/schemas.py` | Enums and immutable request/result models shared by services |
| GitHub boundary | `docsgpt/intelligence/github_client.py` | HTTP, pagination, rate-limit classification, raw objects |
| Normalization | `docsgpt/intelligence/normalizer.py` | Filtering, templates, metadata, stable hashes |
| Persistence | `docsgpt/storage/db/repositories/intelligence.py` | Owner-scoped projects, records, sync runs, reports, analytics |
| Orchestration | `docsgpt/intelligence/sync_service.py`, `tasks.py` | Partial-success collection, persistence, indexing, task status |
| Retrieval | `indexing.py`, `filters.py`, `reranker.py`, `query_router.py`, `query_service.py` | Chunking, retrieval, routing, fallback, trace |
| Trust layer | `analytics.py`, `confidence.py`, `claims.py` | SQL statistics, deterministic confidence, citation enforcement |
| Reports | `report_service.py` | One report model rendered to Markdown and PDF |
| API | `docsgpt/api/user/intelligence/routes.py` | Authenticated JSON endpoints only; no SQL or provider logic |
| Frontend | `frontend/src/intelligence/` | Overview, workbench, evidence, matrix, report experience |
| Evaluation | `evaluation/` | Versioned questions, configs, run records, metrics, summaries |

---

### Task 1: Freeze the Stage A contracts and baseline

**Files:**
- Create: `docsgpt/intelligence/__init__.py`
- Create: `docsgpt/intelligence/schemas.py`
- Create: `tests/intelligence/test_schemas.py`
- Create: `evaluation/fixtures/stage_a_snapshot.json`
- Create: `docs/openscout/decision-log.md`

**Interfaces:**
- Consumes: Pydantic 2 and ISO-8601 UTC datetimes.
- Produces: `SourceType`, `QueryIntent`, `RetrievalStrategy`, `ClaimKind`, `Confidence`, `IntelligenceProject`, `IntelligenceRecord`, `QueryFilters`, `QueryRequest`, `Evidence`, `Claim`, `Coverage`, `SyncSummary`, `RetrievalTrace`, and `QueryResult`.

- [ ] **Step 1: Write the schema contract test**

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from docsgpt.intelligence.schemas import Claim, ClaimKind, Evidence


def test_factual_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence_ids"):
        Claim(id="c1", text="Dify released feature X", kind=ClaimKind.FACT, evidence_ids=[])


def test_evidence_serializes_utc_timestamp() -> None:
    evidence = Evidence(
        id="e1", record_id="r1", repository="langgenius/dify",
        source_type="release", title="v1", excerpt="notes", source_url="https://github.com/x",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert evidence.model_dump(mode="json")["occurred_at"] == "2026-01-01T00:00:00Z"
```

- [ ] **Step 2: Run the contract test and confirm the import fails**

Run: `python -m pytest tests/intelligence/test_schemas.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'docsgpt.intelligence'`.

- [ ] **Step 3: Implement the shared enums and models**

```python
class SourceType(StrEnum):
    DOCUMENTATION = "documentation"
    ISSUE = "issue"
    ISSUE_COMMENT = "issue_comment"
    RELEASE = "release"


class QueryIntent(StrEnum):
    FACTUAL = "factual"
    TEMPORAL = "temporal"
    COMPARATIVE = "comparative"
    AGGREGATE = "aggregate"
    RELATIONAL = "relational"


class RetrievalStrategy(StrEnum):
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"
    SQL_PLUS_HYBRID = "sql_plus_hybrid"
    SPLIT_HYBRID = "split_hybrid"
    GRAPHRAG = "graphrag"


class ClaimKind(StrEnum):
    FACT = "fact"
    STATISTIC = "statistic"
    INFERENCE = "inference"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IntelligenceProject(BaseModel):
    id: str
    user_id: str
    repository: str
    window_start: date
    window_end: date
    status: Literal["draft", "syncing", "ready", "partial", "failed"]
    last_synced_at: datetime | None = None


class IntelligenceRecord(BaseModel):
    id: str | None = None
    repository: str
    source_type: SourceType
    external_id: str
    title: str
    body: str
    source_url: HttpUrl
    state: str | None = None
    labels: list[str] = Field(default_factory=list)
    comments_count: int = 0
    reactions_count: int = 0
    version: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    content_hash: str

    def to_repository_params(self, project_id: str) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["project_id"] = project_id
        data["metadata"] = json.dumps({
            key: data[key] for key in (
                "state", "labels", "comments_count", "reactions_count", "version",
                "created_at", "updated_at", "published_at",
            )
        })
        return data


class SyncFailure(BaseModel):
    source_type: SourceType
    category: Literal["rate_limit", "auth", "not_found", "network", "invalid_payload"]
    retryable: bool
    message: str


class QueryFilters(BaseModel):
    repositories: list[str] = Field(default_factory=list)
    source_types: list[SourceType] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    filters: QueryFilters = Field(default_factory=QueryFilters)


class Evidence(BaseModel):
    id: str
    record_id: str
    repository: str
    source_type: SourceType
    title: str
    excerpt: str
    source_url: HttpUrl
    occurred_at: datetime | None = None
    author: str | None = None


class Claim(BaseModel):
    id: str
    text: str
    kind: ClaimKind
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.LOW

    @model_validator(mode="after")
    def require_evidence_for_facts(self) -> "Claim":
        if self.kind in {ClaimKind.FACT, ClaimKind.STATISTIC} and not self.evidence_ids:
            raise ValueError("evidence_ids required for factual claims")
        return self


class Coverage(BaseModel):
    repositories: list[str]
    date_from: date | None
    date_to: date | None
    counts: dict[SourceType, int]
    capped: bool = False
    last_synced_at: datetime | None = None


class SyncSummary(BaseModel):
    status: Literal["complete", "partial", "failed"]
    counts: dict[SourceType, int]
    failures: list[SyncFailure] = Field(default_factory=list)
    coverage: Coverage


class RetrievalTrace(BaseModel):
    intent: QueryIntent
    strategy: RetrievalStrategy
    fallback_reason: str | None = None
    applied_filters: QueryFilters


class QueryResult(BaseModel):
    answer: str
    claims: list[Claim]
    evidence: list[Evidence]
    coverage: Coverage
    latency_ms: int
    trace: RetrievalTrace
```

All later API and UI types must mirror these serialized names exactly.

- [ ] **Step 4: Add a sanitized snapshot manifest and first decision entry**

```json
{
  "snapshot_id": "stage-a-2026-09-14",
  "window": {"from": "2025-09-14", "to": "2026-09-14"},
  "repositories": ["langgenius/dify", "infiniflow/ragflow", "labring/FastGPT"],
  "issue_limit_per_repository": 1000,
  "comment_limit_per_issue": 20
}
```

In `decision-log.md`, record that public GitHub community activity is a product signal, not commercial demand.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/intelligence/test_schemas.py -q`

Expected: PASS.

```bash
git add docsgpt/intelligence tests/intelligence evaluation/fixtures docs/openscout/decision-log.md
git commit -m "feat(openscout): define stage A intelligence contracts"
```

### Task 2: Persist projects, records, sync runs, and reports

**Files:**
- Create: `docsgpt/alembic/versions/0032_openscout_intelligence.py`
- Modify: `docsgpt/storage/db/models.py`
- Create: `docsgpt/storage/db/repositories/intelligence.py`
- Create: `tests/storage/db/repositories/test_intelligence.py`

**Interfaces:**
- Consumes: `IntelligenceRecord` from Task 1 and an SQLAlchemy `Connection`.
- Produces: `IntelligenceRepository.create_project(user_id: str, repository: str, window_start: date, window_end: date) -> dict`, `upsert_record(project_id: str, record: IntelligenceRecord) -> UpsertOutcome`, `start_sync_run(project_id: str) -> dict`, `finish_sync_run(run_id: str, summary: SyncSummary) -> dict`, and `save_report(user_id: str, report_data: dict[str, Any]) -> dict`.

- [ ] **Step 1: Write repository tests for ownership and hash idempotency**

```python
def test_upsert_record_skips_unchanged_content(pg_conn, intelligence_record) -> None:
    repo = IntelligenceRepository(pg_conn)
    first = repo.upsert_record("project-uuid", intelligence_record)
    second = repo.upsert_record("project-uuid", intelligence_record)
    assert first.changed is True
    assert second.changed is False
    assert second.record_id == first.record_id


def test_project_lookup_is_owner_scoped(pg_conn) -> None:
    row = IntelligenceRepository(pg_conn).create_project(
        user_id="owner", repository="langgenius/dify",
        window_start=date(2025, 9, 14), window_end=date(2026, 9, 14),
    )
    assert IntelligenceRepository(pg_conn).get_project(str(row["id"]), "other") is None
```

- [ ] **Step 2: Run the repository tests and confirm missing tables/classes**

Run: `python -m pytest tests/storage/db/repositories/test_intelligence.py -q`

Expected: FAIL because `IntelligenceRepository` and the four tables do not exist.

- [ ] **Step 3: Add migration and matching SQLAlchemy Core tables**

Create `intelligence_projects`, `intelligence_records`, `intelligence_sync_runs`, `intelligence_reports`, and `intelligence_topic_runs`. The topic table stores `project_id`, `snapshot_id`, `algorithm_version`, `clusters` JSONB, and `created_at` so trend results are reproducible. Enforce:

```sql
UNIQUE (project_id, source_type, external_id);
CHECK (source_type IN ('documentation', 'issue', 'issue_comment', 'release'));
CREATE INDEX intelligence_records_project_type_idx ON intelligence_records(project_id, source_type);
CREATE INDEX intelligence_records_created_idx ON intelligence_records(project_id, created_at);
CREATE INDEX intelligence_records_labels_gin_idx ON intelligence_records USING gin(labels);
```

`intelligence_reports` owns its JSON and rendered storage paths directly; do not reuse `artifacts`, because `artifacts_parent_present_check` requires a conversation or workflow parent.

- [ ] **Step 4: Implement the repository around one owner-scoped class**

```python
@dataclass(frozen=True)
class UpsertOutcome:
    record_id: str
    changed: bool


class IntelligenceRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert_record(self, project_id: str, record: IntelligenceRecord) -> UpsertOutcome:
        row = self._conn.execute(
            text("""
                WITH changed AS (
                    INSERT INTO intelligence_records
                        (project_id, repository, source_type, external_id, title, body,
                         source_url, metadata, content_hash, retrieved_at)
                    VALUES
                        (CAST(:project_id AS uuid), :repository, :source_type, :external_id,
                         :title, :body, :source_url, CAST(:metadata AS jsonb), :content_hash,
                         :retrieved_at)
                    ON CONFLICT (project_id, source_type, external_id) DO UPDATE SET
                        title = EXCLUDED.title, body = EXCLUDED.body,
                        source_url = EXCLUDED.source_url, metadata = EXCLUDED.metadata,
                        content_hash = EXCLUDED.content_hash,
                        retrieved_at = EXCLUDED.retrieved_at, updated_at = now()
                    WHERE intelligence_records.content_hash <> EXCLUDED.content_hash
                    RETURNING id
                )
                SELECT id, true AS changed FROM changed
                UNION ALL
                SELECT id, false AS changed FROM intelligence_records
                WHERE project_id = CAST(:project_id AS uuid)
                  AND source_type = :source_type AND external_id = :external_id
                LIMIT 1
            """),
            record.to_repository_params(project_id),
        ).mappings().one()
        return UpsertOutcome(record_id=str(row["id"]), changed=bool(row["changed"]))
```

Use bound parameters for every value and return dictionaries through `row_to_dict`; only analytics sort/dimension names may use a whitelist.

- [ ] **Step 5: Apply, downgrade, re-apply, test, and commit**

Run: `python -m alembic -c docsgpt/alembic.ini upgrade head`

Run: `python -m alembic -c docsgpt/alembic.ini downgrade 0031_token_usage_cache_tokens`

Run: `python -m alembic -c docsgpt/alembic.ini upgrade head`

Run: `python -m pytest tests/storage/db/repositories/test_intelligence.py -q`

Expected: all commands succeed and tests PASS.

```bash
git add docsgpt/alembic/versions/0032_openscout_intelligence.py docsgpt/storage/db/models.py docsgpt/storage/db/repositories/intelligence.py tests/storage/db/repositories/test_intelligence.py
git commit -m "feat(openscout): persist intelligence records and runs"
```

### Task 3: Collect bounded GitHub Issues, comments, and Releases

**Files:**
- Create: `docsgpt/intelligence/github_client.py`
- Create: `tests/intelligence/test_github_client.py`
- Modify: `docsgpt/parser/remote/github_loader.py`

**Interfaces:**
- Consumes: `GitHubLoader.normalize_repo(repo_url: str) -> str` and `settings.GITHUB_ACCESS_TOKEN`.
- Produces: `GitHubClient.iter_issues(repo, since, until, limit=1000)`, `iter_comments(repo, issue_number, limit=20)`, `iter_releases(repo, since, until)`, and typed `GitHubRateLimitError(reset_at)`.

- [ ] **Step 1: Write recorded-response tests**

```python
def test_iter_issues_filters_pull_requests_and_stops_at_limit(responses) -> None:
    responses.add(responses.GET, "https://api.github.com/repos/o/r/issues?state=all&per_page=100&page=1", json=[
        {"id": 1, "number": 1, "title": "issue", "updated_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "number": 2, "title": "pr", "pull_request": {}},
    ], headers={"Link": ""})
    rows = list(GitHubClient().iter_issues("o/r", DATE_FROM, DATE_TO, limit=1))
    assert [row["id"] for row in rows] == [1]


def test_rate_limit_is_recoverable(responses) -> None:
    responses.add(responses.GET, re.compile(r"api.github.com"), status=403,
                  headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1800000000"})
    with pytest.raises(GitHubRateLimitError) as exc:
        list(GitHubClient().iter_releases("o/r", DATE_FROM, DATE_TO))
    assert exc.value.reset_at.timestamp() == 1800000000
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_github_client.py -q`

Expected: FAIL with missing `docsgpt.intelligence.github_client`.

- [ ] **Step 3: Extract the existing authenticated request seam**

Change `GitHubLoader._make_request()` only if necessary so both callers share headers, status classification, and timeout; preserve existing loader behavior and tests.

- [ ] **Step 4: Implement bounded pagination without sleeping**

```python
def _iter_pages(self, url: str, params: dict[str, object]) -> Iterator[dict[str, Any]]:
    page = 1
    while True:
        response = self._request(url, params={**params, "per_page": 100, "page": page})
        batch = response.json()
        if not batch:
            return
        yield from batch
        if 'rel="next"' not in response.headers.get("Link", ""):
            return
        page += 1
```

Filter by the requested window in code, sort comments by `created_at`, and slice to 20. On rate limit, raise; Celery decides when to retry.

- [ ] **Step 5: Run focused and existing loader tests, then commit**

Run: `python -m pytest tests/intelligence/test_github_client.py tests/parser -q`

Expected: PASS.

```bash
git add docsgpt/intelligence/github_client.py docsgpt/parser/remote/github_loader.py tests/intelligence/test_github_client.py
git commit -m "feat(openscout): collect bounded GitHub community data"
```

### Task 4: Normalize GitHub objects into intelligence records

**Files:**
- Create: `docsgpt/intelligence/normalizer.py`
- Create: `tests/intelligence/test_normalizer.py`
- Create: `tests/intelligence/fixtures/github_objects.json`

**Interfaces:**
- Consumes: raw GitHub API dictionaries and `SourceType`.
- Produces: `is_supported_document(path: str) -> bool`, `normalize_document(repository: str, path: str, body: str, source_url: str, retrieved_at: datetime) -> IntelligenceRecord`, `normalize_issue(repository: str, raw: Mapping[str, Any], retrieved_at: datetime) -> IntelligenceRecord`, `normalize_comment(repository: str, issue_number: int, raw: Mapping[str, Any], retrieved_at: datetime) -> IntelligenceRecord`, `normalize_release(repository: str, raw: Mapping[str, Any], retrieved_at: datetime) -> IntelligenceRecord`, and `content_hash(body: str, metadata: Mapping[str, Any]) -> str`.

- [ ] **Step 1: Write filtering and stable-hash tests**

```python
@pytest.mark.parametrize("path,expected", [
    ("README.md", True), ("docs/guide.md", True),
    ("src/main.py", False), ("documentation.md", False),
])
def test_supported_document_scope(path: str, expected: bool) -> None:
    assert is_supported_document(path) is expected


def test_issue_hash_ignores_retrieval_time(raw_issue) -> None:
    a = normalize_issue("o/r", raw_issue, retrieved_at=UTC_A)
    b = normalize_issue("o/r", raw_issue, retrieved_at=UTC_B)
    assert a.content_hash == b.content_hash
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_normalizer.py -q`

Expected: FAIL with missing normalizer functions.

- [ ] **Step 3: Implement source-specific templates and canonical hashing**

```python
def content_hash(body: str, metadata: Mapping[str, Any]) -> str:
    canonical = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{body.strip()}\n{canonical}".encode()).hexdigest()
```

Hash only content-bearing fields; exclude `retrieved_at`. Preserve Markdown headings, lists, and code fences. Use GitHub HTML URLs, never API URLs, as `source_url`.

- [ ] **Step 4: Assert an exact fixture for 20 normalized records**

Add `test_normalized_fixture_matches_expected_json()` that loads `github_objects.json`, normalizes all 20 entries, and compares `model_dump(mode="json")` with a checked-in expected list.

Run: `python -m pytest tests/intelligence/test_normalizer.py::test_normalized_fixture_matches_expected_json -q`

Expected: fixture snapshots contain repository, source type, dates, labels, counts, version, URL, and hash for all four source types.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/intelligence/test_normalizer.py -q`

Expected: PASS without modifying snapshots.

```bash
git add docsgpt/intelligence/normalizer.py tests/intelligence
git commit -m "feat(openscout): normalize traceable GitHub evidence"
```

### Task 5: Orchestrate partial-success synchronization

**Files:**
- Create: `docsgpt/intelligence/sync_service.py`
- Create: `docsgpt/intelligence/tasks.py`
- Modify: `docsgpt/celeryconfig.py`
- Create: `tests/intelligence/test_sync_service.py`
- Create: `tests/intelligence/test_tasks.py`

**Interfaces:**
- Consumes: `GitHubClient`, normalizers, and `IntelligenceRepository`.
- Produces: `SyncService.run(project_id: str, user_id: str) -> SyncSummary` and Celery task `sync_intelligence_project(project_id, user_id, idempotency_key=None) -> dict`.

- [ ] **Step 1: Write a partial-success service test**

```python
def test_sync_commits_releases_when_issues_fail(repo, github, indexer) -> None:
    github.iter_releases.return_value = [RAW_RELEASE]
    github.iter_issues.side_effect = GitHubRateLimitError(RESET_AT)
    summary = SyncService(repo, github, indexer).run(PROJECT_ID, "u1")
    assert summary.status == "partial"
    assert summary.counts["release"] == 1
    assert summary.failures[0].source_type == "issue"
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_sync_service.py tests/intelligence/test_tasks.py -q`

Expected: FAIL with missing service and task.

- [ ] **Step 3: Implement one transaction per source batch**

```python
for source_type, collector in collectors.items():
    try:
        records = [normalize(raw) for raw in collector()]
        changed = repository.upsert_records(project_id, records)
        indexer.replace_records(project_id, changed)
        summary.record_success(source_type, records)
    except RecoverableGitHubError as exc:
        summary.record_failure(source_type, exc)
```

Persist status `queued -> running -> complete|partial|failed`; record exact object counts, earliest/latest timestamps, capped flags, error category, and last successful sync time.

- [ ] **Step 4: Register an idempotent bounded-retry Celery task**

```python
@celery.task(bind=True, autoretry_for=(RecoverableGitHubError,), retry_backoff=True,
             retry_kwargs={"max_retries": 4})
@with_idempotency("sync_intelligence_project")
def sync_intelligence_project(self, *, project_id: str, user_id: str,
                              idempotency_key: str | None = None) -> dict:
    return build_sync_service().run(project_id, user_id).model_dump(mode="json")
```

Add `docsgpt.intelligence.tasks` to `celeryconfig.imports`; do not add it to the parsing or embeddings queue.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/intelligence/test_sync_service.py tests/intelligence/test_tasks.py -q`

Expected: PASS; a retry preserves successful source batches.

```bash
git add docsgpt/intelligence/sync_service.py docsgpt/intelligence/tasks.py docsgpt/celeryconfig.py tests/intelligence
git commit -m "feat(openscout): synchronize GitHub data with partial success"
```

### Task 6: Index only changed records with traceable chunk metadata

**Files:**
- Create: `docsgpt/intelligence/indexing.py`
- Create: `tests/intelligence/test_indexing.py`
- Modify: `docsgpt/intelligence/sync_service.py`

**Interfaces:**
- Consumes: changed `IntelligenceRecord` rows and `VectorCreator.create_vectorstore(settings.VECTOR_STORE, source_id=project_id, embeddings_key=settings.EMBEDDINGS_KEY)`.
- Produces: `IntelligenceIndexer.replace_records(project_id: str, records: Sequence[IntelligenceRecord]) -> IndexSummary` and `chunks_for_record(record) -> list[Document]`.

- [ ] **Step 1: Write chunk and no-op reindex tests**

```python
def test_issue_stays_single_chunk_when_under_limit() -> None:
    chunks = chunks_for_record(issue_record(body="short"))
    assert len(chunks) == 1
    assert chunks[0].metadata["record_id"] == "issue:42"


def test_unchanged_sync_adds_no_embeddings(repo, vector_store, record) -> None:
    indexer = IntelligenceIndexer(repo, vector_store)
    assert indexer.replace_records(PROJECT_ID, [record]).embedded_chunks == 1
    assert indexer.replace_records(PROJECT_ID, []).embedded_chunks == 0
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_indexing.py -q`

Expected: FAIL with missing indexer.

- [ ] **Step 3: Implement source-aware chunking**

README/docs split at Markdown heading boundaries; Issue/Release remain one chunk below the configured token ceiling and use recursive splitting above it. Every chunk metadata dictionary contains:

```python
{
    "record_id": record.id,
    "project_id": project_id,
    "repository": record.repository,
    "source_type": record.source_type.value,
    "occurred_at": record.occurred_at.isoformat() if record.occurred_at else None,
    "version": record.version,
    "source": record.source_url,
}
```

- [ ] **Step 4: Implement targeted replacement**

Delete old chunks by stable metadata source `openscout://{project_id}/{record_id}`, add the new chunks with `add_texts`, and store returned chunk ids for GraphRAG selection. Never call `delete_index()` for an incremental record change.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/intelligence/test_indexing.py tests/vectorstore/test_pgvector.py -q`

Expected: PASS; changing one Issue only replaces that Issue's chunks.

```bash
git add docsgpt/intelligence/indexing.py docsgpt/intelligence/sync_service.py tests/intelligence/test_indexing.py
git commit -m "feat(openscout): index changed evidence records"
```

### Task 7: Expose project, synchronization, overview, and query contracts

**Files:**
- Create: `docsgpt/api/user/intelligence/__init__.py`
- Create: `docsgpt/api/user/intelligence/routes.py`
- Modify: `docsgpt/api/user/routes.py`
- Create: `tests/api/user/intelligence/test_routes.py`
- Create: `docsgpt/intelligence/query_service.py`
- Create: `tests/intelligence/test_query_service.py`
- Create: `docsgpt/seed/intelligence_projects.py`

**Interfaces:**
- Consumes: owner-scoped repository, Celery task, `HybridRetriever`, and Task 1 schemas.
- Produces: `POST /api/intelligence/projects`, `POST /api/intelligence/projects/<id>/sync`, `GET /api/intelligence/projects`, `GET /api/intelligence/projects/<id>`, `GET /api/intelligence/sync-runs/<id>`, `GET /api/intelligence/overview`, and `POST /api/intelligence/query`.

- [ ] **Step 1: Write auth, ownership, and response-shape API tests**

```python
def test_query_requires_auth(client) -> None:
    assert client.post("/api/intelligence/query", json={"question": "x"}).status_code == 401


def test_query_shape(client, auth_headers, mock_query_service) -> None:
    response = client.post("/api/intelligence/query", headers=auth_headers, json={
        "question": "Which product added SSO?",
        "filters": {"repositories": ["langgenius/dify"]},
    })
    assert set(response.json) == {"answer", "claims", "evidence", "coverage", "latency_ms", "trace"}


def test_stage_a_seed_contains_exact_repositories() -> None:
    assert [item.repository for item in stage_a_projects()] == [
        "langgenius/dify", "infiniflow/ragflow", "labring/FastGPT",
    ]
```

- [ ] **Step 2: Run and confirm route failure**

Run: `python -m pytest tests/api/user/intelligence/test_routes.py tests/intelligence/test_query_service.py -q`

Expected: FAIL with 404 or missing imports.

- [ ] **Step 3: Implement a thin namespace and request validation**

Set `Namespace("intelligence", path="/api")`; read `request.decoded_token["sub"]`; reject malformed UUIDs before database casts; call services inside `db_readonly()`/`db_session()`; never execute SQL in routes. Add an idempotent seed helper that creates exactly the three Stage A repositories with the fixed window and can be rerun without duplicates.

- [ ] **Step 4: Implement the initial Hybrid-only query path**

```python
class QueryService:
    def query(self, request: QueryRequest, user_id: str) -> QueryResult:
        evidence = self.retriever.retrieve(request.question, request.filters)
        claims = self.generator.generate(request.question, evidence)
        return enforce_citations(claims=claims, evidence=evidence, coverage=self.coverage(request.filters))
```

For this task, `trace.strategy` is `hybrid`; SQL, routing, and GraphRAG arrive in later tasks.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/api/user/intelligence/test_routes.py tests/intelligence/test_query_service.py -q`

Expected: PASS, including 401, 403/404 owner isolation, 400 validation, and 202 sync dispatch.

```bash
git add docsgpt/api/user/intelligence docsgpt/api/user/routes.py docsgpt/intelligence/query_service.py docsgpt/seed/intelligence_projects.py tests/api/user/intelligence tests/intelligence/test_query_service.py
git commit -m "feat(openscout): expose intelligence project and query APIs"
```

### Task 8: Build the reproducible evaluation harness and vector/hybrid experiment

**Files:**
- Create: `evaluation/dataset/questions.dev.jsonl`
- Create: `evaluation/dataset/questions.holdout.jsonl`
- Create: `evaluation/configs/vector.yaml`
- Create: `evaluation/configs/hybrid.yaml`
- Create: `evaluation/metrics.py`
- Create: `evaluation/run_eval.py`
- Create: `evaluation/summarize.py`
- Create: `evaluation/check_regression.py`
- Create: `tests/evaluation/test_metrics.py`

**Interfaces:**
- Consumes: `POST /api/intelligence/query` compatible query runner and fixed snapshot id.
- Produces: `recall_at_k(expected: Sequence[str], retrieved: Sequence[str], k: int) -> float`, `ndcg_at_k(expected: Sequence[str], retrieved: Sequence[str], k: int) -> float`, `citation_precision(cited: Sequence[str], expected: Sequence[str]) -> float`, JSONL run records, and Markdown comparison summaries.

- [ ] **Step 1: Write metric tests with hand-calculated values**

```python
def test_recall_at_five() -> None:
    assert recall_at_k(["a", "b"], ["x", "a", "y"], 5) == 0.5


def test_ndcg_rewards_earlier_relevant_evidence() -> None:
    assert ndcg_at_k(["a"], ["a", "x"], 10) > ndcg_at_k(["a"], ["x", "a"], 10)


def test_citation_precision() -> None:
    assert citation_precision(["a", "x"], ["a", "b"]) == 0.5
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/evaluation/test_metrics.py -q`

Expected: FAIL with missing `evaluation.metrics`.

- [ ] **Step 3: Implement deterministic metrics and run schema**

Each JSONL result contains `run_id`, `snapshot_id`, config hash, question id/type, expected URLs, retrieved URLs/ranks, answer rubric score, citation score, faithfulness score, latency ms, prompt/completion tokens, model, and timestamp.

- [ ] **Step 4: Create 60 reviewed development and 20 sealed holdout questions**

Use exactly 15 development and 5 holdout questions for each of `factual`, `temporal`, `comparative`, and `comprehensive`; comprehensive rows add subtype `aggregate` or `relational`. Each line contains question, answer points, evidence URLs, repositories, date range, and acceptance rules. Add `evaluation/dataset/README.md` stating holdout answers must not be edited after experiment selection. Implement `check_regression.py` to exit non-zero when any tracked metric drops by more than `0.05` against the committed baseline.

- [ ] **Step 5: Run vector and hybrid configurations and commit measured outputs**

Run: `python evaluation/run_eval.py --config evaluation/configs/vector.yaml --split dev`

Run: `python evaluation/run_eval.py --config evaluation/configs/hybrid.yaml --split dev`

Run: `python evaluation/summarize.py --baseline vector --candidate hybrid`

Expected: two immutable result JSONL files and one Markdown delta table; do not promote Hybrid unless the measured evidence supports it.

```bash
git add evaluation tests/evaluation
git commit -m "test(openscout): add reproducible retrieval evaluation"
```

### Task 9: Apply explicit time/source filters and optional reranking

**Files:**
- Create: `docsgpt/intelligence/filters.py`
- Create: `docsgpt/intelligence/reranker.py`
- Modify: `docsgpt/intelligence/query_service.py`
- Create: `tests/intelligence/test_filters.py`
- Create: `tests/intelligence/test_reranker.py`
- Create: `evaluation/configs/hybrid-rerank.yaml`

**Interfaces:**
- Consumes: `QueryFilters`, Hybrid candidate `Evidence` objects.
- Produces: `merge_filters(explicit, inferred) -> QueryFilters`, protocol `Reranker.rerank(question, evidence, top_n) -> list[Evidence]`, and `NoOpReranker` fallback.

- [ ] **Step 1: Write precedence and fallback tests**

```python
def test_explicit_filters_override_inferred_dates() -> None:
    merged = merge_filters(QueryFilters(date_from=date(2026, 1, 1)), QueryFilters(date_from=date(2025, 1, 1)))
    assert merged.date_from == date(2026, 1, 1)


def test_reranker_failure_preserves_hybrid_order() -> None:
    assert safe_rerank(BrokenReranker(), "q", EVIDENCE, 5) == EVIDENCE[:5]
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_filters.py tests/intelligence/test_reranker.py -q`

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement pre-retrieval metadata filtering**

Compile repository, source type, date-from, and date-to into the existing source/vector metadata filters before retrieval. Record both explicit and inferred filter values in trace, with `source: "explicit"|"inferred"`.

- [ ] **Step 4: Implement a provider-neutral reranker seam**

```python
class Reranker(Protocol):
    def rerank(self, question: str, evidence: Sequence[Evidence], top_n: int) -> list[Evidence]:
        raise NotImplementedError


def safe_rerank(reranker: Reranker, question: str, evidence: Sequence[Evidence], top_n: int) -> list[Evidence]:
    try:
        return reranker.rerank(question, evidence, top_n)
    except Exception:
        logger.exception("reranker failed; preserving hybrid order")
        return list(evidence[:top_n])
```

Use the configured reranker only; do not silently add a heavy model dependency. Persist provider/model/version in evaluation config.

- [ ] **Step 5: Evaluate, verify, and commit**

Run: `python -m pytest tests/intelligence/test_filters.py tests/intelligence/test_reranker.py tests/intelligence/test_query_service.py -q`

Run: `python evaluation/run_eval.py --config evaluation/configs/hybrid-rerank.yaml --split dev`

Expected: tests PASS and a measured Hybrid-vs-Rerank result exists.

```bash
git add docsgpt/intelligence evaluation/configs/hybrid-rerank.yaml tests/intelligence
git commit -m "feat(openscout): filter and rerank retrieved evidence"
```

### Task 10: Route questions and execute deterministic analytics

**Files:**
- Create: `docsgpt/intelligence/query_router.py`
- Create: `docsgpt/intelligence/analytics.py`
- Modify: `docsgpt/storage/db/repositories/intelligence.py`
- Modify: `docsgpt/intelligence/query_service.py`
- Create: `tests/intelligence/test_query_router.py`
- Create: `tests/intelligence/test_analytics.py`

**Interfaces:**
- Consumes: `QueryRequest` and owner-scoped project ids.
- Produces: `RouteDecision(intent, strategy, confidence, filters)`, `QueryRouter.route(request)`, and `AnalyticsService.run(AggregateQuery) -> AggregateResult`.

- [ ] **Step 1: Write routing and SQL-whitelist tests**

```python
def test_low_confidence_route_falls_back_to_hybrid() -> None:
    decision = apply_route_threshold(RouteDecision(intent="relational", strategy="graphrag", confidence=0.64))
    assert decision.strategy == "hybrid"


def test_analytics_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError, match="dimension"):
        AnalyticsService(repo).run(AggregateQuery(metric="count", dimension="body"))
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_query_router.py tests/intelligence/test_analytics.py -q`

Expected: FAIL with missing router and analytics service.

- [ ] **Step 3: Implement constrained route parsing**

Require the model/parser output to validate against `RouteDecision`; allowed strategies are `hybrid`, `hybrid_rerank`, `sql_plus_hybrid`, `split_hybrid`, and `graphrag`. Validation failure or confidence `< 0.65` becomes `hybrid` and records `fallback_reason`.

- [ ] **Step 4: Implement whitelisted aggregates**

Allowed metrics: `count`, `median_comments`, `sum_reactions`; dimensions: `repository`, `source_type`, `label`, `month`, `state`; sort: `value_asc`, `value_desc`, `period_asc`. Always return `coverage` and `capped` with results. Retrieve representative evidence after SQL; never ask the LLM to count rows.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/intelligence/test_query_router.py tests/intelligence/test_analytics.py tests/intelligence/test_query_service.py -q`

Expected: all five intents route correctly; aggregate answers carry SQL values and representative evidence.

```bash
git add docsgpt/intelligence docsgpt/storage/db/repositories/intelligence.py tests/intelligence
git commit -m "feat(openscout): route questions to retrieval and SQL"
```

### Task 11: Cluster Issue topics and build evidence-backed comparisons

**Files:**
- Create: `docsgpt/intelligence/topics.py`
- Create: `docsgpt/intelligence/comparison.py`
- Modify: `docsgpt/api/user/intelligence/routes.py`
- Create: `tests/intelligence/test_topics.py`
- Create: `tests/intelligence/test_comparison.py`
- Modify: `tests/api/user/intelligence/test_routes.py`

**Interfaces:**
- Consumes: Issue embeddings, owner-scoped records, `QueryFilters`, and the cited split-query path from Task 10.
- Produces: `cluster_issues(issues: Sequence[IntelligenceRecord], vectors: Mapping[str, Sequence[float]], max_clusters: int = 12) -> list[TopicCluster]`, `topic_trends(project_ids: Sequence[str], filters: QueryFilters) -> list[TopicTrend]`, `ComparisonService.compare(project_ids: Sequence[str], dimensions: Sequence[str], filters: QueryFilters) -> ComparisonResult`, `GET /api/intelligence/topics`, and `POST /api/intelligence/comparison`.

- [ ] **Step 1: Write deterministic clustering and unknown-cell tests**

```python
def test_cluster_assignment_is_stable_for_input_order(issue_vectors) -> None:
    forward = cluster_issues(ISSUES, issue_vectors)
    reverse = cluster_issues(list(reversed(ISSUES)), issue_vectors)
    assert [(c.id, sorted(c.record_ids)) for c in forward] == [
        (c.id, sorted(c.record_ids)) for c in reverse
    ]


def test_comparison_uses_unknown_without_supporting_evidence(service) -> None:
    result = service.compare(PROJECT_IDS, ["enterprise_sso"], FILTERS)
    cell = result.rows[0].cells["labring/FastGPT"]
    assert cell.status == "unknown"
    assert cell.display_label == "尚未确认"
    assert cell.evidence_ids == []
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_topics.py tests/intelligence/test_comparison.py -q`

Expected: FAIL with missing topics/comparison modules.

- [ ] **Step 3: Implement deterministic spherical clustering with existing NumPy**

Sort records by stable id, normalize vectors, choose `k = min(max_clusters, max(2, round(sqrt(n / 2))))`, seed centroids with deterministic farthest-point initialization, run at most 50 cosine-assignment/update iterations, and stop when assignments no longer change. Derive a human-readable label from the five most frequent non-stopword title terms; persist algorithm version, cluster id, record ids, centroid, and snapshot id. Do not add scikit-learn solely for this feature.

- [ ] **Step 4: Calculate monthly trends and cited comparison cells**

Count cluster membership by repository and month in PostgreSQL. Comparison splits each feature dimension across repositories, returns `supported`, `not_supported`, or `unknown`, and requires evidence for the first two states; missing or conflicting evidence becomes `unknown`. Each cell includes first evidence date, community-signal count, evidence ids, and coverage warning.

- [ ] **Step 5: Verify routes and commit**

Run: `python -m pytest tests/intelligence/test_topics.py tests/intelligence/test_comparison.py tests/api/user/intelligence/test_routes.py -q`

Expected: stable fixtures produce identical clusters across runs; trend counts match SQL fixtures; every non-unknown matrix cell has evidence.

```bash
git add docsgpt/intelligence/topics.py docsgpt/intelligence/comparison.py docsgpt/api/user/intelligence/routes.py tests/intelligence tests/api/user/intelligence/test_routes.py
git commit -m "feat(openscout): cluster feedback and compare products"
```

### Task 12: Select high-signal GraphRAG data and guarantee fallback

**Files:**
- Create: `docsgpt/intelligence/graph_selection.py`
- Modify: `docsgpt/intelligence/sync_service.py`
- Modify: `docsgpt/intelligence/query_service.py`
- Create: `tests/intelligence/test_graph_selection.py`
- Modify: `tests/intelligence/test_query_service.py`
- Create: `evaluation/configs/routed.yaml`

**Interfaces:**
- Consumes: persisted records, existing `extract_graph_for_source(source_id: str, user: str | None, chunks: list[dict[str, Any]], *, config: SourceConfig, request_id: str | None = None) -> dict[str, int]`, and `GraphRAGRetriever`.
- Produces: `signal_score(comments_count, reactions_count, maxima) -> float`, `select_graph_records(records, issue_limit=300)`, and routed GraphRAG fallback trace.

- [ ] **Step 1: Write cap, ranking, exclusion, and fallback tests**

```python
def test_graph_subset_caps_issues_but_keeps_docs_and_releases(records) -> None:
    selected = select_graph_records(records, issue_limit=300)
    assert len([r for r in selected if r.source_type == SourceType.ISSUE]) == 300
    assert all(r in selected for r in records if r.source_type in {SourceType.DOCUMENTATION, SourceType.RELEASE})


def test_graph_failure_falls_back_and_traces_reason(query_service) -> None:
    result = query_service.query(RELATIONAL_REQUEST, "u1")
    assert result.trace.strategy == "hybrid"
    assert result.trace.fallback_reason == "graphrag_unavailable"
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_graph_selection.py tests/intelligence/test_query_service.py -q`

Expected: FAIL with missing selector/fallback behavior.

- [ ] **Step 3: Implement normalized high-signal ranking**

```python
def signal_score(comments: int, reactions: int, max_comments: int, max_reactions: int) -> float:
    comment_score = comments / max(1, max_comments)
    reaction_score = reactions / max(1, max_reactions)
    return 0.6 * comment_score + 0.4 * reaction_score
```

Sort descending by score, then `updated_at`, then external id for deterministic ties.

- [ ] **Step 4: Wire selective extraction and query fallback**

Graph extraction runs asynchronously after vector indexing. The query service uses GraphRAG only for `relational`; if disabled, incomplete, failed, or timed out, it runs Hybrid once and records the exact reason. Analytics never receives graph-derived rows.

- [ ] **Step 5: Run routed experiment and commit**

Run: `python -m pytest tests/intelligence/test_graph_selection.py tests/intelligence/test_query_service.py -q`

Run: `python evaluation/run_eval.py --config evaluation/configs/routed.yaml --split dev`

Expected: tests PASS and the third experiment compares unified Hybrid with routed SQL/GraphRAG, including latency and token cost.

```bash
git add docsgpt/intelligence evaluation/configs/routed.yaml tests/intelligence
git commit -m "feat(openscout): route relational questions through GraphRAG"
```

### Task 13: Enforce citations and deterministic per-claim confidence

**Files:**
- Create: `docsgpt/intelligence/claims.py`
- Create: `docsgpt/intelligence/confidence.py`
- Modify: `docsgpt/intelligence/query_service.py`
- Create: `tests/intelligence/test_claims.py`
- Create: `tests/intelligence/test_confidence.py`

**Interfaces:**
- Consumes: generated claims, evidence, coverage, and conflict flags.
- Produces: `validate_claims(claims: Sequence[Claim], evidence: Sequence[Evidence], coverage: Coverage) -> ClaimValidation`, `confidence_for_claim(claim: Claim, evidence: Sequence[Evidence], coverage: Coverage, has_conflict: bool) -> Confidence`, and one-regeneration-then-degrade behavior.

- [ ] **Step 1: Encode the specification rules as table tests**

```python
@pytest.mark.parametrize("case,expected", [
    (official_release_case(), Confidence.HIGH),
    (complete_sql_case(), Confidence.HIGH),
    (two_author_issue_case(), Confidence.MEDIUM),
    (single_issue_case(), Confidence.LOW),
    (conflict_case(), Confidence.LOW),
    (inference_case(), Confidence.LOW),
])
def test_confidence_rules(case, expected) -> None:
    assert confidence_for_claim(**case) == expected
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_claims.py tests/intelligence/test_confidence.py -q`

Expected: FAIL with missing trust-layer modules.

- [ ] **Step 3: Implement evidence-id validation and conflict preservation**

Reject evidence ids not present in the response. A fact/statistic without valid evidence triggers exactly one regeneration. If still invalid, return deterministic statistics plus evidence cards and the refusal text `当前收录数据无法支持该结论`.

- [ ] **Step 4: Compute confidence per claim**

Use source type, distinct Issue authors, coverage completeness, conflict, staleness, and claim kind. Do not accept an LLM-provided confidence number. Keep conflicting claims and show both source dates.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/intelligence/test_claims.py tests/intelligence/test_confidence.py tests/intelligence/test_query_service.py -q`

Expected: PASS; the five fixed demo queries contain no uncited factual claim.

```bash
git add docsgpt/intelligence/claims.py docsgpt/intelligence/confidence.py docsgpt/intelligence/query_service.py tests/intelligence
git commit -m "feat(openscout): enforce evidence and claim confidence"
```

### Task 14: Generate one report model and export Markdown/PDF

**Files:**
- Create: `docsgpt/intelligence/report_service.py`
- Modify: `docsgpt/api/user/intelligence/routes.py`
- Create: `tests/intelligence/test_report_service.py`
- Modify: `tests/api/user/intelligence/test_routes.py`

**Interfaces:**
- Consumes: saved `QueryResult` objects and comparison/analytics results.
- Produces: `ReportDocument`, `ReportService.create(user_id: str, project_ids: Sequence[str], results: Sequence[QueryResult]) -> dict`, `render_markdown(report: ReportDocument) -> str`, `render_pdf(report: ReportDocument) -> bytes`, `POST /api/intelligence/reports`, `GET /api/intelligence/reports/<id>`, and `GET /api/intelligence/reports/<id>/download?format=markdown|pdf`.

- [ ] **Step 1: Write render parity and retry tests**

```python
def test_markdown_and_pdf_share_source_ids(report) -> None:
    markdown = render_markdown(report)
    pdf_text = extract_pdf_text(render_pdf(report))
    assert "github.com/langgenius/dify" in markdown
    assert "github.com/langgenius/dify" in pdf_text


def test_export_retry_does_not_rerun_query(report_service, query_service) -> None:
    report_service.export(REPORT_ID, "pdf")
    report_service.export(REPORT_ID, "pdf")
    query_service.query.assert_not_called()
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_report_service.py tests/api/user/intelligence/test_routes.py -q`

Expected: FAIL with missing report service/routes.

- [ ] **Step 3: Implement a single report schema**

Sections are fixed: executive summary, feature comparison, feedback trends, opportunity signals, risks/evidence limits, and complete sources. Store structured JSON before rendering; renderers accept only `ReportDocument`.

- [ ] **Step 4: Implement authenticated exports**

Markdown uses UTF-8 attachment response; PDF uses ReportLab with an embedded CJK-capable font checked into an approved assets location or an existing project font. Export failure leaves the report row intact and returns a retryable 500 without querying again.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/intelligence/test_report_service.py tests/api/user/intelligence/test_routes.py -q`

Expected: PASS; Markdown and extracted PDF text contain identical section headings and source URLs.

```bash
git add docsgpt/intelligence/report_service.py docsgpt/api/user/intelligence/routes.py tests/intelligence/test_report_service.py tests/api/user/intelligence/test_routes.py
git commit -m "feat(openscout): export evidence-backed intelligence reports"
```

### Task 15: Build typed frontend state, routing, overview, and workbench

**Files:**
- Create: `frontend/src/intelligence/types.ts`
- Create: `frontend/src/intelligence/intelligenceService.ts`
- Create: `frontend/src/intelligence/intelligenceSlice.ts`
- Create: `frontend/src/intelligence/Overview.tsx`
- Create: `frontend/src/intelligence/Workbench.tsx`
- Create: `frontend/src/intelligence/intelligenceSlice.test.ts`
- Create: `frontend/src/intelligence/Overview.test.tsx`
- Create: `frontend/src/intelligence/Workbench.test.tsx`
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/store.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/Navigation.tsx`

**Interfaces:**
- Consumes: Task 7 API and exact `QueryResult` JSON keys.
- Produces: Redux `intelligence` state, `/intelligence` overview route, `/intelligence/workbench` route, filter controls, and query dispatch.

- [ ] **Step 1: Write reducer and visible-state tests**

```tsx
it('shows capped coverage as a warning', async () => {
  render(<Overview />, {preloadedState: cappedOverviewState});
  expect(screen.getByText(/已达到 1,000 条 Issue 上限/)).toBeInTheDocument();
});

it('sends explicit filters with the question', async () => {
  render(<Workbench />);
  await userEvent.click(screen.getByLabelText('Dify'));
  await userEvent.type(screen.getByLabelText('研究问题'), '最近有哪些变化？');
  await userEvent.click(screen.getByRole('button', {name: '开始分析'}));
  expect(mockQuery).toHaveBeenCalledWith(expect.objectContaining({filters: {repositories: ['langgenius/dify']}}));
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd frontend && npm test -- --run src/intelligence/intelligenceSlice.test.ts src/intelligence/Overview.test.tsx src/intelligence/Workbench.test.tsx`

Expected: FAIL because the feature folder/routes do not exist.

- [ ] **Step 3: Implement API types and Redux state**

Mirror backend names exactly; state contains `overview`, `filters`, `question`, `queryResult`, `requestStatus`, and `error`. Use existing API base/error handling; add endpoint constants under `/api/intelligence`.

- [ ] **Step 4: Implement overview and workbench states**

Overview cards show document/Issue/Release counts, coverage, last sync, latest version, topics, capped/partial warnings. Workbench provides repository multi-select, date range, source type, question type, and five fixed recommended questions. Include loading, empty, partial, and error copy.

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && npm test -- --run src/intelligence`

Run: `cd frontend && npm run lint`

Expected: tests PASS and lint exits 0.

```bash
git add frontend/src/intelligence frontend/src/api/endpoints.ts frontend/src/store.ts frontend/src/App.tsx frontend/src/Navigation.tsx
git commit -m "feat(openscout): add intelligence overview and workbench"
```

### Task 16: Present claims, evidence, comparisons, and reports

**Files:**
- Create: `frontend/src/intelligence/ClaimCard.tsx`
- Create: `frontend/src/intelligence/EvidencePanel.tsx`
- Create: `frontend/src/intelligence/ComparisonMatrix.tsx`
- Create: `frontend/src/intelligence/ReportView.tsx`
- Create: `frontend/src/intelligence/ClaimCard.test.tsx`
- Create: `frontend/src/intelligence/ComparisonMatrix.test.tsx`
- Create: `frontend/src/intelligence/ReportView.test.tsx`
- Modify: `frontend/src/intelligence/Workbench.tsx`

**Interfaces:**
- Consumes: `QueryResult`, comparison cells, and report endpoints.
- Produces: result order `summary -> analysis -> statistics -> evidence`, per-claim kind/confidence, expandable evidence, comparison cells, and download actions.

- [ ] **Step 1: Write trust-display tests**

```tsx
it('renders unsupported comparison cells as 尚未确认', () => {
  render(<ComparisonMatrix rows={[unknownFeatureRow]} />);
  expect(screen.getByText('尚未确认')).toBeInTheDocument();
});

it('opens every claim evidence source', async () => {
  render(<ClaimCard claim={claim} evidence={evidence} />);
  await userEvent.click(screen.getByRole('button', {name: /查看 2 条证据/}));
  expect(screen.getAllByRole('link')).toHaveLength(2);
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd frontend && npm test -- --run src/intelligence/ClaimCard.test.tsx src/intelligence/ComparisonMatrix.test.tsx src/intelligence/ReportView.test.tsx`

Expected: FAIL because components do not exist.

- [ ] **Step 3: Implement evidence-first result components**

Use `lucide-react` for standard icons. Every evidence card displays source type, repository, date/version, excerpt, and external GitHub link. Show `事实`, `统计`, or `AI 推断`, plus deterministic `低/中/高` confidence. Display stale data and GraphRAG fallback at result top.

- [ ] **Step 4: Implement matrix and report flows**

Matrix cells show support status, first evidence date, community signal count, and expandable sources. Unknown cells say `尚未确认`. ReportView displays all six fixed report sections and triggers Markdown/PDF downloads without rerunning the analysis.

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && npm test -- --run src/intelligence`

Run: `cd frontend && npm run build`

Expected: tests PASS and production build succeeds.

```bash
git add frontend/src/intelligence
git commit -m "feat(openscout): present evidence comparisons and reports"
```

### Task 17: Lock Stage A quality gates and portfolio evidence

**Files:**
- Create: `tests/integration/test_openscout_stage_a.py`
- Create: `evaluation/demo/questions.json`
- Create: `evaluation/results/stage-a-summary.md`
- Create: `docs/openscout/architecture.md`
- Create: `docs/openscout/limitations.md`
- Create: `README-openscout.md`
- Modify: `docs/openscout/decision-log.md`

**Interfaces:**
- Consumes: frozen snapshot, 80-question dataset, all Stage A APIs/UI.
- Produces: one repeatable five-minute demo, measured gate report, architecture/limitations docs, screenshots/video checklist, and release tag eligibility.

- [ ] **Step 1: Write the end-to-end acceptance test**

```python
def test_stage_a_demo_has_no_uncited_fact(openscout_client) -> None:
    for scenario in load_demo_scenarios("evaluation/demo/questions.json"):
        result = openscout_client.query(scenario)
        assert result["claims"]
        assert all(claim["evidence_ids"] for claim in result["claims"] if claim["kind"] in {"fact", "statistic"})
        assert all(e["source_url"].startswith("https://github.com/") for e in result["evidence"])
```

- [ ] **Step 2: Run integration test against the fixed snapshot**

Run: `KMP_DUPLICATE_LIB_OK=TRUE python -m pytest tests/integration/test_openscout_stage_a.py -q`

Expected: PASS for all five demo scenarios: trend discovery, representative Issues, Release relationship, three-product comparison, and report generation.

- [ ] **Step 3: Run the sealed holdout once and generate the gate report**

Run: `python evaluation/run_eval.py --config evaluation/configs/routed.yaml --split holdout --freeze`

Run: `python evaluation/summarize.py --release-gates --output evaluation/results/stage-a-summary.md`

Run: `python evaluation/check_regression.py --baseline evaluation/results/baseline.json --candidate evaluation/results/stage-a.json --max-drop 0.05`

Expected: report includes factual accuracy, citation accuracy, complex-question success, non-GraphRAG mean latency, token cost, and each threshold pass/fail; regression check exits 0 only when no tracked metric drops by more than five percentage points. Do not edit holdout questions afterward.

- [ ] **Step 4: Document only measured claims and capture proof**

`README-openscout.md` must disclose DocsGPT as the base, enumerate OpenScout-owned work, show the three experiments, link failure cases, state GitHub Issue sampling bias, and use measured values from the summary. Capture required screenshots or a short video for PR readiness.

- [ ] **Step 5: Run full validation and commit**

Run: `ruff check .`

Run: `KMP_DUPLICATE_LIB_OK=TRUE python -m pytest`

Run: `cd frontend && npm run lint`

Run: `cd frontend && npm run build`

Expected: all commands succeed. If a quality gate fails, preserve the measured result and remove the corresponding success claim rather than changing the threshold.

```bash
git add tests/integration evaluation docs/openscout README-openscout.md
git commit -m "docs(openscout): publish measured stage A portfolio evidence"
git tag openscout-stage-a
```

## Stage A Self-Review Record

- Spec coverage: ingestion limits, four source types, idempotency, partial success, hybrid/Rerank/route experiments, SQL analytics, selective GraphRAG, evidence rules, confidence, matrix, Markdown/PDF, coverage warnings, five-minute demo, and release gates are each assigned to a task.
- Deliberate exclusion: arbitrary repositories, incremental deletion confirmation, public share links, scheduled sync, and user research belong to the separate Stage B plan.
- Type consistency: `QueryResult`, `Evidence`, `Claim`, `Coverage`, and `SyncSummary` originate in Task 1; `RouteDecision` originates in Task 10; later tasks consume those names without renaming.
- Placeholder scan: implementation tasks contain exact files, interfaces, tests, commands, expected outcomes, and commit boundaries; no unfinished implementation markers remain.
