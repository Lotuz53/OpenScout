# OpenScout Intelligence Worker Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` (or the repository's equivalent execution workflow) to implement this plan task-by-task. Each task is independently verifiable and uses checkbox tracking.

**Goal:** Prevent large OpenScout Intelligence GitHub synchronizations from losing their Celery worker or leaving projects permanently in `syncing`, while preserving existing partial/failed semantics and keeping changes narrowly scoped.

**Architecture:** Make worker-local embedding execution explicit, add observable sync-stage progress and durable liveness heartbeats, reap only genuinely stale runs through the existing reconciliation path, deduplicate equivalent project creations at the database boundary, and add bounded vector-index batching only if focused profiling proves per-record embedding is a real bottleneck.

**Tech Stack:** Python, Flask, Celery, PostgreSQL, Redis, FAISS, FastEmbed, pytest, Ruff, Alembic.

**Spec:** `docs/superpowers/specs/2026-09-28-openscout-intelligence-worker-reliability-design.md`

## Global Constraints

- Read and follow `CONTRIBUTING.md` and `AGENTS.md`; never stage or modify the user-managed `AGENTS.md` change.
- Inspect only the synchronization task and direct dependencies needed for the current task. Do not scan the whole repository or perform unrelated refactors.
- Use red/green TDD: add a focused failing test first, run it to record the failure, implement the smallest fix, then run focused tests and Ruff.
- Do not unconditionally set `KMP_DUPLICATE_LIB_OK` in production. Add a macOS launcher change only if a worker reproduction proves an OpenMP/native crash.
- Do not change the `/api/events` SSE 429 reconnect behavior in this work.
- Do not log credentials, full private document bodies, embeddings, or tokens. Progress logs may include stable IDs, repository names, stage names, and counts only.
- Preserve existing GitHub source partial/failed semantics and existing sync-claim behavior.
- After each completed task: update this plan, commit only scoped changes (never `AGENTS.md` or `:memory:.ses`), and push the commit to the configured OpenScout GitHub remote.

## Direct File Map

- Worker and embedding boundary: `docsgpt/vectorstore/base.py`, `docsgpt/vectorstore/embeddings_delegated.py`, `docsgpt/vectorstore/embeddings_tasks.py`, `docsgpt/vectorstore/embeddings_local.py`.
- Intelligence execution: `docsgpt/intelligence/tasks.py`, `docsgpt/intelligence/sync_service.py`, `docsgpt/intelligence/indexing.py`.
- Persistence and recovery: `docsgpt/storage/db/repositories/intelligence.py`, `docsgpt/api/user/reconciliation.py`, `docsgpt/api/user/tasks.py`, Alembic migrations.
- API deduplication: `docsgpt/api/user/intelligence/routes.py`.
- Focused tests: `tests/vectorstore`, `tests/intelligence`, `tests/storage/db/repositories/test_intelligence.py`, `tests/api/user/intelligence/test_routes.py`, `tests/api/user/test_reconciliation.py`.

---

## Task 1: Make worker-local embeddings explicit

**Files:**

- Modify: `docsgpt/vectorstore/base.py`
- Modify: `docsgpt/vectorstore/embeddings_tasks.py`
- Test: `tests/vectorstore/test_base.py`
- Test: `tests/vectorstore/test_embeddings_delegated.py`
- Create: `tests/vectorstore/test_embeddings_tasks.py`

**Step 1 — Write the failing test.**

Add a test proving that a `local_embeddings_only()` context forces `get_embeddings()` to construct/use local embeddings even when `EMBEDDINGS_DELEGATE_TO_WORKER` is enabled. Add a task-level test proving `embed_texts` enters that scope before embedding.

**Step 2 — Run the focused test and confirm RED.**

Run:

`KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest tests/vectorstore/test_base.py tests/vectorstore/test_embeddings_delegated.py tests/vectorstore/test_embeddings_tasks.py -q`

Expected failure: the new scope is absent or the task still resolves through delegation.

**Step 3 — Implement the smallest fix.**

Add a context-local flag/context manager in `base.py`. Make `get_embeddings()` honor it, and wrap the existing `embed_texts` body in the scope without changing its public task signature or queue contract.

**Step 4 — Run GREEN validation.**

Run the focused pytest command above and:

`.venv/bin/ruff check docsgpt/vectorstore/base.py docsgpt/vectorstore/embeddings_tasks.py tests/vectorstore/test_base.py tests/vectorstore/test_embeddings_delegated.py tests/vectorstore/test_embeddings_tasks.py`

**Step 5 — Commit and push.**

Commit message: `fix(embeddings): force local execution inside worker`

---

## Task 2: Keep sync embedding in-process and add stage diagnostics

