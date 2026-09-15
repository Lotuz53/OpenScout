# OpenScout AI Stage B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the validated Stage A portfolio build into a promotable product that accepts arbitrary public GitHub repositories, synchronizes incrementally, shares safe read-only reports, and records real user-task evidence.

**Architecture:** Reuse the Stage A project, record, indexing, query, and report contracts. Add a repository preflight boundary before project creation, durable per-object synchronization cursors and deletion audits, existing Celery/RedBeat scheduling, and a public report projection that never exposes owner or internal trace data. Keep user research artifacts outside runtime tables and aggregate only consented, anonymized observations.

**Tech Stack:** Stage A stack plus Celery RedBeat, cryptographically random share tokens, pytest/Vitest, and Markdown research records.

**Spec:** `docs/superpowers/specs/2026-09-14-openscout-ai-design.md`

## Global Constraints

- Stage B starts only after Stage A acceptance tests and measured evaluation results exist.
- Accept public GitHub repositories only; private repository support and expanded OAuth scopes are out of scope.
- Unchanged `content_hash` records must not be re-indexed.
- A missing external object remains active after the first miss and leaves the active index only after two consecutive successful syncs confirm absence.
- Partial syncs commit successful batches and expose retryable failures.
- Public report responses expose no `user_id`, GitHub token, provider credentials, private storage path, or internal retrieval trace.
- Sharing is read-only, uses an unguessable token, and can be revoked.
- Recruit 5 to 10 target users; report measured task outcomes and limitations without inventing demand.

---

### Task 1: Preflight and create an arbitrary public repository project

**Files:**
- Create: `docsgpt/intelligence/preflight.py`
- Modify: `docsgpt/intelligence/github_client.py`
- Modify: `docsgpt/api/user/intelligence/routes.py`
- Create: `tests/intelligence/test_preflight.py`
- Modify: `tests/api/user/intelligence/test_routes.py`
- Create: `frontend/src/intelligence/RepositorySetup.tsx`
- Create: `frontend/src/intelligence/RepositorySetup.test.tsx`
- Modify: `frontend/src/intelligence/intelligenceService.ts`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GitHubLoader.normalize_repo(repo_url: str) -> str`, Stage A project repository, and authenticated `/api/intelligence` namespace.
- Produces: `RepositoryPreflight(repository, default_branch, archived, estimated_counts, warnings)`, `POST /api/intelligence/preflight`, and setup-to-sync UI flow.

- [ ] **Step 1: Write preflight classification tests**

```python
@pytest.mark.parametrize("status,private,expected", [
    (404, False, "not_found"), (200, True, "private_not_supported"),
    (200, False, None),
])
def test_preflight_classifies_repository(status, private, expected, github) -> None:
    github.repository_metadata.return_value = {"status": status, "private": private, "archived": False}
    result = RepositoryPreflightService(github).check("https://github.com/o/r")
    assert result.error_code == expected
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_preflight.py tests/api/user/intelligence/test_routes.py -q`

Expected: FAIL with missing preflight service/route.

- [ ] **Step 3: Implement bounded metadata preflight**

Normalize to `owner/name`, fetch repository metadata and count estimates without downloading content, reject malformed/non-GitHub/private repositories, and return warnings for archived, empty, or over-limit repositories. A warning does not bypass Stage A caps.

- [ ] **Step 4: Implement setup UI and creation handoff**

The form collects URL and date window, displays canonical repository, estimated Issues/Releases/docs, and cap warnings, then calls the existing create and sync endpoints. Disable creation on error; require explicit acknowledgement for archived or capped repositories.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/intelligence/test_preflight.py tests/api/user/intelligence/test_routes.py -q`

Run: `cd frontend && npm test -- --run src/intelligence/RepositorySetup.test.tsx`

Expected: valid public repositories create a project; invalid/private repositories do not.

