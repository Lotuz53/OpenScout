"""Tests for whitelist-only OpenScout SQL analytics."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from docsgpt.intelligence.analytics import (
    AggregateQuery,
    AggregateResult,
    AnalyticsService,
)
from docsgpt.intelligence.query_router import QueryRouter, RouteDecision
from docsgpt.intelligence.query_service import QueryService
from docsgpt.intelligence.schemas import (
    Coverage,
    Evidence,
    QueryFilters,
    QueryIntent,
    QueryRequest,
    RetrievalStrategy,
    SourceType,
)
from docsgpt.storage.db.repositories.intelligence import IntelligenceRepository


def _coverage() -> Coverage:
    """Return a deterministic aggregate coverage object."""
    return Coverage(
        repositories=["langgenius/dify"],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        counts={SourceType.ISSUE: 3},
    )


def _evidence() -> Evidence:
    """Return one representative evidence item."""
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


class FakeRepository:
    """Record the required SQL-first analytics call order."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def aggregate(self, user_id, project_ids, query):
        """Return SQL-shaped rows before representative evidence."""
        assert user_id == "owner"
        assert project_ids == ["project-1"]
        self.calls.append("aggregate")
        return {
            "rows": [{"dimension": "langgenius/dify", "value": 3}],
            "coverage": _coverage(),
            "capped": False,
        }

    def representative_evidence(self, user_id, project_ids, query, limit):
        """Return evidence only after the aggregate query has completed."""
        assert self.calls == ["aggregate"]
        assert user_id == "owner"
        assert project_ids == ["project-1"]
        assert limit == 5
        self.calls.append("representative_evidence")
        return [_evidence()]


class FakeRow:
    """Expose the SQLAlchemy row mapping used by the repository boundary."""

    def __init__(self, values: dict) -> None:
        self._mapping = values


class FakeResult:
    """Return deterministic rows for repository SQL assertions."""

    def __init__(self, rows: list[FakeRow]) -> None:
        self.rows = rows

    def fetchall(self) -> list[FakeRow]:
        """Return all configured rows."""
        return self.rows

    def fetchone(self) -> FakeRow | None:
        """Return the first configured row."""
        return self.rows[0] if self.rows else None


class RecordingConnection:
    """Capture SQL and parameters without replacing the production repository."""

    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict]] = []

    def execute(self, statement, parameters):
        """Record a SQLAlchemy statement and return its prepared result."""
        self.calls.append((str(statement), parameters))
        return self.results.pop(0)


def test_analytics_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError, match="dimension"):
        AnalyticsService(FakeRepository(), user_id="owner").run(
            AggregateQuery(metric="count", dimension="body")
        )


def test_analytics_uses_whitelisted_sql_result_and_then_evidence() -> None:
    repository = FakeRepository()
    result = AnalyticsService(repository, user_id="owner").run(
        AggregateQuery(
            metric="count",
            dimension="repository",
            project_ids=["project-1"],
            order="value_desc",
        )
    )

    assert isinstance(result, AggregateResult)
    assert result.rows[0].dimension == "langgenius/dify"
    assert result.rows[0].value == 3
    assert result.coverage == _coverage()
    assert result.capped is False
    assert result.evidence == [_evidence()]
    assert repository.calls == ["aggregate", "representative_evidence"]


@pytest.mark.parametrize("metric", ["count", "median_comments", "sum_reactions"])
def test_analytics_accepts_only_supported_metrics(metric: str) -> None:
    repository = FakeRepository()
    result = AnalyticsService(repository, user_id="owner").run(
        AggregateQuery(
            metric=metric,
            dimension="repository",
            project_ids=["project-1"],
        )
    )

    assert result.rows[0].value == 3


def test_analytics_rejects_unknown_order() -> None:
    with pytest.raises(ValueError, match="order"):
        AnalyticsService(FakeRepository(), user_id="owner").run(
            AggregateQuery(metric="count", dimension="repository", order="random")
        )


def test_repository_aggregate_keeps_owner_scope_and_parameterized_filters() -> None:
    connection = RecordingConnection(
        [
            FakeResult(
                [
                    FakeRow(
                        {
                            "dimension": "langgenius/dify",
                            "value": 3,
                            "total_groups": 1,
                        }
                    )
                ]
            ),
            FakeResult(
                [
                    FakeRow(
                        {
                            "repositories": ["langgenius/dify"],
                            "date_from": date(2026, 1, 1),
                            "date_to": date(2026, 1, 31),
                            "documentation_count": 0,
                            "issue_count": 3,
                            "issue_comment_count": 0,
                            "release_count": 0,
                        }
                    )
                ]
            ),
        ]
    )
    project_ids = [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    query = AggregateQuery(
        metric="count",
        dimension="repository",
        project_ids=project_ids,
        filters=QueryFilters(
            repositories=["langgenius/dify"],
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        ),
    )

    result = IntelligenceRepository(connection).aggregate("owner", project_ids, query)

    sql, params = connection.calls[0]
    assert "p.user_id = :user_id" in sql
    assert "p.id IN (CAST(:project_id_0 AS uuid), CAST(:project_id_1 AS uuid))" in sql
    assert "r.repository IN (:repository_0)" in sql
    assert "::date >= :date_from" in sql
    assert "::date <= :date_to" in sql
    assert params["user_id"] == "owner"
    assert result["rows"] == [{"dimension": "langgenius/dify", "value": 3}]
    assert result["coverage"]["counts"]["issue"] == 3


def test_query_service_keeps_sql_value_and_representative_evidence() -> None:
    evidence = _evidence()
    retriever = MagicMock()
    generator = MagicMock()
    generator.generate.return_value = {
        "answer": "The evidence explains the result.",
        "claims": [],
    }
    analytics = MagicMock()
    analytics.run.return_value = AggregateResult(
        rows=[{"dimension": "langgenius/dify", "value": 3}],
        coverage=_coverage(),
        evidence=[evidence],
    )
    router = QueryRouter(
        parser=lambda request: RouteDecision(
            intent=QueryIntent.AGGREGATE,
            strategy=RetrievalStrategy.SQL_PLUS_HYBRID,
            confidence=0.9,
        )
    )

    result = QueryService(
        retriever=retriever,
        generator=generator,
        router=router,
        analytics=analytics,
    ).query(QueryRequest(question="How many issues mention export?"), "owner")

    assert "3" in result.answer
    assert result.evidence == [evidence]
    assert len(result.claims) == 1
    assert result.claims[0].kind == "statistic"
    assert result.claims[0].evidence_ids == [evidence.id]
    analytics.run.assert_called_once()
    retriever.retrieve.assert_not_called()
