"""Explicit and inferred metadata filters for intelligence retrieval."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from docsgpt.intelligence.schemas import FilterSource, QueryFilters


FILTER_FIELDS = ("repositories", "source_types", "date_from", "date_to")


def _has_value(value: Any) -> bool:
    """Return whether a filter field contributes an effective constraint."""
    return bool(value) if isinstance(value, list) else value is not None


def _validate_date_range(filters: QueryFilters) -> QueryFilters:
    """Reject an effective date range whose end precedes its start."""
    if (
        filters.date_from is not None
        and filters.date_to is not None
        and filters.date_to < filters.date_from
    ):
        raise ValueError("date_to must not be before date_from")
    return filters


def merge_filters(explicit: QueryFilters, inferred: QueryFilters) -> QueryFilters:
    """Merge filters with non-empty explicit values taking precedence.

    Empty lists and null dates mean that the caller did not constrain that
    field, so an inferred value may fill it. The input models are never
    mutated.
    """
    merged = QueryFilters(
        repositories=list(explicit.repositories or inferred.repositories),
        source_types=list(explicit.source_types or inferred.source_types),
        date_from=explicit.date_from or inferred.date_from,
        date_to=explicit.date_to or inferred.date_to,
    )
    return _validate_date_range(merged)


def compile_metadata_filter(filters: QueryFilters) -> dict[str, Any]:
    """Compile query filters for source and vector metadata adapters.

    The field names match the metadata emitted by intelligence indexing:
    repository, source_type, and occurred_at. Empty constraints are omitted so
    existing retrievers can continue to use their unfiltered path.
    """
    compiled: dict[str, Any] = {}
    if filters.repositories:
        compiled["repository"] = {"$in": list(filters.repositories)}
    if filters.source_types:
        compiled["source_type"] = {
            "$in": [source_type.value for source_type in filters.source_types]
        }
    occurred_at: dict[str, str] = {}
    if filters.date_from is not None:
        occurred_at["$gte"] = filters.date_from.isoformat()
    if filters.date_to is not None:
        occurred_at["$lt"] = (filters.date_to + timedelta(days=1)).isoformat()
    if occurred_at:
        compiled["occurred_at"] = occurred_at
    return compiled


def _serializable_value(value: Any) -> Any:
    """Convert enum and date filter values into trace-safe JSON values."""
    if isinstance(value, list):
        return [_serializable_value(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return getattr(value, "value", value)


def filter_provenance(
    explicit: QueryFilters,
    inferred: QueryFilters,
) -> list[FilterSource]:
    """Record each supplied filter value and whether it was explicit or inferred."""
    provenance: list[FilterSource] = []
    for field_name in FILTER_FIELDS:
        explicit_value = getattr(explicit, field_name)
        inferred_value = getattr(inferred, field_name)
        if _has_value(explicit_value):
            provenance.append(
                FilterSource(
                    field=field_name,
                    value=_serializable_value(explicit_value),
                    source="explicit",
                )
            )
        if _has_value(inferred_value):
            provenance.append(
                FilterSource(
                    field=field_name,
                    value=_serializable_value(inferred_value),
                    source="inferred",
                )
            )
    return provenance


__all__ = [
    "FILTER_FIELDS",
    "compile_metadata_filter",
    "filter_provenance",
    "merge_filters",
]