```bash
git add docsgpt/intelligence/preflight.py docsgpt/intelligence/github_client.py docsgpt/api/user/intelligence/routes.py tests frontend/src/intelligence frontend/src/App.tsx
git commit -m "feat(openscout): preflight public GitHub repositories"
```

### Task 2: Synchronize incrementally and audit deletion candidates

**Files:**
- Create: `docsgpt/alembic/versions/0033_openscout_incremental_sync.py`
- Modify: `docsgpt/storage/db/models.py`
- Modify: `docsgpt/storage/db/repositories/intelligence.py`
- Modify: `docsgpt/intelligence/sync_service.py`
- Modify: `docsgpt/intelligence/indexing.py`
- Create: `tests/intelligence/test_incremental_sync.py`
- Modify: `tests/storage/db/repositories/test_intelligence.py`

**Interfaces:**
- Consumes: last successful cursor, external `updated_at`, `content_hash`, and targeted chunk deletion from Stage A.
- Produces: `SyncCursor(last_success_at: datetime, external_updated_at: datetime | None)`, `mark_seen(record_id: str, sync_id: str) -> None`, `record_missing(project_id: str, source_type: SourceType, seen_ids: set[str]) -> int`, `deactivate_confirmed_missing(project_id: str) -> list[str]`, and `IncrementalSyncSummary`.

- [ ] **Step 1: Write change/no-change/two-miss tests**

```python
def test_unchanged_record_is_not_reindexed(service, indexer) -> None:
    service.run_incremental(PROJECT_ID, "u1")
    indexer.replace_records.assert_not_called()


def test_record_deactivates_only_after_two_complete_misses(service, repo) -> None:
    service.run_incremental(PROJECT_ID, "u1")
    assert repo.get_record(RECORD_ID)["active"] is True
    service.run_incremental(PROJECT_ID, "u1")
    assert repo.get_record(RECORD_ID)["active"] is False
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_incremental_sync.py tests/storage/db/repositories/test_intelligence.py -q`

Expected: FAIL because cursor and deletion-audit fields are absent.

- [ ] **Step 3: Add migration and repository transitions**

Add `last_seen_sync_id`, `missing_confirmations integer NOT NULL DEFAULT 0`, `active boolean NOT NULL DEFAULT true`, and `deactivated_at`. Reset misses when seen; increment misses only after a complete source-type sync; partial/failed source batches never confirm absence.

- [ ] **Step 4: Implement incremental collection and targeted indexing**

Use last successful sync time as `since`, compare hashes, index only new/changed records, and remove chunks only when a record transitions from active to inactive. Preserve the normalized record and audit fields after deactivation.

- [ ] **Step 5: Migrate, verify, and commit**

Run: `python -m alembic -c docsgpt/alembic.ini upgrade head`

Run: `python -m pytest tests/intelligence/test_incremental_sync.py tests/storage/db/repositories/test_intelligence.py -q`

Expected: PASS; repeated no-change syncs embed zero chunks and partial failures deactivate nothing.

```bash
git add docsgpt/alembic/versions/0033_openscout_incremental_sync.py docsgpt/storage/db docsgpt/intelligence tests
git commit -m "feat(openscout): add audited incremental synchronization"
```

### Task 3: Schedule synchronization and display durable run status

**Files:**
- Modify: `docsgpt/intelligence/tasks.py`
- Modify: `docsgpt/api/user/intelligence/routes.py`
- Modify: `docsgpt/api/user/scheduler_dispatcher.py`
- Create: `tests/intelligence/test_sync_schedule.py`
- Modify: `frontend/src/intelligence/Overview.tsx`
- Create: `frontend/src/intelligence/SyncStatus.tsx`
- Create: `frontend/src/intelligence/SyncStatus.test.tsx`

**Interfaces:**
- Consumes: existing Celery/RedBeat scheduling and `sync_intelligence_project`.
- Produces: manual/daily schedule contract, idempotent dispatch key `openscout-sync:{project_id}:{scheduled_at}`, and visible run state with retry action.

