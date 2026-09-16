# OpenScout evaluation dataset

The development split contains 60 manually reviewed questions: 15 each for
factual, temporal, comparative, and comprehensive questions. The holdout split
contains 20 questions with the same 15/5 distribution. Every row is tied to
snapshot stage-a-2026-09-14, whose repository and time window are defined in
evaluation/fixtures/stage_a_snapshot.json.

Each JSONL row contains:

- id, snapshot_id, type, and question;
- answer_points, the manually reviewed points an answer should cover;
- evidence_urls, the source URLs accepted as gold evidence;
- repositories, date_from, and date_to, the query scope;
- acceptance, including citation and answer-point rules.

Comprehensive questions additionally set subtype to aggregate or relational.
Aggregate questions combine multiple records or source types; relational
questions test an explicit relationship between records.

The recorded fixture executor is an offline, deterministic lexical proxy. Its
outputs make the vector/hybrid comparison reproducible, but they are not
production embedding-quality measurements. Both supplied configurations set
promotion.default to false.

The holdout answers are frozen after this file is committed. Do not edit,
reorder, or replace a holdout row after selecting an evaluation approach.
Changes require a new snapshot and a new holdout split. Use
evaluation/check_regression.py against a committed result baseline before
promoting a retrieval change.
