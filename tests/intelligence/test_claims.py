"""Tests for evidence validation and query-level citation enforcement."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from docsgpt.intelligence.claims import ClaimValidation, validate_claims
from docsgpt.intelligence.query_service import NO_EVIDENCE_ANSWER, QueryService
from docsgpt.intelligence.schemas import (
    Claim,
    ClaimKind,
    Confidence,
    Coverage,
    Evidence,
    QueryFilters,
    QueryRequest,
    SourceType,
)


def _evidence() -> Evidence:
    """Return one official source excerpt."""
    return Evidence(
        id="evidence-1",
        record_id="release:1",
        repository="langgenius/dify",
        source_type=SourceType.RELEASE,
        title="Dify 1.0",
        excerpt="Added SSO support.",
        source_url="https://github.com/langgenius/dify/releases/tag/v1.0",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _coverage(filters) -> Coverage:
    """Return coverage matching the query filters."""
    return Coverage(
        repositories=filters.repositories,
        date_from=filters.date_from,
        date_to=filters.date_to,
        counts={SourceType.RELEASE: 1},
    )


def _claim(evidence_ids: list[str], *, claim_id: str = "claim-1") -> Claim:
    """Build a fact claim with an intentionally misleading confidence value."""
    return Claim(
        id=claim_id,
        text="Dify added SSO.",
        kind=ClaimKind.FACT,
        evidence_ids=evidence_ids,
        confidence=Confidence.LOW,
    )


def test_validate_claims_rejects_unknown_ids_without_dropping_valid_claims() -> None:
    """Unknown citations are invalid while supported claims remain inspectable."""
    valid_claim = _claim(["evidence-1"], claim_id="valid")
    invalid_claim = _claim(["missing-evidence"], claim_id="invalid")
    coverage = _coverage(QueryFilters())

    result = validate_claims(
        [valid_claim, invalid_claim],
        [_evidence()],
        coverage,
    )

    assert isinstance(result, ClaimValidation)
    assert result.valid is False
    assert result.valid_claims == [valid_claim]
    assert result.invalid_claims == [invalid_claim]
    assert result.unknown_evidence_ids == {"invalid": ["missing-evidence"]}


def test_query_service_regenerates_once_and_overwrites_model_confidence() -> None:
    """A citation error gets one retry and then deterministic confidence."""
    retriever = MagicMock()
    retriever.retrieve.return_value = [_evidence()]
    generator = MagicMock()
    generator.generate.side_effect = [
        {"answer": "Unsupported first draft.", "claims": [_claim(["missing"]) ]},
        {"answer": "Dify added SSO.", "claims": [_claim(["evidence-1"])]},
    ]

    result = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=_coverage,
    ).query(QueryRequest(question="Which product added SSO?"), "user-1")

    assert generator.generate.call_count == 2
    assert result.answer == "Dify added SSO."
    assert result.claims[0].confidence == Confidence.HIGH


def test_query_service_degrades_after_one_invalid_retry() -> None:
    """Two invalid generations yield refusal text plus evidence cards."""
    retriever = MagicMock()
    retriever.retrieve.return_value = [_evidence()]
    generator = MagicMock()
    generator.generate.side_effect = [
        {"answer": "Unsupported first draft.", "claims": [_claim(["missing"])]},
        {"answer": "Unsupported second draft.", "claims": [_claim(["missing"])]},
    ]

    result = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=_coverage,
    ).query(QueryRequest(question="Which product added SSO?"), "user-1")

    assert generator.generate.call_count == 2
    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.claims == []
    assert result.evidence == [_evidence()]


def test_validate_claims_preserves_multiple_claims_for_conflict_display() -> None:
    """Validation does not silently choose one side of a conflicting answer."""
    claims = [_claim(["evidence-1"], claim_id="claim-a"), _claim(["evidence-1"], claim_id="claim-b")]
    coverage = _coverage(QueryFilters())

    result = validate_claims(claims, [_evidence()], coverage)

    assert result.valid is True
    assert result.valid_claims == claims


def test_query_service_preserves_conflicting_claims_and_source_evidence() -> None:
    """A conflict marker lowers confidence without selecting one conclusion."""
    retriever = MagicMock()
    retriever.retrieve.return_value = [_evidence()]
    generator = MagicMock()
    generator.generate.return_value = {
        "answer": "Sources disagree.",
        "claims": [
            _claim(["evidence-1"], claim_id="claim-a"),
            _claim(["evidence-1"], claim_id="claim-b").model_copy(
                update={"text": "Another source disagrees."}
            ),
        ],
        "has_conflict": True,
    }

    result = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=_coverage,
    ).query(QueryRequest(question="What do sources say?"), "user-1")

    assert [claim.id for claim in result.claims] == ["claim-a", "claim-b"]
    assert all(claim.confidence == Confidence.LOW for claim in result.claims)
    assert result.evidence == [_evidence()]