- [ ] **Step 1: Write scheduling and status tests**

```python
def test_daily_dispatch_uses_project_scoped_idempotency_key(dispatcher) -> None:
    dispatcher.dispatch(PROJECT_ID, scheduled_at=WHEN)
    dispatched = sync_intelligence_project.apply_async.call_args.kwargs["kwargs"]
    assert dispatched["idempotency_key"] == f"openscout-sync:{PROJECT_ID}:{WHEN.isoformat()}"
```

```tsx
it('shows partial counts and a retry action', () => {
  render(<SyncStatus run={partialRun} />);
  expect(screen.getByText('部分完成')).toBeInTheDocument();
  expect(screen.getByRole('button', {name: '重试失败项'})).toBeEnabled();
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/intelligence/test_sync_schedule.py -q`

Run: `cd frontend && npm test -- --run src/intelligence/SyncStatus.test.tsx`

Expected: both fail because scheduling/status components are absent.

- [ ] **Step 3: Reuse RedBeat without adding another scheduler**

Map a daily project schedule to the existing scheduler dispatcher, dispatch the existing task, and preserve bounded retries. The manual endpoint uses the same task and a request-generated idempotency key.

- [ ] **Step 4: Render synchronization transparency**

Show queued/running/complete/partial/failed, object counts by source type, actual coverage, cap flags, last success, error category, and retry action. Never show raw exception strings or tokens.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/intelligence/test_sync_schedule.py tests/api/user/intelligence/test_routes.py -q`

Run: `cd frontend && npm test -- --run src/intelligence/SyncStatus.test.tsx && npm run build`

Expected: schedules dispatch once per due slot and UI reflects every terminal state.

```bash
git add docsgpt/intelligence/tasks.py docsgpt/api/user docsgpt/api/user/scheduler_dispatcher.py tests frontend/src/intelligence
git commit -m "feat(openscout): schedule and explain intelligence syncs"
```

### Task 4: Share and revoke sanitized read-only reports

**Files:**
- Create: `docsgpt/alembic/versions/0034_openscout_report_sharing.py`
- Modify: `docsgpt/storage/db/models.py`
- Modify: `docsgpt/storage/db/repositories/intelligence.py`
- Modify: `docsgpt/api/user/intelligence/routes.py`
- Create: `docsgpt/api/public/__init__.py`
- Create: `docsgpt/api/public/intelligence.py`
- Modify: `docsgpt/app.py`
- Create: `tests/api/user/intelligence/test_report_sharing.py`
- Create: `frontend/src/intelligence/SharedReportView.tsx`
- Create: `frontend/src/intelligence/SharedReportView.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Stage A report JSON.
- Produces: authenticated `POST /api/intelligence/reports/<id>/share` and `DELETE /api/intelligence/reports/<id>/share`, unauthenticated Flask blueprint route `GET /api/public/intelligence/reports/<token>`, and frontend route `/reports/shared/:token`.

- [ ] **Step 1: Write owner/revocation/redaction tests**

```python
def test_public_report_projection_redacts_internal_fields(client, shared_report) -> None:
    response = client.get(f"/api/public/intelligence/reports/{shared_report.token}")
    payload = response.get_json()
    assert response.status_code == 200
    assert "user_id" not in json.dumps(payload)
    assert "trace" not in json.dumps(payload)


def test_revoked_token_returns_not_found(client, revoked_token) -> None:
    assert client.get(f"/api/public/intelligence/reports/{revoked_token}").status_code == 404
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/api/user/intelligence/test_report_sharing.py -q`

Expected: FAIL with missing endpoints/schema fields.

- [ ] **Step 3: Add hashed tokens and a public projection**

Generate 32 random bytes with `secrets.token_urlsafe(32)`, store only SHA-256 token hash plus `shared_at`/`revoked_at`, and return the plaintext token only when sharing is created. Register a separate public Flask blueprint in `docsgpt/app.py`; do not weaken the authenticated user namespace. Public serialization whitelists report title, sections, source URLs, coverage, and generated timestamp.

