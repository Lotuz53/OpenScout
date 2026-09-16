"""Deterministic retrieval and citation metrics for OpenScout experiments."""

from __future__ import annotations

from collections.abc import Sequence
from math import log2


def _unique(values: Sequence[str]) -> set[str]:
    """Return non-empty values as a set for binary relevance metrics."""
    return {str(value) for value in values if value}


def recall_at_k(
    expected: Sequence[str],
    retrieved: Sequence[str],
    k: int,
) -> float:
    """Return the fraction of expected ids found in the first ``k`` results.

    Args:
        expected: Relevant evidence identifiers or URLs.
        retrieved: Ranked identifiers or URLs returned by a retriever.
        k: Maximum rank included in the calculation.

    Returns:
        A value between 0 and 1. Empty expectations and non-positive ``k``
        return 0 so an incomplete test item cannot inflate an experiment.
    """
    relevant = _unique(expected)
    if not relevant or k <= 0:
        return 0.0
    found = _unique(retrieved[:k])
    return len(relevant & found) / len(relevant)


def ndcg_at_k(
    expected: Sequence[str],
    retrieved: Sequence[str],
    k: int,
) -> float:
    """Return binary-relevance nDCG for the first ``k`` ranked results."""
    relevant = _unique(expected)
    if not relevant or k <= 0:
        return 0.0

    seen: set[str] = set()
    dcg = 0.0
    for rank, item in enumerate(retrieved[:k], start=1):
        item = str(item)
        if item in relevant and item not in seen:
            dcg += 1.0 / log2(rank + 1)
            seen.add(item)

    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def citation_precision(
    cited: Sequence[str],
    expected: Sequence[str],
) -> float:
    """Return the fraction of cited identifiers that are expected evidence."""
    cited_values = [str(value) for value in cited if value]
    expected_values = _unique(expected)
    if not cited_values or not expected_values:
        return 0.0
    return sum(value in expected_values for value in cited_values) / len(cited_values)


__all__ = ["citation_precision", "ndcg_at_k", "recall_at_k"]
