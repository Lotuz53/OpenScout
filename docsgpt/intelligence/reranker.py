"""Provider-neutral reranking boundary for intelligence evidence."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

from docsgpt.intelligence.schemas import Evidence

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    """Interface implemented by an optional evidence reranking provider."""

    def rerank(
        self,
        question: str,
        evidence: Sequence[Evidence],
        top_n: int,
    ) -> list[Evidence]:
        """Return evidence ordered for the question, limited to top_n items."""
        raise NotImplementedError


class NoOpReranker:
    """Fallback reranker that preserves the Hybrid retrieval order."""

    def rerank(
        self,
        question: str,
        evidence: Sequence[Evidence],
        top_n: int,
    ) -> list[Evidence]:
        """Return the first top_n items without external model calls."""
        del question
        return list(evidence[: max(0, top_n)])


def safe_rerank(
    reranker: Reranker,
    question: str,
    evidence: Sequence[Evidence],
    top_n: int,
) -> list[Evidence]:
    """Run a reranker and preserve Hybrid order when it fails."""
    limit = max(0, top_n)
    try:
        reranked = reranker.rerank(question, evidence, limit)
        if not isinstance(reranked, Sequence) or isinstance(reranked, (str, bytes)):
            raise TypeError("reranker must return a sequence of Evidence")
        return list(reranked[:limit])
    except Exception:
        logger.exception("reranker failed; preserving hybrid order")
        return list(evidence[:limit])


__all__ = ["NoOpReranker", "Reranker", "safe_rerank"]
