"""Tests for constrained OpenScout query routing."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from docsgpt.intelligence.query_router import (
    QueryRouter,
    RouteDecision,
    apply_route_threshold,
)
from docsgpt.intelligence.query_service import QueryService
from docsgpt.intelligence.schemas import (
    Coverage,
    Evidence,
    QueryIntent,
    QueryRequest,
    RetrievalStrategy,
    SourceType,
)


def _evidence() -> Evidence:
    """Return one deterministic evidence item for service integration."""
    return Evidence(
        id="evidence-1",
        record_id="issue:1",
        repository="langgenius/dify",
        source_type=SourceType.ISSUE,
        title="Add export",
        excerpt="The issue requests an export option.",
        source_url="https://github.com/langgenius/dify/issues/1",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _coverage(filters) -> Coverage:
    """Return a coverage object matching the query filters."""
    return Coverage(
        repositories=filters.repositories,
        date_from=filters.date_from,
        date_to=filters.date_to,
        counts={SourceType.ISSUE: 1},
    )


def test_low_confidence_route_falls_back_to_hybrid() -> None:
    decision = apply_route_threshold(
        RouteDecision(
            intent="relational",
            strategy="graphrag",
            confidence=0.64,
        )
    )

    assert decision.strategy == RetrievalStrategy.HYBRID
    assert decision.fallback_reason == "low_confidence"


def test_invalid_route_output_falls_back_to_hybrid() -> None:
    router = QueryRouter(
        parser=lambda request: {
            "intent": "relational",
            "strategy": "not-allowed",
            "confidence": 0.99,
        }
    )

    decision = router.route(QueryRequest(question="How are these issues related?"))

    assert decision.strategy == RetrievalStrategy.HYBRID
    assert decision.fallback_reason == "invalid_route_decision"


@pytest.mark.parametrize(
    ("question", "intent", "strategy"),
    [
        (
            "What feature did Dify add?",
            QueryIntent.FACTUAL,
            RetrievalStrategy.HYBRID_RERANK,
        ),
        (
            "When did Dify release version 1.0?",
            QueryIntent.TEMPORAL,
            RetrievalStrategy.HYBRID_RERANK,
        ),
        (
            "Compare Dify and RAGFlow's search features.",
            QueryIntent.COMPARATIVE,
            RetrievalStrategy.SPLIT_HYBRID,
        ),
        (
            "How many issues mention export?",
            QueryIntent.AGGREGATE,
            RetrievalStrategy.SQL_PLUS_HYBRID,
        ),
        (
            "How is the SSO issue related to the latest release?",
            QueryIntent.RELATIONAL,
            RetrievalStrategy.GRAPHRAG,
        ),
    ],
)
def test_default_router_classifies_supported_intents(
    question: str,
    intent: QueryIntent,
    strategy: RetrievalStrategy,
) -> None:
    decision = QueryRouter().route(QueryRequest(question=question))

    assert decision.intent == intent
    assert decision.strategy == strategy
    assert decision.confidence >= 0.65


def test_query_service_traces_explicit_route_decision() -> None:
    retriever = MagicMock()
    retriever.retrieve.return_value = [_evidence()]
    graph_retriever = MagicMock()
    graph_retriever.retrieve.return_value = [_evidence()]
    generator = MagicMock()
    generator.generate.return_value = {"answer": "supported", "claims": []}
    router = QueryRouter(
        parser=lambda request: RouteDecision(
            intent=QueryIntent.RELATIONAL,
            strategy=RetrievalStrategy.GRAPHRAG,
            confidence=0.91,
        )
    )

    result = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=_coverage,
        router=router,
        graph_retriever=graph_retriever,
    ).query(QueryRequest(question="How are these issues related?"), "user-1")

    assert result.trace.intent == QueryIntent.RELATIONAL
    assert result.trace.strategy == RetrievalStrategy.GRAPHRAG