**Files:**

- Modify: `docsgpt/intelligence/tasks.py`
- Modify: `docsgpt/intelligence/sync_service.py`
- Test: `tests/intelligence/test_tasks.py`
- Test: `tests/intelligence/test_sync_service.py`

**Step 1 — Write the failing tests.**

Add tests proving both sync-task branches execute the service inside `local_embeddings_only()` and proving stage logs include safe stage names and counts without document bodies or credentials.

**Step 2 — Run RED.**

Run:

`KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest tests/intelligence/test_tasks.py tests/intelligence/test_sync_service.py -q`

Expected failure: the task does not establish the local scope and the new stage-log assertions are absent.

**Step 3 — Implement the smallest fix.**

Wrap both existing service-run branches in the local embedding scope, retain the existing exception handling and bare re-raise, and add bounded stage logs around claim, GitHub fetch, chunk/index progress, persistence, and issue/comment progress. Do not log content or secrets.

**Step 4 — Verify behavior and native-crash evidence.**

Run the focused tests and Ruff. Then run the existing minimal FAISS/FastEmbed child-process probe and, if the local services are available, one recommended macOS solo worker invocation while capturing its exit status and final log lines. Only if this proves SIGABRT/OpenMP conflict should a launcher/environment fix be added in this task.

**Step 5 — Commit and push.**

Commit message: `fix(intelligence): run sync embeddings locally and log stages`

---

## Task 3: Persist sync-run liveness and safely reap stale runs

**Files:**

- Create: `docsgpt/alembic/versions/0036_openscout_sync_liveness.py`
- Modify: `docsgpt/storage/db/repositories/intelligence.py`
- Test: `tests/storage/db/repositories/test_intelligence.py`

**Step 1 — Write the failing tests.**

Cover heartbeat updates, reaping an old `running` run with the exact diagnostic message `Worker exited before completing the sync.`, leaving fresh active runs untouched, and allowing a later claim after reaping.

**Step 2 — Run RED.**

Run:

`KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest tests/storage/db/repositories/test_intelligence.py -q`

Expected failure: there is no heartbeat field or stale-reaper method.

**Step 3 — Implement the migration and repository operations.**

Add nullable `last_heartbeat_at`, backfill it from `started_at`, and add the narrow status/time index. Add repository methods to heartbeat a run and atomically reap stale queued/running runs using row locking with `FOR UPDATE SKIP LOCKED`. Use `COALESCE(last_heartbeat_at, started_at, created_at)` for stale-age calculations. Make terminal updates write `finished_at` and preserve existing failure/count semantics.

**Step 4 — Run GREEN validation.**

Run the focused repository tests and Ruff for the migration/repository/test files.

**Step 5 — Commit and push.**

Commit message: `fix(intelligence): persist sync liveness and reap stale runs`

---

## Task 4: Integrate heartbeats with reconciliation recovery

**Files:**

- Modify: `docsgpt/intelligence/sync_service.py`
- Modify: `docsgpt/api/user/reconciliation.py`
- Test: `tests/intelligence/test_sync_service.py`
- Test: `tests/api/user/test_reconciliation.py`

**Step 1 — Write the failing tests.**

Cover heartbeat calls after claim, source/batch progress, and before terminal updates. Cover reconciliation marking reaped runs failed, moving a syncing project to failed only when no active run remains, preserving fresh long-running work, and being idempotent.

**Step 2 — Run RED.**

Run:

`KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest tests/intelligence/test_sync_service.py tests/api/user/test_reconciliation.py -q`

Expected failure: no intelligence stale sweep or heartbeat integration exists.

**Step 3 — Implement the smallest integration.**

Add a narrow sync-service heartbeat helper and call it at existing safe progress boundaries. Add an intelligence sweep to the existing reconciliation summary and sweep framework. Use the repository's atomic stale-reap result, update project status only when the project has no active run, and keep the exact worker-exit failure reason. Do not add a second scheduler.

**Step 4 — Run GREEN validation.**

Run the focused tests and Ruff for the modified files.

**Step 5 — Commit and push.**

Commit message: `fix(intelligence): recover projects after dead workers`

---

## Task 5: Deduplicate equivalent Intelligence projects

**Files:**

- Create: `docsgpt/alembic/versions/0037_openscout_project_dedupe.py`
- Modify: `docsgpt/storage/db/repositories/intelligence.py`
- Modify: `docsgpt/api/user/intelligence/routes.py`
- Test: `tests/storage/db/repositories/test_intelligence.py`
- Test: `tests/api/user/intelligence/test_routes.py`

**Step 1 — Write the failing tests.**

