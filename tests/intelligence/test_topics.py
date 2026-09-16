"""Tests for deterministic OpenScout issue topic clustering."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from docsgpt.intelligence.schemas import IntelligenceRecord, QueryFilters, SourceType
from docsgpt.intelligence.topics import (
    ALGORITHM_VERSION,
    TopicTrend,
    cluster_issues,
    persist_topic_run,
    topic_trends,
)
from docsgpt.storage.db.repositories.intelligence import IntelligenceRepository


RETRIEVED_AT = datetime(2026, 9, 16, tzinfo=timezone.utc)


def _issue(record_id: str, title: str) -> IntelligenceRecord:
    """Build a small deterministic issue record for clustering tests."""
    return IntelligenceRecord(
        id=record_id,
        repository="owner/repo",
        source_type=SourceType.ISSUE,
        external_id=record_id,
        title=title,
        body=title,
        source_url=f"https://github.com/owner/repo/issues/{record_id}",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        retrieved_at=RETRIEVED_AT,
        content_hash=f"hash-{record_id}",
    )


ISSUES = [
    _issue("issue-1", "Enterprise SSO login fails"),
    _issue("issue-2", "Enterprise SSO authentication request"),
    _issue("issue-3", "Billing export is missing"),
    _issue("issue-4", "Billing report download fails"),
]
ISSUE_VECTORS = {
    "issue-1": [1.0, 0.0],
    "issue-2": [0.98, 0.2],
    "issue-3": [0.0, 1.0],
    "issue-4": [0.2, 0.98],
}


def test_cluster_assignment_is_stable_for_input_order() -> None:
    forward = cluster_issues(ISSUES, ISSUE_VECTORS)
    reverse = cluster_issues(list(reversed(ISSUES)), ISSUE_VECTORS)

    assert [(cluster.id, sorted(cluster.record_ids)) for cluster in forward] == [
        (cluster.id, sorted(cluster.record_ids)) for cluster in reverse
    ]


def test_clusters_include_normalized_centroids_and_reproducible_snapshot() -> None:
    clusters = cluster_issues(ISSUES, ISSUE_VECTORS)

    assert len(clusters) == 2
    assert all(abs(sum(value * value for value in cluster.centroid) - 1) < 1e-9 for cluster in clusters)
    assert {cluster.algorithm_version for cluster in clusters} == {ALGORITHM_VERSION}
    assert len({cluster.snapshot_id for cluster in clusters}) == 1
    assert clusters[0].snapshot_id == cluster_issues(ISSUES, ISSUE_VECTORS)[0].snapshot_id


def test_persist_topic_run_keeps_cluster_snapshot_metadata() -> None:
    repository = MagicMock()
    clusters = cluster_issues(ISSUES, ISSUE_VECTORS)

    persist_topic_run(repository, "project-1", clusters)

    repository.save_topic_run.assert_called_once()
    call = repository.save_topic_run.call_args.kwargs
    assert call["project_id"] == "project-1"
    assert call["snapshot_id"] == clusters[0].snapshot_id
    assert call["algorithm_version"] == ALGORITHM_VERSION
    assert call["clusters"][0]["id"] == clusters[0].id


def test_topic_trends_returns_repository_rows() -> None:
    repository = MagicMock()
    repository.topic_trends.return_value = [
        {
            "cluster_id": "topic-1",
            "label": "enterprise / sso",
            "repository": "owner/repo",
            "month": "2026-01",
            "count": 2,
            "snapshot_id": "snapshot-1",
        }
    ]

    result = topic_trends(
        ["project-1"],
        QueryFilters(repositories=["owner/repo"]),
        repository=repository,
        user_id="user-1",
    )

    assert result == [
        TopicTrend(
            cluster_id="topic-1",
            label="enterprise / sso",
            repository="owner/repo",
            month="2026-01",
            count=2,
            snapshot_id="snapshot-1",
        )
    ]
    repository.topic_trends.assert_called_once_with("user-1", ["project-1"], QueryFilters(repositories=["owner/repo"]))


class _FakeRow:
    """Expose the SQLAlchemy row mapping used by the repository boundary."""

    def __init__(self, values: dict[str, object]) -> None:
        self._mapping = values


class _FakeResult:
    """Return fixed rows for repository SQL assertions."""

    def __init__(self, rows: list[_FakeRow]) -> None:
        self.rows = rows

    def fetchall(self) -> list[_FakeRow]:
        """Return all configured rows."""
        return self.rows


class _RecordingConnection:
    """Capture rendered SQL and bound values without opening PostgreSQL."""

    def __init__(self, result: _FakeResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute(self, statement, parameters):
        """Record one SQLAlchemy execution and return its fixed result."""
        self.calls.append((str(statement), parameters))
        return self.result


def test_repository_topic_trends_keeps_owner_and_filter_scope() -> None:
    project_id = "00000000-0000-0000-0000-000000000001"
    connection = _RecordingConnection(
        _FakeResult(
            [
                _FakeRow(
                    {
                        "cluster_id": "topic-1",
                        "label": "sso",
                        "repository": "owner/repo",
                        "month": "2026-01",
                        "count": 2,
                        "snapshot_id": "snapshot-1",
                    }
                )
            ]
        )
    )

    result = IntelligenceRepository(connection).topic_trends(
        "owner",
        [project_id],
        QueryFilters(repositories=["owner/repo"], date_from=datetime(2026, 1, 1).date()),
    )

    sql, params = connection.calls[0]
    assert "tp.user_id = :user_id" in sql
    assert "p.user_id = :user_id" in sql
    assert "tp.id IN (CAST(:project_id_0 AS uuid))" in sql
    assert "r.repository IN (:repository_0)" in sql
    assert "jsonb_array_elements" in sql
    assert params["user_id"] == "owner"
    assert params["project_id_0"] == project_id
    assert result[0]["cluster_id"] == "topic-1"
