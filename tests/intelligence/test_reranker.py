"""Tests for the provider-neutral OpenScout reranker boundary."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from docsgpt.intelligence.reranker import NoOpReranker, safe_rerank
from docsgpt.intelligence.query_service import QueryService
from docsgpt.intelligence.schemas import (
    Coverage,
    Evidence,
    QueryRequest,
    RetrievalStrategy,
    SourceType,
)


def _evidence(index: int) -> Evidence:
    """Return one deterministic evidence item."""
    return Evidence(
        id=f"evidence-{index}",
        record_id=f"issue:{index}",
        repository="langgenius/dify",
        source_type=SourceType.ISSUE,
        title=f"Issue {index}",
        excerpt=f"Excerpt {index}",
        source_url=f"https://github.com/langgenius/dify/issues/{index}",
        occurred_at=datetime(2026, 1, index, tzinfo=timezone.utc),
    )


EVIDENCE = [_evidence(index) for index in range(1, 7)]


class BrokenReranker:
    """Reranker double that simulates an unavailable provider."""

    def rerank(self, question, evidence, top_n):
        """Raise to exercise the safe fallback."""
        raise RuntimeError("provider unavailable")


class ReverseReranker:
    """Reranker double that makes the ordering change observable."""

    def rerank(self, question, evidence, top_n):
        """Return the candidate evidence in reverse order."""
        del question
        return list(reversed(evidence[:top_n]))


def test_reranker_failure_preserves_hybrid_order() -> None:
    assert safe_rerank(BrokenReranker(), "q", EVIDENCE, 5) == EVIDENCE[:5]


def test_noop_reranker_preserves_hybrid_order_and_top_n() -> None:
    assert NoOpReranker().rerank("q", EVIDENCE, 3) == EVIDENCE[:3]


def test_query_service_applies_only_configured_reranker() -> None:
    retriever = MagicMock()
    retriever.retrieve.return_value = EVIDENCE
    generator = MagicMock()
    generator.generate.return_value = {"answer": "supported", "claims": []}

    def coverage(filters) -> Coverage:
        return Coverage(
            repositories=filters.repositories,
            date_from=filters.date_from,
            date_to=filters.date_to,
            counts={SourceType.ISSUE: len(EVIDENCE)},
        )

    result = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=coverage,
        reranker=ReverseReranker(),
    ).query(QueryRequest(question="Which issue?"), "user-1")

    assert result.evidence == list(reversed(EVIDENCE))
    assert result.trace.strategy == RetrievalStrategy.HYBRID_RERANK