- [ ] **Step 4: Implement public UI and owner controls**

The owner can create/copy/revoke a link. The public route requires no authentication and offers read-only report content and source links; it exposes no edit, resync, download of private artifacts, or internal trace controls.

- [ ] **Step 5: Verify and commit**

Run: `python -m alembic -c docsgpt/alembic.ini upgrade head`

Run: `python -m pytest tests/api/user/intelligence/test_report_sharing.py -q`

Run: `cd frontend && npm test -- --run src/intelligence/SharedReportView.test.tsx && npm run build`

Expected: owner isolation, token entropy, revocation, and redaction tests PASS.

```bash
git add docsgpt/alembic/versions/0034_openscout_report_sharing.py docsgpt/storage/db docsgpt/api/user/intelligence docsgpt/api/public docsgpt/app.py tests frontend/src
git commit -m "feat(openscout): share sanitized read-only reports"
```

### Task 5: Validate promotion value with real user tasks

**Files:**
- Create: `research/stage-b/research-protocol.md`
- Create: `research/stage-b/task-script.md`
- Create: `research/stage-b/observations.csv`
- Create: `research/stage-b/findings.md`
- Create: `research/stage-b/consent-and-redaction.md`
- Modify: `README-openscout.md`
- Modify: `docs/openscout/decision-log.md`

**Interfaces:**
- Consumes: deployed Stage B build and one consistent competitor-research task.
- Produces: anonymized observations for 5-10 participants, task completion rate, median completion time, evidence-click rate, report-adoption intent, ranked failures, and an evidence-based go/iterate/stop decision.

- [ ] **Step 1: Write the fixed protocol before recruiting**

The protocol defines target roles, one 15-minute research task, success criteria, neutral moderator wording, consent, no collection of GitHub credentials, and the five measures from the specification. Participant ids are `P01`-`P10`; names/emails never enter the repository.

- [ ] **Step 2: Pilot the task once without changing success criteria afterward**

Run the script with one pilot participant. Fix only confusing instructions or broken product behavior; log every protocol change with date and reason before formal sessions.

- [ ] **Step 3: Conduct 5-10 sessions and record one row per participant**

`observations.csv` columns are exactly:

```csv
participant_id,role,completed,seconds,evidence_clicks,report_exported,would_reuse,blocking_failure,notes_redacted
```

Do not coach participants toward the answer and do not replace failed sessions.

- [ ] **Step 4: Analyze outcomes and make one bounded iteration**

Calculate completion rate, median seconds, mean evidence clicks, export rate, and reuse intent. Rank blocking failures by affected participants; fix only the top three core-task failures, rerun their automated regression tests, and record deferred feedback.

- [ ] **Step 5: Publish truthful findings and tag the release**

Run: `ruff check .`

Run: `KMP_DUPLICATE_LIB_OK=TRUE python -m pytest`

Run: `cd frontend && npm run lint && npm run build`

Expected: automated validation succeeds and `findings.md` contains sample size, method, raw aggregate values, limitations, and decision. README/resume wording uses only these measured results.

```bash
git add research/stage-b README-openscout.md docs/openscout/decision-log.md
git commit -m "docs(openscout): publish stage B user validation"
git tag openscout-stage-b
```

## Stage B Self-Review Record

- Spec coverage: arbitrary public repository setup, incremental sync, status/failures, daily scheduling, safe report sharing, revocation, and 5-10 user-task validation each map to one independently testable task.
- Security coverage: private repository access, plaintext token storage, owner fields, credentials, storage paths, and internal trace are explicitly excluded from public responses.
- Type consistency: Stage B extends Stage A `IntelligenceProject`, `SyncSummary`, and `ReportDocument`; it does not introduce parallel shapes.
- Scope boundary: payment, enterprise tenancy, social/news sources, roadmap automation, and complex permissions remain non-goals.
