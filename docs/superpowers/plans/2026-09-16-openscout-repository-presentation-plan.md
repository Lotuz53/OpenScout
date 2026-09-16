# OpenScout Repository Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Present the existing repository as a complete OpenScout AI project on GitHub while preserving DocsGPT ancestry and the current development branch.

**Architecture:** Keep the existing source history and Stage A implementation intact. Make the repository-facing documentation OpenScout-first, then expose the same commit through a stable `main` branch and configure the GitHub repository to use it as the default.

**Tech Stack:** Markdown documentation, Git branches/remotes, GitHub repository settings.

**Spec:** `docs/superpowers/specs/2026-09-16-openscout-repository-presentation-design.md`

## Global Constraints

- Preserve the existing DocsGPT commit ancestry; do not rewrite history.
- Keep `feature/openscout-design`; do not delete or force-overwrite an existing remote branch.
- Do not modify OpenScout feature code, evaluation outputs, or Stage A/B plans.
- Preserve the user's uncommitted `AGENTS.md` change and exclude it from commits.
- Push each completed task and verify the remote hash before continuing.

---

### Task 1: Make repository documentation OpenScout-first

**Files:**
- Modify: `README.md`
- Delete: `README-openscout.md`
- Modify: `CONTRIBUTING.md`

**Interfaces:**
- Consumes: the approved copy and links in `README-openscout.md`.
- Produces: a root README and contribution guide that identify OpenScout as the project, while linking to DocsGPT only as the upstream foundation.

- [x] Replace the root README with the approved OpenScout overview, preserving measured Stage A limitations and evaluation links.
- [x] Remove the duplicate `README-openscout.md` entry point.
- [x] Rewrite DocsGPT-specific contribution instructions as OpenScout instructions and retain only relevant upstream references.
- [x] Run `git diff --check` and inspect targeted OpenScout/DocsGPT references.
- [x] Commit the documentation changes without `AGENTS.md` and push the current development branch.

### Task 2: Establish a stable default branch and remote layout

**Files:**
- Git metadata only: local `main` branch and remotes
- GitHub repository setting: default branch

**Interfaces:**
- Consumes: the Task 1 commit on `feature/openscout-design`.
- Produces: `main` and `feature/openscout-design` pointing to the same current commit, with `main` as the GitHub default branch.

- [x] Move the local `main` pointer to the current OpenScout commit without checking out or changing the worktree.
- [x] Set local `origin` to `https://github.com/Lotuz53/OpenScout.git` and add DocsGPT as `upstream`.
- [x] Push `main` and set the GitHub default branch to `main`.
- [x] Push the current development branch if its final commit changed, then verify both remote branch hashes.

### Task 3: Final repository presentation verification

**Files:**
- No source files

**Interfaces:**
- Consumes: the published `main` and `feature/openscout-design` branches.
- Produces: verified repository metadata and a clean, intentionally preserved worktree state.

- [x] Confirm GitHub reports `main` as the default branch and the repository is not falsely represented as a GitHub fork.
- [x] Confirm the root README is OpenScout-first and the latest commit is the expected OpenScout commit.
- [x] Confirm only the pre-existing `AGENTS.md` modification remains uncommitted.
- [x] Record the remote branch/tag hashes and any non-blocking GitHub warnings.

**Final verification:** `main` and `feature/openscout-design` both point to `bc4530e3554712d54d08ecd24842a6398ff25773`; `openscout-stage-a` remains at `acb8b3d5b618a8bcc2b7f30fb11f5ed33682025d`. GitHub reports `default_branch=main`, `fork=false`, and no parent repository. GitHub warned that the pre-existing `tests/e2e/fixtures/docs/oversize.pdf` is 55 MB, but accepted the push.
