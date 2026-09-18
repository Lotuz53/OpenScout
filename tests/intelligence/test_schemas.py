from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from docsgpt.intelligence.schemas import (
    Claim,
    ClaimKind,
    Coverage,
    Evidence,
    QueryFilters,
    QueryResult,
    QueryIntent,
    RetrievalStrategy,
    RetrievalTrace,
    MAX_QUERY_CLAIMS,
    MAX_QUERY_EVIDENCE,
)


def test_factual_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence_ids"):
        Claim(id="c1", text="Dify released feature X", kind=ClaimKind.FACT, evidence_ids=[])


def test_evidence_serializes_utc_timestamp() -> None:
    evidence = Evidence(
        id="e1",
        record_id="r1",
        repository="langgenius/dify",
        source_type="release",
        title="v1",
        excerpt="notes",
        source_url="https://github.com/x",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert evidence.model_dump(mode="json")["occurred_at"] == "2026-01-01T00:00:00Z"


def test_query_filter_collection_is_bounded() -> None:
    with pytest.raises(ValidationError, match="at most"):
        QueryFilters(repositories=["owner/repo"] * 65)


def test_query_result_claim_and_evidence_collections_are_bounded() -> None:
    coverage = Coverage(
        repositories=[],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 2),
        counts={},
    )
    trace = RetrievalTrace(
        intent=QueryIntent.FACTUAL,
        strategy=RetrievalStrategy.HYBRID,
        applied_filters=QueryFilters(),
    )
    claim = Claim(id="claim", text="inference", kind=ClaimKind.INFERENCE)
    evidence = Evidence(
        id="evidence",
        record_id="record",
        repository="owner/repo",
        source_type="release",
        title="Release",
        excerpt="Notes",
        source_url="https://github.com/owner/repo/releases/1",
    )

    with pytest.raises(ValidationError, match="at most"):
        QueryResult(
            answer="ok",
            claims=[claim] * (MAX_QUERY_CLAIMS + 1),
            evidence=[],
            coverage=coverage,
            latency_ms=1,
            trace=trace,
        )
    with pytest.raises(ValidationError, match="at most"):
        QueryResult(
            answer="ok",
            claims=[],
            evidence=[evidence] * (MAX_QUERY_EVIDENCE + 1),
            coverage=coverage,
            latency_ms=1,
            trace=trace,
        )


def test_result_text_is_bounded() -> None:
    with pytest.raises(ValidationError, match="at most"):
        Claim(
            id="claim",
            text="x" * 4001,
            kind=ClaimKind.INFERENCE,
        )

    with pytest.raises(ValidationError, match="at most"):
        Evidence(
            id="evidence",
            record_id="record",
            repository="owner/repo",
            source_type="release",
            title="x" * 513,
            excerpt="Notes",
            source_url="https://github.com/owner/repo/releases/1",
        )
