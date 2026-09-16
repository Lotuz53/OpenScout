"""Tests for the first hybrid-only intelligence query chain."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from docsgpt.intelligence.query_service import QueryService
from docsgpt.intelligence.schemas import (
    Claim,
    ClaimKind,
    Confidence,
    Coverage,
    Evidence,
    QueryRequest,
    RetrievalStrategy,
    SourceType,
)


def _evidence() -> Evidence:
    """Return one deterministic source excerpt for query tests."""
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
    """Return coverage matching the explicit query filters."""
    return Coverage(
        repositories=filters.repositories,
        date_from=filters.date_from,
        date_to=filters.date_to,
        counts={SourceType.RELEASE: 1},
    )


def test_query_service_runs_hybrid_chain_and_returns_trace() -> None:
    retriever = MagicMock()
    retriever.retrieve.return_value = [_evidence()]
    generator = MagicMock()
    generator.generate.return_value = {
        "answer": "Dify added SSO.",
        "claims": [
            Claim(
                id="claim-1",
                text="Dify added SSO.",
                kind=ClaimKind.FACT,
                evidence_ids=["evidence-1"],
                confidence=Confidence.HIGH,
            )
        ],
    }
    service = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=_coverage,
    )
    request = QueryRequest.model_validate(
        {"question": "Which product added SSO?", "filters": {}}
    )

    result = service.query(request, "user-1")

    retriever.retrieve.assert_called_once_with(request.question, request.filters)
    generator.generate.assert_called_once()
    assert result.answer == "Dify added SSO."
    assert result.claims[0].evidence_ids == ["evidence-1"]
    assert result.trace.strategy == RetrievalStrategy.HYBRID
    assert result.latency_ms >= 0


def test_query_service_rejects_citations_not_in_evidence() -> None:
    retriever = MagicMock()
    retriever.retrieve.return_value = [_evidence()]
    generator = MagicMock()
    generator.generate.return_value = {
        "answer": "Unsupported.",
        "claims": [
            Claim(
                id="claim-1",
                text="Unsupported.",
                kind=ClaimKind.FACT,
                evidence_ids=["missing-evidence"],
            )
        ],
    }
    service = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=_coverage,
    )

    with pytest.raises(ValueError, match="unknown evidence"):
        service.query(QueryRequest(question="What happened?"), "user-1")
