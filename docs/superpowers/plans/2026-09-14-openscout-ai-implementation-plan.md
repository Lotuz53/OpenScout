# OpenScout AI Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute OpenScout AI in two independently releasable stages, prioritizing the resume-ready Stage A before spending time on promotion features.

**Architecture:** Stage A builds the fixed three-repository intelligence product and proves retrieval quality. Stage B reuses that vertical slice for arbitrary public repositories, incremental synchronization, report sharing, and user validation. The detailed plans carry exact files, interfaces, tests, commands, and commit boundaries.

**Tech Stack:** Python 3.12, Flask-RESTX, SQLAlchemy Core, Alembic, PostgreSQL/pgvector, Redis/Celery, Pydantic 2, pytest, React/TypeScript, Redux Toolkit, Vite/Vitest, ReportLab.

**Spec:** `docs/superpowers/specs/2026-09-14-openscout-ai-design.md`

## Global Constraints

- Complete and measure Stage A before beginning Stage B.
- Use DocsGPT's existing auth, LLM, Embedding, HybridRetriever, GraphRAG, vector-store, Redis/Celery, Redux, and component conventions.
- Keep original OpenScout work inside narrow `intelligence` feature boundaries and disclose the DocsGPT base in portfolio materials.
- Follow red/green TDD, commit each reviewable task, and use measured values only.

---

## Execution Order

- [ ] **Stage A — resume-ready fixed three-product release**

Plan: [`2026-09-15-openscout-ai-stage-a-implementation-plan.md`](2026-09-15-openscout-ai-stage-a-implementation-plan.md)

Deliverable: fixed Dify/RAGFlow/FastGPT ingestion; evidence-based factual, temporal, comparative, aggregate, and relational questions; product matrix; Markdown/PDF report; 80 reviewed questions; three reproducible experiments; five-minute demo; measured README claims.

Estimated effort at 6-8 hours/day: 15 focused workdays. Tasks 1-7 create the data-to-query vertical slice; Tasks 8-13 prove and improve retrieval/trust; Tasks 14-17 finish reports, product UI, and release evidence.

- [ ] **Stage A gate**

Run the sealed holdout once. Continue to Stage B only after the fixed demo is stable and the README accurately states whichever thresholds passed or failed. A failed metric does not block portfolio use, but it blocks claiming that metric was achieved.

- [ ] **Stage B — promotion and validation release**

Plan: [`2026-09-15-openscout-ai-stage-b-implementation-plan.md`](2026-09-15-openscout-ai-stage-b-implementation-plan.md)

Deliverable: arbitrary public repository preflight, audited incremental sync, daily/manual runs, sanitized revocable report links, and 5-10 anonymized user-task sessions.

Estimated effort at 6-8 hours/day: 5-7 focused workdays plus recruiting/calendar time that does not count as engineering effort.

## Review Findings Resolved

1. The previous document was organized by calendar day rather than independently testable deliverables. The new plans use 22 reviewable tasks with explicit red/green tests and commits.
2. The previous document named files but did not define shared signatures. The Stage A plan now freezes `QueryResult`, `Evidence`, `Claim`, `Coverage`, `RouteDecision`, and `SyncSummary` before consumers are built.
3. The previous report design risked reusing DocsGPT artifacts even though the current artifact schema requires a conversation or workflow parent. Reports now use the dedicated `intelligence_reports` table required by the product domain.
4. The previous plan treated Rerank as if it already existed. The repository only reserves reranker configuration, so the new plan adds a provider-neutral `Reranker` protocol and a tested no-op fallback without silently adding a heavy dependency.
5. Incremental deletion could have removed data after partial GitHub failures. Stage B now increments missing confirmations only after a complete source-type sync and requires two successful misses.
6. The evaluation sequence previously expanded the dataset late. Stage A now freezes 60 development and 20 holdout questions before optimization and forbids post-run holdout edits.
7. Frontend/API names could drift. The backend contract is defined first and TypeScript mirrors the same snake_case response keys.
8. The spec's trust rules are now executable: per-claim citations, deterministic confidence, one regeneration, refusal/degraded evidence response, and conflict preservation each have tests.

## Milestones

| Milestone | Ends after | Demonstrable outcome |
|---|---:|---|
| Data foundation | Stage A Task 6 | Repeat sync embeds zero unchanged records; one changed Issue replaces only its chunks |
| First vertical demo | Stage A Task 7 | Authenticated question returns answer, claims, evidence, coverage, latency, and trace |
| Retrieval proof | Stage A Task 13 | Three versioned experiments and uncited-claim guard exist |
| Portfolio release | Stage A Task 17 | Five-minute demo, exports, metrics, architecture, limitations, screenshots/video |
| Promotion release | Stage B Task 4 | Any public repo, incremental status, revocable report link |
| Market evidence | Stage B Task 5 | 5-10 real task sessions and a measured go/iterate/stop conclusion |

## Daily Learning Rule

Spend 45-60 minutes only on the concept needed for the current task, 4-5 hours implementing with AI, 1-1.5 hours running experiments and classifying failures, and 30 minutes recording one decision and a two-minute interview explanation. Syntax memorization is not an objective; the ability to explain the product trade-off and verify AI-generated implementation is.

## Self-Review Record

- Scope is split because Stage A and Stage B can be accepted or rejected independently and each produces working software.
- Every specification requirement maps to a detailed Stage A or Stage B task; non-goals remain excluded.
- Detailed plans contain exact file paths, interfaces, failing tests, implementation instructions, validation commands, expected outcomes, and commit boundaries.
- The original plan remains at this path as the stable entry point, so existing links do not break.
