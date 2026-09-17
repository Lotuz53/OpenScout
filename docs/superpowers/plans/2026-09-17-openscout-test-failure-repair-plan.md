# OpenScout Test Failure Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 22 remaining backend test failures pass without weakening SSRF protection or changing OpenScout product behavior.

**Architecture:** Keep production URL validation unchanged. Isolate endpoint and BYOM forwarding tests from machine-dependent DNS results, add SciPy as a declared core dependency required by the existing NetworkX PageRank path, then re-run the complete backend suite and record the measured result.

**Tech Stack:** Python 3.13, pytest, Flask, NetworkX, SciPy, uv, PostgreSQL test fixtures.

**Spec:** `docs/superpowers/specs/2026-09-17-openscout-test-failure-repair-design.md`

## Global Constraints

- Preserve the existing SSRF blocklist and private/internal address rejection.
- Do not edit frozen OpenScout evaluation questions, answers, snapshots, or thresholds.
- Change only the test fixtures, dependency declarations, generated dependency exports, and validation records required by this repair.
- Never stage the user's existing `AGENTS.md` modification.
- Use `--postgresql-port=55433` for PostgreSQL-backed validation in the current macOS environment.
- After each completed task, run its focused verification, commit only that task's files, and push both `main` and `feature/openscout-design`.

### Task 1: Isolate MCP endpoint tests from machine DNS

**Files:**
- Modify: `tests/api/user/test_tools_mcp_pg.py`

**Interfaces:**
- Consumes: production `docsgpt.api.user.tools.mcp.validate_url` and the existing `MCPTool` mocks.
- Produces: an explicit test-only `_allow_public_mcp_url` fixture used only by the five endpoint branch tests that already mock network behavior.

- [ ] **Step 1: Confirm the current focused failure set**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest \
  tests/api/user/test_tools_mcp_pg.py -q --no-cov \
  --postgresql-port=55433
```

Expected before the change: the five endpoint tests using `https://example.com/mcp` fail with `Invalid MCP server URL: Access to private/internal networks is not allowed`; the lower-level URL validation tests remain green.

- [ ] **Step 2: Add a test-only URL-validation fixture**

Add this fixture near the existing `app` fixture:

```python
@pytest.fixture
def _allow_public_mcp_url(monkeypatch):
    monkeypatch.setattr(
        "docsgpt.api.user.tools.mcp.validate_url",
        lambda _url: None,
    )
```

Add `_allow_public_mcp_url` as a fixture argument only to these methods:

```text
TestTestMCPServerConfig.test_connection_success
TestTestMCPServerConfig.test_connection_failure_returns_200_with_failure_message
TestTestMCPServerConfig.test_oauth_required_returns_200
TestTestMCPServerConfig.test_unexpected_exception_returns_500
TestMCPServerSave.test_creates_mcp_tool_successfully
```

Do not apply the fixture to `TestValidateMcpServerUrl`; its real SSRF assertions must continue to execute.

- [ ] **Step 3: Run the focused MCP suite**

Run the command from Step 1.

Expected: every test in `test_tools_mcp_pg.py` passes, including the real `127.0.0.1` rejection test.

- [ ] **Step 4: Review and commit the MCP test-only change**

Run:

```bash
git diff --check
git status --short
git add tests/api/user/test_tools_mcp_pg.py
git commit -m "test(openscout): isolate mcp endpoint url fixtures"
```

The staged file list must contain only `tests/api/user/test_tools_mcp_pg.py`; `AGENTS.md` must remain unstaged.

- [ ] **Step 5: Push the completed MCP task**

Run separately:

```bash
git push origin HEAD:feature/openscout-design
git push origin HEAD:main
```

### Task 2: Make BYOM forwarding tests DNS-deterministic

**Files:**
- Modify: `tests/core/test_byom_user_aware_helpers.py`
- Modify: `tests/core/test_registry_user_layer.py`

**Interfaces:**
- Consumes: `docsgpt.security.safe_url._resolve` and the existing BYOM dispatch tests.
- Produces: explicit `_stable_public_model_dns` fixtures that make only forwarding tests deterministic while preserving the production validation and pinned-client implementation.

- [ ] **Step 1: Confirm the current focused BYOM failures**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest \
  tests/core/test_byom_user_aware_helpers.py \
  tests/core/test_registry_user_layer.py -q --no-cov \
  --postgresql-port=55433
```

Expected before the change: exactly these four tests fail before their assertions because `api.mistral.ai` resolves to `198.18.2.182`:

```text
TestSharedAgentResolvesOwnerBYOM.test_classic_rag_rephrase_resolves_owner_byom
TestAgentSendsUpstreamModelId.test_llm_gen_passes_upstream_id_to_provider
TestLLMCreatorDispatchUsesUpstreamModelId.test_llmcreator_sends_upstream_id_not_uuid
TestLLMCreatorDispatchUsesUpstreamModelId.test_llmcreator_forwards_byom_capabilities
```

- [ ] **Step 2: Add deterministic DNS fixtures to the two test modules**

In each module, add `import ipaddress` and this fixture:

```python
@pytest.fixture
def _stable_public_model_dns(monkeypatch):
    monkeypatch.setattr(
        "docsgpt.security.safe_url._resolve",
        lambda _host: [ipaddress.ip_address("104.18.0.1")],
    )
