"""Constrained intent and retrieval-strategy routing for OpenScout queries."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from docsgpt.intelligence.schemas import (
    QueryIntent,
    QueryRequest,
    RouteDecision,
    RetrievalStrategy,
)


logger = logging.getLogger(__name__)
ROUTE_CONFIDENCE_THRESHOLD = 0.65
ROUTE_STRATEGIES = {
    QueryIntent.FACTUAL: RetrievalStrategy.HYBRID_RERANK,
    QueryIntent.TEMPORAL: RetrievalStrategy.HYBRID_RERANK,
    QueryIntent.COMPARATIVE: RetrievalStrategy.SPLIT_HYBRID,
    QueryIntent.AGGREGATE: RetrievalStrategy.SQL_PLUS_HYBRID,
    QueryIntent.RELATIONAL: RetrievalStrategy.GRAPHRAG,
}


RouteParser = Callable[[QueryRequest], RouteDecision | Mapping[str, Any]]


def apply_route_threshold(
    decision: RouteDecision,
    threshold: float = ROUTE_CONFIDENCE_THRESHOLD,
) -> RouteDecision:
    """Fall back to the safe Hybrid strategy below the confidence threshold.

    Args:
        decision: A validated route decision.
        threshold: Minimum confidence required for the requested strategy.

    Returns:
        The original decision or a copy whose strategy is ``hybrid``.
    """
    if decision.confidence >= threshold:
        return decision
    return decision.model_copy(
        update={
            "strategy": RetrievalStrategy.HYBRID,
            "fallback_reason": decision.fallback_reason or "low_confidence",
        }
    )


class QueryRouter:
    """Route questions through a validated parser or deterministic fallback."""

    def __init__(
        self,
        parser: RouteParser | None = None,
        *,
        classifier: RouteParser | None = None,
        confidence_threshold: float = ROUTE_CONFIDENCE_THRESHOLD,
    ) -> None:
        """Initialize the router.

        Args:
            parser: Optional parser receiving a complete ``QueryRequest``.
            classifier: Backwards-compatible name for the parser boundary.
            confidence_threshold: Minimum confidence for non-Hybrid routes.

        Raises:
            ValueError: If both parser aliases are supplied or the threshold
                is outside the inclusive confidence range.
        """
        if parser is not None and classifier is not None:
            raise ValueError("provide parser or classifier, not both")
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self.parser = parser or classifier
        self.confidence_threshold = confidence_threshold

    def route(self, request: QueryRequest) -> RouteDecision:
        """Return a validated and thresholded route decision.

        Invalid parser output is treated as an unsafe route and falls back to
        factual Hybrid retrieval while preserving the caller's explicit
        filters in the request handled by ``QueryService``.
        """
        try:
            raw_decision = (
                self.parser(request)
                if self.parser is not None
                else self._heuristic_decision(request)
            )
            decision = (
                raw_decision
                if isinstance(raw_decision, RouteDecision)
                else RouteDecision.model_validate(raw_decision)
            )
            if request.intent is not None:
                decision = decision.model_copy(
                    update={
                        "intent": request.intent,
                        "strategy": ROUTE_STRATEGIES[request.intent],
                        "confidence": 1.0,
                    }
                )
        except Exception:
            logger.exception("route decision validation failed; using Hybrid")
            return RouteDecision(
                intent=QueryIntent.FACTUAL,
                strategy=RetrievalStrategy.HYBRID,
                confidence=0.0,
                fallback_reason="invalid_route_decision",
            )
        return apply_route_threshold(decision, self.confidence_threshold)

    @staticmethod
    def _heuristic_decision(request: QueryRequest) -> RouteDecision:
        """Classify common question forms without a model dependency."""
        if request.intent is not None:
            return RouteDecision(
                intent=request.intent,
                strategy=ROUTE_STRATEGIES[request.intent],
                confidence=1.0,
            )

        question = request.question.casefold()
        if _contains_any(question, ("相关", "关系", "关联", "related", "relationship")):
            intent = QueryIntent.RELATIONAL
        elif _contains_any(
            question,
            ("比较", "对比", "差异", "compare", "versus", " vs "),
        ):
            intent = QueryIntent.COMPARATIVE
        elif _contains_any(
            question,
            (
                "多少",
                "数量",
                "统计",
                "how many",
                "number of",
                "count",
                "median",
                "sum",
            ),
        ):
            intent = QueryIntent.AGGREGATE
        elif _contains_any(
            question,
            (
                "何时",
                "什么时候",
                "何时",
                "最近",
                "时间",
                "when",
                "recent",
                "latest",
                "most recent",
            ),
        ):
            intent = QueryIntent.TEMPORAL
        else:
            intent = QueryIntent.FACTUAL

        return RouteDecision(
            intent=intent,
            strategy=ROUTE_STRATEGIES[intent],
            confidence=0.9,
        )


def _contains_any(value: str, candidates: tuple[str, ...]) -> bool:
    """Return whether a question contains one of the routing markers."""
    return any(candidate in value for candidate in candidates)


__all__ = [
    "ROUTE_CONFIDENCE_THRESHOLD",
    "QueryRouter",
    "RouteDecision",
    "apply_route_threshold",
]
