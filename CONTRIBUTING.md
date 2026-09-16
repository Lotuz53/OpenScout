# Contributing to OpenScout

Thank you for contributing to OpenScout AI. OpenScout is an evidence-first product intelligence workbench built on the DocsGPT application foundation. Contributions should make the OpenScout-specific ingestion, evidence retrieval, analysis, workbench, reporting, or evaluation experience more useful and more trustworthy.

## Before you start

- Read [`README.md`](README.md) for the current product scope and measured limitations.
- Read [`docs/openscout/architecture.md`](docs/openscout/architecture.md) before changing OpenScout data flow or service boundaries.
- Read [`docs/openscout/limitations.md`](docs/openscout/limitations.md) before changing evaluation or evidence behavior.
- Keep changes focused on the issue or feature being addressed; avoid unrelated refactors.
- Add or update tests for behavior changes.
- For UI changes, attach a screenshot or short screen recording to the Pull Request so reviewers can verify the result.

## Development checks

Use the existing local environment when possible. The repository's development workflow and service prerequisites are documented in [`AGENTS.md`](AGENTS.md).

Backend checks:

```bash
ruff check .
KMP_DUPLICATE_LIB_OK=TRUE python -m pytest
```

Frontend checks:

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

Documentation checks:

```bash
cd docs && npm run build
```

For the reproducible offline Stage A check, run the command documented in the README:

```bash
KMP_DUPLICATE_LIB_OK=TRUE .venv/bin/python -m pytest \\
  tests/integration/test_openscout_stage_a.py -q
```

## Project boundaries

OpenScout-specific code and evidence live in the intelligence, evaluation, and `docs/openscout` areas. The `docsgpt/` application provides the underlying Flask/React runtime, authentication, storage, retrieval, model integrations, and document processing. Changes to the foundation should explain their impact on OpenScout behavior and include focused regression coverage.

Do not edit frozen evaluation outputs to improve a score. If the snapshot, rubric, or human-reviewed answers change, create a new version and document the reason in the decision log.

## Git workflow

Clone the OpenScout repository and create a focused branch:

```bash
git clone https://github.com/Lotuz53/OpenScout.git
cd OpenScout
git switch -c feature/short-description
```

If you need to compare or synchronize with the DocsGPT foundation, add it as an upstream remote:

```bash
git remote add upstream https://github.com/arc53/DocsGPT.git
git fetch upstream
```

Stage only the files belonging to your change, commit with a descriptive message, and push your branch:

```bash
git add path/to/changed-file path/to/test-file
git commit -m "feat(openscout): describe the change"
git push -u origin feature/short-description
```

## Pull Requests

Please include:

- a concise description of the user-visible or evaluation-visible change;
- the focused validation commands you ran and their results;
- screenshots or a short recording for UI changes;
- any configuration, dependency, migration, or deployment implications;
- links to relevant evaluation evidence when changing retrieval, citations, reports, or quality gates.

Reviewers may ask for narrower scope, additional tests, or clearer evidence before merging. Thank you for helping make OpenScout more transparent and useful.
