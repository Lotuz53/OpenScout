# OpenScout Initial Sync FAISS Lifecycle Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the first OpenScout GitHub synchronization create and persist a missing FAISS index, preserve strict corruption checks, and always leave failed local synchronizations in terminal database states.

**Architecture:** `FaissStore` will expose an explicit `create_if_missing=False` opt-in. Only the OpenScout `SyncService` production factory will enable it for FAISS; a directory with any existing index artifact will still use strict loading. FAISS mutations will persist the three index artifacts, while `SyncService` will convert local persistence/indexing exceptions into a failed run/project summary, attempt both terminal writes independently, and re-raise the original exception.

**Tech Stack:** Python 3, FAISS CPU, Pydantic contracts, SQLAlchemy/Postgres repositories, Celery, pytest, Ruff, React/TypeScript/Vitest.

**Spec:** `docs/superpowers/specs/2026-09-17-openscout-initial-sync-faiss-repair-design.md`

## Global Constraints

- Keep `FaissStore`'s default missing-index behavior strict; only OpenScout's FAISS sync path may pass `create_if_missing=True`.
- Treat `index.faiss` plus either supported sidecar (`index.json` or legacy `index.pkl`) as an existing index; if an artifact is present but the required companion files cannot be loaded, raise rather than initialize over it.
- Persist `index.faiss`, `index.json`, and `index.pkl` after successful FAISS additions and deletions; do not change other vector-store interfaces or retry policy.
- Local index/database/persistence errors must write `sync_runs.status=failed` and `intelligence_projects.status=failed` when possible, preserve a diagnostic `sync`/`local` failure, and re-raise the original exception.
- GitHub collection failures keep the existing source-level `partial`/`failed` behavior.
- Read `CONTRIBUTING.md` and follow the repository `AGENTS.md`; keep changes narrow and use red/green TDD.
- Use the existing `.venv`, Postgres, and Redis when available; do not recreate or stop development services.
- Run focused backend tests and changed-file Ruff checks; run the relevant frontend lint/test/build checks only because the failure label is changed.
- Do not stage or modify the existing unrelated `AGENTS.md` worktree change.
- After every code task, commit only that task's files and push the commit to both `origin/feature/openscout-design` and `origin/main`.

## File Map

- `docsgpt/vectorstore/faiss.py`: add the explicit missing-index construction mode and persist successful `add_texts()` mutations.
- `tests/vectorstore/test_faiss.py`: cover first creation, reopen, direct-add persistence, incremental append, and strict partial/corrupt artifact handling.
- `tests/intelligence/test_indexing.py`: exercise `IntelligenceIndexer.replace_records()` and `delete_records()` against a real persisted FAISS store.
- `docsgpt/intelligence/schemas.py`: allow a synchronization-process failure source and the `local` failure category without changing source-type counts.
- `docsgpt/intelligence/sync_service.py`: pass the FAISS creation flag and finalize local failures independently for the run and project before re-raising.
- `tests/intelligence/test_sync_service.py`: cover the FAISS factory flag and local finalization attempts.
- `tests/intelligence/test_incremental_sync.py`: use a stateful repository double to prove failed runs/projects leave `running`/`syncing`.
- `tests/storage/db/repositories/test_intelligence.py`: verify the database repository serializes a local failed summary as a terminal run.
- `frontend/src/intelligence/types.ts`: include `local` in the typed failure categories.
- `frontend/src/intelligence/SyncStatus.tsx`: label the `sync` failure source and `local` category for users.
- `frontend/src/intelligence/SyncStatus.test.tsx`: verify the local failure label is rendered.
- `docsgpt/intelligence/tasks.py`: inspect and test the existing propagation path; do not change it unless a focused regression proves it is required.

---

### Task 1: Add an explicit missing-index mode to FAISS

**Files:**
- Modify: `docsgpt/vectorstore/faiss.py:84-128`
- Test: `tests/vectorstore/test_faiss.py:45-70,150-180`

**Interfaces:**
- Consumes: existing `StorageCreator` storage and `FAISS_INDEX`/sidecar constants.
- Produces: `FaissStore(source_id, embeddings_key, create_if_missing=False)`; an instance created with this flag and no index artifacts starts with `index=None`, empty documents, and an empty row map.

