"""Tests for the first hybrid-only intelligence query chain."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from docsgpt.intelligence.query_service import NO_EVIDENCE_ANSWER, QueryService
from docsgpt.intelligence.query_router import QueryRouter
from docsgpt.intelligence.schemas import (
    Claim,
    ClaimKind,
    Confidence,
    Coverage,
    Evidence,
    QueryRequest,
    QueryIntent,
    RouteDecision,
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


def test_query_service_retries_then_rejects_citations_not_in_evidence() -> None:
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

    result = service.query(QueryRequest(question="What happened?"), "user-1")

    assert generator.generate.call_count == 2
    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.claims == []
    assert result.evidence == [_evidence()]


def test_graph_failure_falls_back_and_traces_reason() -> None:
    retriever = MagicMock()
    retriever.retrieve.return_value = [_evidence()]
    graph_retriever = MagicMock()
    graph_retriever.retrieve.side_effect = RuntimeError("graph store unavailable")
    generator = MagicMock()
    generator.generate.return_value = {"answer": "supported", "claims": []}
    analytics = MagicMock()
    router = QueryRouter(
        parser=lambda request: RouteDecision(
            intent=QueryIntent.RELATIONAL,
            strategy=RetrievalStrategy.GRAPHRAG,
            confidence=0.9,
        )
    )
    request = QueryRequest(question="How are these issues related?")

    result = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=_coverage,
        router=router,
        graph_retriever=graph_retriever,
        analytics=analytics,
    ).query(request, "u1")

    assert result.trace.strategy == RetrievalStrategy.HYBRID
    assert result.trace.fallback_reason == "graphrag_unavailable"
    graph_retriever.retrieve.assert_called_once()
    retriever.retrieve.assert_called_once_with(request.question, request.filters)
    analytics.run.assert_not_called()


@pytest.mark.parametrize(
    ("graph_result", "graph_error", "reason"),
    [
        ({"status": "incomplete", "evidence": []}, None, "graphrag_incomplete"),
        (None, TimeoutError("graph timeout"), "graphrag_timeout"),
    ],
)
def test_graph_fallback_traces_incomplete_and_timeout(
    graph_result, graph_error, reason
) -> None:
    retriever = MagicMock()
    retriever.retrieve.return_value = [_evidence()]
    graph_retriever = MagicMock()
    if graph_error is not None:
        graph_retriever.retrieve.side_effect = graph_error
    else:
        graph_retriever.retrieve.return_value = graph_result
    generator = MagicMock()
    generator.generate.return_value = {"answer": "supported", "claims": []}
    router = QueryRouter(
        parser=lambda request: RouteDecision(
            intent=QueryIntent.RELATIONAL,
            strategy=RetrievalStrategy.GRAPHRAG,
            confidence=0.9,
        )
    )

    result = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=_coverage,
        router=router,
        graph_retriever=graph_retriever,
    ).query(QueryRequest(question="How are these issues related?"), "u1")

    assert result.trace.strategy == RetrievalStrategy.HYBRID
    assert result.trace.fallback_reason == reason


def test_disabled_graph_falls_back_without_calling_adapter() -> None:
    retriever = MagicMock()
    retriever.retrieve.return_value = [_evidence()]
    graph_retriever = MagicMock()
    generator = MagicMock()
    generator.generate.return_value = {"answer": "supported", "claims": []}
    router = QueryRouter(
        parser=lambda request: RouteDecision(
            intent=QueryIntent.RELATIONAL,
            strategy=RetrievalStrategy.GRAPHRAG,
            confidence=0.9,
        )
    )

    result = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=_coverage,
        router=router,
        graph_retriever=graph_retriever,
        graph_enabled=False,
    ).query(QueryRequest(question="How are these issues related?"), "u1")

    assert result.trace.strategy == RetrievalStrategy.HYBRID
    assert result.trace.fallback_reason == "graphrag_disabled"
    graph_retriever.retrieve.assert_not_called()
