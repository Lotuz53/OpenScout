"""Tests for deterministic OpenScout evaluation metrics."""

from evaluation.metrics import citation_precision, ndcg_at_k, recall_at_k


def test_recall_at_five() -> None:
    assert recall_at_k(["a", "b"], ["x", "a", "y"], 5) == 0.5


def test_ndcg_rewards_earlier_relevant_evidence() -> None:
    assert ndcg_at_k(["a"], ["a", "x"], 10) > ndcg_at_k(["a"], ["x", "a"], 10)


def test_citation_precision() -> None:
    assert citation_precision(["a", "x"], ["a", "b"]) == 0.5


def test_metrics_handle_empty_inputs() -> None:
    assert recall_at_k([], ["a"], 5) == 0.0
    assert ndcg_at_k([], ["a"], 10) == 0.0
    assert citation_precision([], ["a"]) == 0.0