- [ ] **Step 1: Write the failing tests**

Extend the `make_store` fixture with a `create_if_missing=False` keyword and pass it to `FaissStore`. Add these tests beside `test_missing_index_raises`:

```python
def test_missing_index_can_be_initialized(self, make_store):
    store = make_store(source_id="new-project", create_if_missing=True)

    assert store.index is None
    assert store.get_chunks() == []


def test_partial_index_is_not_treated_as_missing(self, make_store, storage):
    storage.save_file(io.BytesIO(b"not a complete index"), "indexes/corrupt/index.faiss")

    with pytest.raises(Exception, match="Error loading FAISS index"):
        make_store(source_id="corrupt", create_if_missing=True)
```

Add `import io` with the existing test imports. Keep `test_missing_index_raises` unchanged to prove the default remains strict.

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q \
  tests/vectorstore/test_faiss.py::TestFaissPersistence::test_missing_index_can_be_initialized \
  tests/vectorstore/test_faiss.py::TestFaissPersistence::test_partial_index_is_not_treated_as_missing
```

Expected: FAIL because `FaissStore` does not accept `create_if_missing` yet.

- [ ] **Step 3: Implement the smallest construction change**

Add the keyword to the constructor after the existing optional flags, document that it only permits an entirely absent storage directory, and distinguish “no artifact exists” from “an artifact exists but cannot load”:

```python
def __init__(
    self,
    source_id: str,
    embeddings_key: str,
    docs_init=None,
    ids=None,
    batch_size=None,
    skip_dimension_check: bool = False,
    create_if_missing: bool = False,
):
    if docs_init:
        self._build_from_documents(docs_init, ids=ids, batch_size=batch_size)
    elif create_if_missing and not self._has_index_artifacts():
        pass
    else:
        self._load_from_storage()

def _has_index_artifacts(self) -> bool:
    """Return whether any FAISS index or sidecar file already exists."""
    return any(
        self.storage.file_exists(f"{self.path}/{name}")
        for name in (FAISS_INDEX, JSON_SIDECAR, PICKLE_SIDECAR)
    )
```

Do not weaken `_load_from_storage()`: a present FAISS file still requires a readable JSON or legacy pickle sidecar, and FAISS/sidecar/embedding dimension errors must continue through the existing error path.

- [ ] **Step 4: Run the focused FAISS tests to verify they pass**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q tests/vectorstore/test_faiss.py
```

Expected: PASS, including the existing default missing-index and corrupt/dimension checks.

- [ ] **Step 5: Commit and push the task**

```bash
git add docsgpt/vectorstore/faiss.py tests/vectorstore/test_faiss.py
git commit -m "fix(faiss): allow explicit empty index initialization"
git push origin HEAD:feature/openscout-design
git push origin HEAD:main
```

### Task 2: Persist every direct FAISS addition and prove reopen/incremental append

**Files:**
- Modify: `docsgpt/vectorstore/faiss.py:255-272`
- Test: `tests/vectorstore/test_faiss.py:105-125,150-180`

**Interfaces:**
- Consumes: Task 1's `create_if_missing` mode and existing `_save_to_storage()` implementation.
- Produces: successful `FaissStore.add_texts()` calls write all three storage artifacts before returning; failed saves propagate to the caller.

- [ ] **Step 1: Write the failing persistence tests**

Add tests that reopen a fresh instance after a direct append and that append to an already saved index survives a second reopen:

```python
def test_add_texts_persists_for_reopen(self, make_store, storage):
    store = make_store(source_id="append-project", create_if_missing=True)
    store.add_texts(["Paris is the capital of France."], [{"source": "README.md"}])

    reopened = make_store(source_id="append-project")

    assert reopened.index.ntotal == 1
    assert reopened.get_chunks()[0]["metadata"]["source"] == "README.md"


def test_second_open_reuses_existing_index_for_incremental_append(self, make_store):
    store = make_store(source_id="incremental-project", create_if_missing=True)
    store.add_texts(["Postgres is a database."], [{"source": "db.md"}])

    reopened = make_store(source_id="incremental-project")
    reopened.add_texts(["Celery runs tasks."], [{"source": "queue.md"}])

    final_store = make_store(source_id="incremental-project")
    assert final_store.index.ntotal == 2
    assert {chunk["metadata"]["source"] for chunk in final_store.get_chunks()} == {
        "db.md",
        "queue.md",
    }
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q \
  tests/vectorstore/test_faiss.py::TestFaissPersistence::test_add_texts_persists_for_reopen \
  tests/vectorstore/test_faiss.py::TestFaissPersistence::test_second_open_reuses_existing_index_for_incremental_append
```

