"""Whitelist-only SQL analytics for OpenScout aggregate questions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field

from docsgpt.intelligence.schemas import (
    Coverage,
    Evidence,
    IntelligenceModel,
    QueryFilters,
    SourceType,
)


ALLOWED_METRICS = frozenset({"count", "median_comments", "sum_reactions"})
ALLOWED_DIMENSIONS = frozenset({"repository", "source_type", "label", "month", "state"})
ALLOWED_ORDERS = frozenset({"value_asc", "value_desc", "period_asc"})
DEFAULT_EVIDENCE_LIMIT = 5
DEFAULT_AGGREGATE_LIMIT = 100


class AggregateQuery(IntelligenceModel):
    """A structured request for one deterministic SQL aggregate."""

    metric: str
    dimension: str
    user_id: str | None = None
    project_ids: list[str] = Field(default_factory=list)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    order: str = "value_desc"
    limit: int = Field(default=DEFAULT_AGGREGATE_LIMIT, ge=1, le=DEFAULT_AGGREGATE_LIMIT)


class AggregateRow(IntelligenceModel):
    """One dimension/value pair returned by PostgreSQL."""

    dimension: str
    value: int | float


class AggregateResult(IntelligenceModel):
    """SQL aggregate values, coverage, cap status, and supporting evidence."""

    rows: list[AggregateRow] = Field(default_factory=list)
    coverage: Coverage
    capped: bool = False
    evidence: list[Evidence] = Field(default_factory=list)
    metric: str = "count"
    dimension: str = "repository"


class AnalyticsService:
    """Validate aggregate requests and execute SQL before evidence lookup."""

    def __init__(
        self,
        repository: Any,
        user_id: str | None = None,
        *,
        evidence_limit: int = DEFAULT_EVIDENCE_LIMIT,
    ) -> None:
        """Initialize the service with an owner-scoped repository.

        Args:
            repository: Repository exposing ``aggregate`` and optionally
                ``representative_evidence``.
            user_id: Default owner id used when a query does not carry one.
            evidence_limit: Maximum number of representative evidence items.
        """
        if evidence_limit < 1:
            raise ValueError("evidence_limit must be positive")
        self.repository = repository
        self.user_id = user_id
        self.evidence_limit = evidence_limit

    def run(self, query: AggregateQuery) -> AggregateResult:
        """Run a validated SQL aggregate and then load representative evidence.

        Args:
            query: Structured aggregate request.

        Returns:
            Aggregate rows, exact SQL coverage, cap status, and evidence.

        Raises:
            ValueError: If a metric, dimension, order, or owner is invalid.
        """
        self._validate_query(query)
        owner_id = query.user_id or self.user_id
        if not owner_id:
            raise ValueError("user_id is required for analytics")
        aggregate = getattr(self.repository, "aggregate", None)
        if not callable(aggregate):
            raise TypeError("repository must expose aggregate")

        raw_result = aggregate(owner_id, query.project_ids, query)
        result = self._coerce_result(raw_result, query)
        if result.evidence:
            return result

        representative_loader = _optional_method(
            self.repository,
            "representative_evidence",
        )
        if not callable(representative_loader):
            return result
        raw_evidence = representative_loader(
            owner_id,
            query.project_ids,
            query,
            self.evidence_limit,
        )
        evidence = _coerce_evidence(raw_evidence or [])
        return result.model_copy(update={"evidence": evidence})

    @staticmethod
    def _validate_query(query: AggregateQuery) -> None:
        """Reject every aggregate operation outside the SQL whitelist."""
        if query.metric not in ALLOWED_METRICS:
            raise ValueError(f"metric {query.metric!r} is not allowed")
        if query.dimension not in ALLOWED_DIMENSIONS:
            raise ValueError(f"dimension {query.dimension!r} is not allowed")
        if query.order not in ALLOWED_ORDERS:
            raise ValueError(f"order {query.order!r} is not allowed")

    @staticmethod
    def _coerce_result(raw_result: Any, query: AggregateQuery) -> AggregateResult:
        """Normalize repository rows into the public aggregate result model."""
        if isinstance(raw_result, AggregateResult):
            return raw_result.model_copy(
                update={"metric": query.metric, "dimension": query.dimension}
            )
        if isinstance(raw_result, Mapping):
            raw_rows = raw_result.get("rows") or []
            raw_coverage = raw_result.get("coverage")
            raw_evidence = raw_result.get("evidence") or []
            rows = [
                row if isinstance(row, AggregateRow) else AggregateRow.model_validate(row)
                for row in raw_rows
            ]
            coverage = (
                raw_coverage
                if isinstance(raw_coverage, Coverage)
                else Coverage.model_validate(raw_coverage or _empty_coverage(query.filters))
            )
            evidence = _coerce_evidence(raw_evidence)
            return AggregateResult(
                rows=rows,
                coverage=coverage,
                capped=bool(raw_result.get("capped", False)),
                evidence=evidence,
                metric=query.metric,
                dimension=query.dimension,
            )
        if isinstance(raw_result, list):
            rows = [
                row if isinstance(row, AggregateRow) else AggregateRow.model_validate(row)
                for row in raw_result
            ]
            return AggregateResult(
                rows=rows,
                coverage=_empty_coverage(query.filters),
                metric=query.metric,
                dimension=query.dimension,
            )
        raise TypeError("repository aggregate must return a mapping or AggregateResult")


def _empty_coverage(filters: QueryFilters) -> dict[str, Any]:
    """Build a safe zero-count coverage object for adapter fallbacks."""
    return {
        "repositories": list(filters.repositories),
        "date_from": filters.date_from,
        "date_to": filters.date_to,
        "counts": {source_type.value: 0 for source_type in SourceType},
    }


def _coerce_evidence(items: Any) -> list[Evidence]:
    """Normalize repository evidence rows into typed evidence objects."""
    if not isinstance(items, list | tuple):
        return []
    return [
        item if isinstance(item, Evidence) else Evidence.model_validate(item)
        for item in items
    ]


def _optional_method(instance: Any, name: str) -> Any:
    """Read an optional adapter method without triggering dynamic mocks."""
    instance_attributes = getattr(instance, "__dict__", {})
    if name in instance_attributes:
        return instance_attributes[name]
    if any(name in parent.__dict__ for parent in type(instance).__mro__):
        return getattr(instance, name, None)
    return None


__all__ = [
    "ALLOWED_DIMENSIONS",
    "ALLOWED_METRICS",
    "ALLOWED_ORDERS",
    "AggregateQuery",
    "AggregateResult",
    "AggregateRow",
    "AnalyticsService",
]