```

Add `_stable_public_model_dns` only to the four failing test methods listed in Step 1. Keep `test_dispatch_injects_pinned_http_client_for_user_model` unchanged because it already owns and asserts its own `socket.getaddrinfo` patch and pinned IP.

- [ ] **Step 3: Run the focused BYOM suite**

Run the command from Step 1.

Expected: all tests in both modules pass, including API-key precedence, upstream model-id forwarding, capability forwarding, and the existing SSRF/DNS-pinning tests.

- [ ] **Step 4: Run lint for the changed test modules**

Run:

```bash
ruff check tests/core/test_byom_user_aware_helpers.py tests/core/test_registry_user_layer.py
```

Expected: exit code 0.

- [ ] **Step 5: Review, commit, and push the BYOM task**

Run:

```bash
git diff --check
git status --short
git add tests/core/test_byom_user_aware_helpers.py tests/core/test_registry_user_layer.py
git commit -m "test(openscout): stabilize byom dns fixtures"
git push origin HEAD:feature/openscout-design
git push origin HEAD:main
```

The staged file list must contain only the two BYOM test modules.

### Task 3: Declare SciPy for the GraphRAG PageRank path

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock` (generated by `uv lock`)
- Modify: `docsgpt/requirements.txt` (generated by the export script)
- Modify: `docsgpt/requirements-docling.txt` (generated by the export script)
- Modify: `docsgpt/requirements-milvus.txt` (generated by the export script)

**Interfaces:**
- Consumes: the existing `networkx.pagerank` call in `docsgpt/retriever/graph_rag.py`.
- Produces: a base installation that includes the SciPy runtime required by the existing GraphRAG implementation.

- [ ] **Step 1: Confirm the GraphRAG dependency failure**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest \
  tests/retriever/test_graph_rag.py -q --no-cov
```

Expected before the dependency change: the PageRank and graph batching tests fail with `ModuleNotFoundError: No module named 'scipy'`, and the success-path close assertion observes the fallback path.

- [ ] **Step 2: Add SciPy to the canonical core dependency list**

Add this entry next to the existing numerical/graph dependencies in `pyproject.toml`:

```toml
  "scipy>=1.18.1,<2",
```

Do not edit any `docsgpt/requirements*.txt` file by hand.

- [ ] **Step 3: Regenerate and install dependencies**

Run:

```bash
uv lock
bash scripts/export_requirements.sh
uv sync
```

Expected: the lock and all exported requirement files contain `scipy==1.18.1` for the current lock resolution, and the project environment can import `scipy`.

- [ ] **Step 4: Run the GraphRAG suite**

Run the command from Step 1.

Expected: all GraphRAG tests pass, including PPR ordering, token budget, batching, fallback, and exactly-once success-path store close. Do not modify `docsgpt/retriever/graph_rag.py` unless this focused run still reports a resource-lifecycle failure after SciPy is installed.

- [ ] **Step 5: Run dependency-file consistency checks**

Run:

```bash
git diff --check
ruff check docsgpt/retriever/graph_rag.py
```

Expected: exit code 0; no source change is expected in `graph_rag.py` for this task.

- [ ] **Step 6: Review, commit, and push the dependency task**

Run:

```bash
git status --short
git add pyproject.toml uv.lock docsgpt/requirements.txt docsgpt/requirements-docling.txt docsgpt/requirements-milvus.txt
git commit -m "fix(openscout): declare scipy for graphrag"
git push origin HEAD:feature/openscout-design
git push origin HEAD:main
```

The staged file list must contain only the canonical dependency file, its lockfile, and generated exports.

### Task 4: Re-run the full backend gate and publish the result

**Files:**
- Modify: `docs/openscout/limitations.md`
- Modify: `docs/superpowers/plans/2026-09-15-openscout-ai-stage-a-implementation-plan.md`

**Interfaces:**
- Consumes: the passing focused test groups and the existing Stage A validation record.
- Produces: an accurate full-suite result and Task 17 Step 5 status.

- [ ] **Step 1: Run Ruff**

Run:

```bash
ruff check .
```

Expected: exit code 0.

- [ ] **Step 2: Run the complete backend suite in the known-good PostgreSQL environment**

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest \
  --postgresql-port=55433
```

Expected: exit code 0 with no failed or errored tests. Preserve the exact pass/skip/warning counts and duration from the command output.

- [ ] **Step 3: Update the validation records from measured output**

Replace the old `10,088 passed、451 skipped、22 failed` statement in both files with the new measured result. If the full suite is green, change only Task 17 Step 5 from `[ ]` to `[x]`; keep the separate holdout citation limitation and pending demo video unchanged.

- [ ] **Step 4: Validate the documentation diff**

Run:

```bash
git diff --check
```

Expected: exit code 0 and no changes outside the two validation records plus the user's pre-existing `AGENTS.md` modification.

- [ ] **Step 5: Commit and push the final validation record**

Run:

```bash
git add docs/openscout/limitations.md docs/superpowers/plans/2026-09-15-openscout-ai-stage-a-implementation-plan.md
git commit -m "docs(openscout): record repaired backend validation"
git push origin HEAD:feature/openscout-design
git push origin HEAD:main
```