Expected: FAIL because `add_texts()` currently mutates only memory and does not write storage.

- [ ] **Step 3: Make `add_texts()` persist after the append**

Keep embedding and dimension creation unchanged, then save only after `_append()` succeeds:

```python
        if self.index is None:
            faiss = _dependable_faiss_import()
            self.index = faiss.IndexFlatL2(len(vectors[0]))
        ids = self._append(texts, metadatas, vectors, ids)
        self._save_to_storage()
        return ids
```

Do not catch `_save_to_storage()` exceptions. Existing `add_chunk()`/`delete_chunk()` may save again for compatibility; leave their public behavior and error propagation unchanged unless the focused tests demonstrate a duplicate-save bug.

- [ ] **Step 4: Run all FAISS tests**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q tests/vectorstore/test_faiss.py
```

Expected: PASS, including the existing JSON/legacy-pickle reload tests and embedding dimension tests.

- [ ] **Step 5: Commit and push the task**

```bash
git add docsgpt/vectorstore/faiss.py tests/vectorstore/test_faiss.py
git commit -m "fix(faiss): persist direct text additions"
git push origin HEAD:feature/openscout-design
git push origin HEAD:main
```

### Task 3: Cover persisted record replacement and deletion through the real indexer

**Files:**
- Test: `tests/intelligence/test_indexing.py`
- Inspect only: `docsgpt/intelligence/indexing.py:85-145`

**Interfaces:**
- Consumes: Task 2's persisted `add_texts()` and existing FAISS `delete_chunk()` persistence.
- Produces: a regression test proving stable OpenScout sources can be replaced, reopened, and deleted without rebuilding unrelated records; no production indexer API change is expected.

- [ ] **Step 1: Write the failing end-to-end indexer test**

Add `import pytest`, `from types import SimpleNamespace`, `from docsgpt.storage.local import LocalStorage`, and `from docsgpt.vectorstore import faiss as indexing_faiss` to the existing imports. Add a real-FAISS fixture in `tests/intelligence/test_indexing.py` using deterministic 3D vectors and patches for `BaseVectorStore._get_embeddings`, `StorageCreator.get_storage`, and `faiss.settings`. The test should create an empty store with `create_if_missing=True`, run a first `IntelligenceIndexer.replace_records()`, reopen it with the default constructor, replace the same `issue:42` with changed body text, reopen again, then delete the record and reopen once more:

```python
@pytest.fixture
def real_faiss_store(tmp_path, monkeypatch):
    class Embeddings:
        dimension = 3

        def embed_documents(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

    storage = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(
        indexing_faiss,
        "settings",
        SimpleNamespace(EMBEDDINGS_NAME="test_model"),
    )
    monkeypatch.setattr(
        indexing_faiss.BaseVectorStore,
        "_get_embeddings",
        lambda self, name, key: Embeddings(),
    )
    monkeypatch.setattr(indexing_faiss.StorageCreator, "get_storage", lambda: storage)

    def build(create_if_missing=False):
        return indexing_faiss.FaissStore(
            PROJECT_ID,
            "key",
            create_if_missing=create_if_missing,
        )

    store = build(create_if_missing=True)
    store.reopen = build
    return store


def test_replace_and_delete_records_survive_reopen(real_faiss_store):
    first = IntelligenceIndexer(MagicMock(), real_faiss_store)
    first.replace_records(PROJECT_ID, [issue_record(body="first body")])

    second_store = real_faiss_store.reopen()
    second = IntelligenceIndexer(MagicMock(), second_store)
    second.replace_records(PROJECT_ID, [issue_record(body="updated body")])

    replaced = real_faiss_store.reopen()
    assert [chunk["text"] for chunk in replaced.get_chunks()] == ["updated body"]

    second.delete_records(PROJECT_ID, ["issue:42"])
    assert real_faiss_store.reopen().get_chunks() == []
```

The fixture may expose `reopen()` as a small closure returning a new `FaissStore` with the same patched storage and `source_id`; keep the helper test-local so no production fixture API is introduced.

- [ ] **Step 2: Run the indexer regression test against the completed FAISS behavior**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q tests/intelligence/test_indexing.py::test_replace_and_delete_records_survive_reopen
```

Expected: PASS because Task 2's persistence implementation is already present; this task verifies the higher-level replacement and deletion path that was not covered by the direct store tests.

- [ ] **Step 3: Confirm no unrelated indexer change is needed**

Read the existing `IntelligenceIndexer._delete_existing()` path. It uses the inherited `delete_chunks_by_source_path()` fallback, which calls FAISS `delete_chunk()` and therefore persists the deletion. Do not add a second vector-store-wide save abstraction or alter other backends solely to make this test pass.

- [ ] **Step 4: Run all indexing tests**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q tests/intelligence/test_indexing.py
```

Expected: PASS, including existing mock-based chunking and metadata tests.

- [ ] **Step 5: Commit and push the task**

```bash
git add tests/intelligence/test_indexing.py
git commit -m "test(openscout): cover persisted record replacement"
git push origin HEAD:feature/openscout-design
git push origin HEAD:main
```

### Task 4: Add a diagnostic local-sync failure contract and FAISS factory coverage

**Files:**
- Modify: `docsgpt/intelligence/schemas.py:128-136`
- Modify: `docsgpt/intelligence/sync_service.py:626-645`
- Modify: `frontend/src/intelligence/types.ts:15-20`
- Modify: `frontend/src/intelligence/SyncStatus.tsx:44-68,108-125`
- Test: `tests/intelligence/test_sync_service.py`
- Test: `frontend/src/intelligence/SyncStatus.test.tsx`

**Interfaces:**
- Consumes: existing `SourceType` and `VectorCreator.create_vectorstore()` call.
- Produces: `SyncFailure.source_type` accepts normal `SourceType` values or the literal `"sync"`; `SyncFailure.category` accepts `"local"`; `_get_indexer()` passes `create_if_missing=True` only when `settings.VECTOR_STORE.lower() == "faiss"`.

- [ ] **Step 1: Add failing contract and factory tests**

In `tests/intelligence/test_sync_service.py`, patch the lazy `VectorCreator` and settings, then assert the exact FAISS constructor call:

```python
def test_production_faiss_indexer_allows_a_missing_index(monkeypatch):
    repository = MagicMock()
    service = SyncService(
        repository=None,
        github=MagicMock(),
        indexer=None,
        session_factory=MagicMock(),
    )
    vector_store = MagicMock()
    creator = MagicMock(create_vectorstore=MagicMock(return_value=vector_store))
    monkeypatch.setattr("docsgpt.vectorstore.vector_creator.VectorCreator", creator)
    monkeypatch.setattr("docsgpt.core.settings.settings.VECTOR_STORE", "faiss", raising=False)
    monkeypatch.setattr("docsgpt.core.settings.settings.EMBEDDINGS_KEY", "embedding-key", raising=False)

    service._get_indexer(PROJECT_ID, repository)

    creator.create_vectorstore.assert_called_once_with(
        "faiss",
        source_id=PROJECT_ID,
        embeddings_key="embedding-key",
        create_if_missing=True,
    )
```

Add a Pydantic construction assertion for `SyncFailure(source_type="sync", category="local", retryable=False, message="local index failed")`. Add a frontend test case that renders a failed run containing that failure and expects `同步流程 · 本地同步失败`.

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q tests/intelligence/test_sync_service.py::test_production_faiss_indexer_allows_a_missing_index
(cd frontend && npm run test -- --run src/intelligence/SyncStatus.test.tsx)
```

Expected: backend fails because the factory does not pass the new keyword; frontend fails because the new category/source labels are absent.

- [ ] **Step 3: Implement the narrow contract and labels**

In `schemas.py`, define a local failure source alias and extend only the failure contract:

```python
SyncFailureSource = SourceType | Literal["sync"]

class SyncFailure(IntelligenceModel):
    source_type: SyncFailureSource
    category: Literal[
        "rate_limit", "auth", "not_found", "network", "invalid_payload", "local"
    ]
    retryable: bool
    message: str
```

In `_get_indexer()`, pass the keyword only for FAISS:

```python
vector_store_kwargs = {
    "source_id": project_id,
    "embeddings_key": settings.EMBEDDINGS_KEY,
}
if str(settings.VECTOR_STORE).lower() == "faiss":
    vector_store_kwargs["create_if_missing"] = True
vector_store = VectorCreator.create_vectorstore(settings.VECTOR_STORE, **vector_store_kwargs)
```

Add `local` to the TypeScript union, add `local: '本地同步失败'` to `FAILURE_LABELS`, and handle `source_type === 'sync'` as `同步流程` without changing the four normal source labels.

- [ ] **Step 4: Run the focused backend/frontend tests**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q tests/intelligence/test_sync_service.py
cd frontend && npm run test -- --run src/intelligence/SyncStatus.test.tsx
```

Expected: PASS, with existing GitHub failure-label tests unchanged.

- [ ] **Step 5: Commit and push the task**

```bash
git add docsgpt/intelligence/schemas.py docsgpt/intelligence/sync_service.py \
  frontend/src/intelligence/types.ts frontend/src/intelligence/SyncStatus.tsx \
  tests/intelligence/test_sync_service.py frontend/src/intelligence/SyncStatus.test.tsx
git commit -m "fix(openscout): describe local sync failures"
git push origin HEAD:feature/openscout-design
git push origin HEAD:main
```

### Task 5: Finalize local sync failures and preserve the original exception

**Files:**
- Modify: `docsgpt/intelligence/sync_service.py:134-336,650-710,850-880`
- Modify: `tests/intelligence/test_incremental_sync.py:35-150`
- Modify: `tests/intelligence/test_sync_service.py`
- Test: `tests/storage/db/repositories/test_intelligence.py`
- Inspect only: `docsgpt/intelligence/tasks.py:45-68`

**Interfaces:**
- Consumes: Task 4's `SyncFailureSource`, `local` category, and FAISS creation mode.
- Produces: after a run has been started, any local indexing/database/persistence exception calls the existing `finish_sync_run(run_id, failed_summary)` and `set_project_status(project_id, user_id, "failed")` independently, logs terminalization errors, then raises the original exception unchanged.

- [ ] **Step 1: Extend the in-memory repository test double and write the failing lifecycle test**

Record finished summaries in `MemoryRepository.finish_sync_run()` and add this test:

```python
def test_local_index_failure_finishes_run_and_project_as_failed():
    repository = MemoryRepository()
    github = FakeGitHub([release_payload()])
    indexer = MagicMock()
    indexer.replace_records.side_effect = RuntimeError("FAISS save failed")

    with pytest.raises(RuntimeError, match="FAISS save failed"):
        make_service(repository, github, indexer).run_incremental(PROJECT_ID, "u1")

    assert repository.project["status"] == "failed"
    failed_summary = repository.finished_runs["sync-1"]
    assert failed_summary.status == "failed"
    assert failed_summary.failures[-1].source_type == "sync"
    assert failed_summary.failures[-1].category == "local"
    assert "FAISS save failed" in failed_summary.failures[-1].message
```

Add a second test with `finish_sync_run` raising a terminalization error and assert `set_project_status(PROJECT_ID, "u1", "failed")` is still attempted. Add a repository integration test that sends `SyncSummary(status="failed", counts={}, failures=[local_failure], coverage=coverage)` through `finish_sync_run()` and asserts the returned row has `status == "failed"` and a JSON failure with `category == "local"`.

- [ ] **Step 2: Run the new lifecycle tests to verify they fail**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q \
  tests/intelligence/test_incremental_sync.py::test_local_index_failure_finishes_run_and_project_as_failed \
  tests/storage/db/repositories/test_intelligence.py -k local
```

Expected: FAIL because the current service lets the exception escape before finishing the run or changing the project to `failed`.

- [ ] **Step 3: Add the smallest local-failure finalization path**

Define a nested `run_started_sync() -> IncrementalSyncSummary` closure immediately after the counters are initialized. At the top of the closure declare `nonlocal changed_records, unchanged_records, embedded_chunks, capped`, then move the current source collection, persistence, reconciliation, normal summary finalization, and return body into that closure without changing its order. The closure closes over the mutable `counts`, `failures`, and `observed_dates` values, while the outer function retains the run id and local-failure counters. Add this helper with the exact signature below; it sets `status="failed"`, `cursor=None`, `deactivated_record_ids=[]`, and `coverage.last_synced_at=None` while preserving counts and observed date bounds:

```python
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
```

On exception, build that failed summary from the counts and coverage accumulated so far:

```python
try:
    self._set_project_status(project_id, user_id, "syncing")
    return run_started_sync()
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
        logger.exception("Could not mark intelligence project %s as failed", project_id)
    raise
```

The helper must set `status="failed"`, `cursor=None`, `coverage.last_synced_at=None`, preserve the accumulated counts/date bounds, and not invoke source-level `_to_sync_failure()` for this exception. Keep `tasks.py` unchanged: its existing task wrapper must receive the same exception so Celery does not report a false success. If extracting `_run_started_sync()` is needed to avoid a broad behavioral rewrite, move the current post-start body mechanically and keep its ordering and source semantics unchanged.

- [ ] **Step 4: Run all focused synchronization and repository tests**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q \
  tests/intelligence/test_sync_service.py \
  tests/intelligence/test_incremental_sync.py \
  tests/intelligence/test_tasks.py \
  tests/storage/db/repositories/test_intelligence.py -k 'sync or local or project_status'
```

Expected: PASS. The existing GitHub rate-limit test must still return `partial`, and the task serialization/retry-policy tests must remain unchanged.

- [ ] **Step 5: Commit and push the task**

```bash
git add docsgpt/intelligence/sync_service.py tests/intelligence/test_incremental_sync.py \
  tests/intelligence/test_sync_service.py tests/storage/db/repositories/test_intelligence.py
git commit -m "fix(openscout): finalize failed local synchronizations"
git push origin HEAD:feature/openscout-design
git push origin HEAD:main
```

### Task 6: Run final focused validation and safely recover the stuck project

**Files:**
- Inspect only: `docsgpt/intelligence/tasks.py`, `docsgpt/storage/db/repositories/intelligence.py`, `docsgpt/api/user/intelligence/routes.py`
- Modify only if a focused regression exposes a task-specific issue; otherwise no source change is expected.

**Interfaces:**
- Consumes: all previous tasks and the existing `db_readonly`/`db_session` and Celery task entry points.
- Produces: focused validation evidence and a real terminal state for `jinchenma94/bazi-skill`, followed by a new sync attempt with a unique idempotency key.

- [ ] **Step 1: Run backend Ruff and the focused regression set**

Run:

```bash
.venv/bin/ruff check \
  docsgpt/vectorstore/faiss.py docsgpt/intelligence/indexing.py \
  docsgpt/intelligence/schemas.py docsgpt/intelligence/sync_service.py \
  docsgpt/intelligence/tasks.py \
  tests/vectorstore/test_faiss.py tests/intelligence/test_indexing.py \
  tests/intelligence/test_sync_service.py tests/intelligence/test_incremental_sync.py \
  tests/intelligence/test_tasks.py tests/storage/db/repositories/test_intelligence.py
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest -q \
  tests/vectorstore/test_faiss.py tests/intelligence/test_indexing.py \
  tests/intelligence/test_sync_service.py tests/intelligence/test_incremental_sync.py \
  tests/intelligence/test_tasks.py tests/storage/db/repositories/test_intelligence.py
```

Expected: Ruff passes and all selected FAISS/OpenScout synchronization tests pass. Do not run the entire backend suite unless one of these focused tests reveals a cross-module regression that requires it.

- [ ] **Step 2: Run the relevant frontend checks once**

Run:

```bash
(cd frontend && npm run test -- --run src/intelligence/SyncStatus.test.tsx)
(cd frontend && npm run lint)
(cd frontend && npm run build)
```

Expected: the local failure label test, ESLint, and the production frontend build pass.

- [ ] **Step 3: Inspect the currently stuck database state without writing**

Using the existing `.env`/settings and `.venv`, query only the target repository and active states:

```python
from sqlalchemy import text
from docsgpt.storage.db.session import db_readonly

with db_readonly() as conn:
    rows = conn.execute(text("""
        SELECT p.id::text AS project_id,
               p.user_id,
               p.status AS project_status,
               r.id::text AS run_id,
               r.status AS run_status
        FROM intelligence_projects AS p
        LEFT JOIN intelligence_sync_runs AS r
          ON r.project_id = p.id
         AND r.status = 'running'
        WHERE p.repository = 'jinchenma94/bazi-skill'
          AND (p.status = 'syncing' OR r.id IS NOT NULL)
        ORDER BY r.started_at DESC NULLS LAST
    """)).mappings().all()
    print([dict(row) for row in rows])
```

Confirm the row still has the historical `syncing`/`running` states before mutating anything. If there is no such row, skip cleanup and use the current project status as the baseline. If more than one active run is returned, stop and report the ambiguity instead of guessing.

- [ ] **Step 4: Mark only the confirmed historical run/project as failed**

For the single confirmed target row, open one `db_session()` transaction, re-read the project and run, and abort if either status changed. Build a `SyncSummary` with `status="failed"`, the project's window dates, zero counts, and:

```python
SyncFailure(
    source_type="sync",
    category="local",
    retryable=False,
    message="历史首次同步因 FAISS 索引不存在而失败，已由修复流程收尾。",
)
```

Call `IntelligenceRepository.finish_sync_run(run_id, summary)` and `set_project_status(project_id, user_id, "failed")` in that transaction. Do not delete records, indexes, or other projects. Re-read the target project/run after commit and verify neither is still `syncing`/`running`.

- [ ] **Step 5: Retrigger the target sync with a unique repair idempotency key**

Use the existing Celery task entry point and the confirmed `project_id`/`user_id`:

```python
from uuid import uuid4
from docsgpt.intelligence.tasks import sync_intelligence_project

result = sync_intelligence_project.apply_async(
    kwargs={
        "project_id": project_id,
        "user_id": user_id,
        "idempotency_key": f"openscout-faiss-repair:{project_id}:{uuid4()}",
    },
    queue="docsgpt",
)
print(result.id)
```

Poll the target project's latest sync run through the existing repository/read API until it reaches `complete`, `partial`, or `failed`. Confirm the project reaches `ready`, `partial`, or `failed`, confirm the failure message if it fails, and verify it does not remain `syncing` while the run remains `running`. If the worker is unavailable, report that external blocker rather than marking the new run successful.

- [ ] **Step 6: Record final status and push any task-specific fix**

Report the exact modified files, focused test/Ruff/frontend results, target project status, latest run status, and whether records/index artifacts were created. If Step 1–5 required no additional source edits, do not create a no-op commit; otherwise commit the narrowly scoped fix and push it to both `origin/feature/openscout-design` and `origin/main`.

## Plan Self-Review

- Spec coverage: Task 1 covers missing-index creation and strict artifact handling; Task 2 covers direct-add persistence and reopen; Task 3 covers replacement/deletion and second-instance incremental behavior; Task 4 covers the FAISS factory flag and diagnostic contract/UI; Task 5 covers failed run/project terminalization, best-effort cleanup, and original exception propagation; Task 6 covers focused validation and safe database recovery/retrigger.
- Reserved-word check: the plan contains no unresolved planning markers or incomplete implementation instructions.
- Type consistency: `SyncFailureSource` is introduced before `SyncFailure` uses it; `create_if_missing` is introduced in Task 1 before Task 4 passes it; Task 5 consumes the `sync`/`local` contract introduced in Task 4; all task test names and commands reference the files and symbols defined in their own task.
- Scope check: no GitHub collector, normalizer, graph algorithm, unrelated vector store, Celery retry policy, or product status vocabulary is changed.
