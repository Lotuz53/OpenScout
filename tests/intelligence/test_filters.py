"""Tests for explicit and inferred OpenScout metadata filters."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from docsgpt.intelligence.filters import compile_metadata_filter, merge_filters
from docsgpt.intelligence.query_service import QueryService
from docsgpt.intelligence.schemas import (
    Coverage,
    Evidence,
    QueryFilters,
    QueryRequest,
    SourceType,
)


def _evidence() -> Evidence:
    """Return one source item for query filter integration assertions."""
    return Evidence(
        id="evidence-1",
        record_id="issue:1",
        repository="langgenius/dify",
        source_type=SourceType.ISSUE,
        title="Add export",
        excerpt="Please add an export option.",
        source_url="https://github.com/langgenius/dify/issues/101",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_explicit_filters_override_inferred_dates() -> None:
    explicit = QueryFilters(
        repositories=["langgenius/dify"],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 2, 1),
    )
    inferred = QueryFilters(
        repositories=["infiniflow/ragflow"],
        date_from=date(2025, 1, 1),
        date_to=date(2025, 12, 31),
    )

    merged = merge_filters(explicit, inferred)

    assert merged.repositories == ["langgenius/dify"]
    assert merged.date_from == date(2026, 1, 1)
    assert merged.date_to == date(2026, 2, 1)


def test_inferred_filters_fill_missing_explicit_values() -> None:
    merged = merge_filters(
        QueryFilters(repositories=["langgenius/dify"]),
        QueryFilters(
            source_types=[SourceType.ISSUE],
            date_from=date(2026, 1, 1),
        ),
    )

    assert merged.repositories == ["langgenius/dify"]
    assert merged.source_types == [SourceType.ISSUE]
    assert merged.date_from == date(2026, 1, 1)


def test_compile_metadata_filter_uses_index_metadata_fields() -> None:
    compiled = compile_metadata_filter(
        QueryFilters(
            repositories=["langgenius/dify"],
            source_types=[SourceType.ISSUE, SourceType.RELEASE],
            date_from=date(2026, 1, 1),
            date_to=date(2026, 2, 1),
        )
    )

    assert compiled == {
        "repository": {"$in": ["langgenius/dify"]},
        "source_type": {"$in": ["issue", "release"]},
        "occurred_at": {"$gte": "2026-01-01", "$lt": "2026-02-02"},
    }


def test_query_trace_keeps_filter_values_and_sources() -> None:
    retriever = MagicMock()
    retriever.retrieve.return_value = [_evidence()]
    generator = MagicMock()
    generator.generate.return_value = {"answer": "supported", "claims": []}

    def coverage(filters: QueryFilters) -> Coverage:
        return Coverage(
            repositories=filters.repositories,
            date_from=filters.date_from,
            date_to=filters.date_to,
            counts={SourceType.ISSUE: 1},
        )

    service = QueryService(
        retriever=retriever,
        generator=generator,
        coverage=coverage,
        filter_inferer=lambda question: QueryFilters(
            repositories=["infiniflow/ragflow"],
            date_from=date(2025, 1, 1),
        ),
    )
    request = QueryRequest(
        question="Which issue was opened?",
        filters=QueryFilters(date_from=date(2026, 1, 1)),
    )

    result = service.query(request, "user-1")

    effective = retriever.retrieve.call_args.args[1]
    assert effective.repositories == ["infiniflow/ragflow"]
    assert effective.date_from == date(2026, 1, 1)
    assert result.trace.applied_filters == effective
    assert result.trace.explicit_filters == request.filters
    assert result.trace.inferred_filters.date_from == date(2025, 1, 1)
    assert {item.source for item in result.trace.filter_sources} == {
        "explicit",
        "inferred",
    }