Add concurrent-creation coverage proving equivalent user/repository/window requests return one canonical project, while a different time window remains valid. Assert the API returns the existing project with a clear non-creation response and that duplicate sync claims still dispatch at most one task.

**Step 2 — Run RED.**

Run:

`KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest tests/storage/db/repositories/test_intelligence.py tests/api/user/intelligence/test_routes.py -q`

Expected failure: creation always inserts and the API always returns 201.

**Step 3 — Implement database-backed deduplication.**

Add nullable `project_dedupe_key`. Backfill only the earliest existing row per normalized user/repository/window group and leave older duplicate rows NULL so existing data is not deleted or silently reassigned. Add a partial unique index for non-null keys. Make creation use a conflict-safe insert and return a typed result containing the project and `created` flag. Return 201 for a new project and 200 for an existing canonical one, preserving the current preflight and sync-claim behavior.

**Step 4 — Run GREEN validation.**

Run the focused tests and Ruff. Verify the migration is compatible with the current duplicate rows before applying it.

**Step 5 — Commit and push.**

Commit message: `fix(intelligence): deduplicate equivalent projects`

---

## Task 6: Prove and, if necessary, add bounded index batching

**Files:**

- Modify: `docsgpt/core/settings.py`
- Modify: `docsgpt/intelligence/indexing.py`
- Test: `tests/intelligence/test_indexing.py`
- Test: `tests/intelligence/test_incremental_sync.py`

**Step 1 — Add the characterization test before changing behavior.**

With a configured batch size of 2 and three changed records, assert the current `replace_records()` call count and capture record/chunk ordering. Use the test result to decide whether per-record embedding is actually present and material.

**Step 2 — Run the focused test and record the proof.**

Run:

`KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest tests/intelligence/test_indexing.py tests/intelligence/test_incremental_sync.py -q`

If the existing behavior does not demonstrate the suspected small-batch problem, do not add batching; retain only the characterization/profiling evidence and skip the production change.

**Step 3 — If proof warrants it, implement the smallest bounded batching change.**

Add `INTELLIGENCE_INDEX_BATCH_SIZE` with default 32 and maximum 512. Flush batches before the bound, split oversized records safely, retain stable source/record metadata, and wrap failures with the affected stable IDs. Keep unchanged-record short-circuiting intact and emit batch progress counts. Never accumulate the whole repository in memory.

**Step 4 — Run GREEN validation.**

Run focused indexing/incremental tests and Ruff. Confirm batch boundaries, failure attribution, result counts, and zero re-embedding for unchanged records.

**Step 5 — Commit and push.**

Commit message: `perf(intelligence): bound vector indexing batches` (only if the proof required a production change).

---

## Task 7: Safely recover the current database and perform operational acceptance

**Files:**

- Modify: this plan only, unless a directly evidenced operational defect requires a scoped code change.

**Step 1 — Run focused regression validation.**

Run the complete set of relevant vectorstore, intelligence, repository, reconciliation, and route tests once, plus Ruff for all modified files. Do not rerun unrelated full-project suites.

**Step 2 — Apply and inspect migrations safely.**

Use the normal development migration command if the local environment is configured. Inspect the two known Dify projects and their sync runs before changing state; never delete projects or sync records.

**Step 3 — Reap only the confirmed stale runs.**

Invoke the repository/reconciliation recovery for the explicitly observed old Dify runs, verify they become failed with the worker-exit reason, verify projects leave `syncing`, and verify no records were deleted.

**Step 4 — Re-trigger exactly one canonical project.**

Use the existing project that is retained as canonical (prefer the row with the existing usable index when it is the same user/repository/window), dispatch one sync, and monitor safe stage logs plus database status until it reaches `ready`, `partial`, or a diagnostic `failed` terminal state. Do not create another duplicate.

**Step 5 — Verify idempotency and unchanged-content behavior.**

Repeat the equivalent create/sync requests and confirm no duplicate project or concurrent task is created. On an unchanged follow-up sync, confirm records are not re-embedded.

**Step 6 — Commit and push the completed plan state.**

Commit message: `chore(intelligence): validate worker recovery rollout`

Final report must include root cause evidence (including worker exit status if reproduced), modified files and purposes, tests/results, macOS startup impact, migration/deployment impact, unresolved native-crash risk, and a reminder to attach a PR screenshot or recording.

---

## Completion Checklist

- [ ] Task 1 complete and pushed.
- [ ] Task 2 complete and pushed.
- [ ] Task 3 complete and pushed.
- [ ] Task 4 complete and pushed.
- [ ] Task 5 complete and pushed.
- [ ] Task 6 complete and pushed or explicitly skipped with profiling evidence.
- [ ] Task 7 complete and pushed.
