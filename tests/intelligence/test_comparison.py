"""Tests for evidence-backed OpenScout product comparison."""

from datetime import date, datetime, timezone

from docsgpt.intelligence.comparison import ComparisonService
from docsgpt.intelligence.schemas import QueryFilters


PROJECT_IDS = ["project-dify", "project-ragflow", "project-fastgpt"]
FILTERS = QueryFilters()


class FakeComparisonRepository:
    """Return fixed owner-scoped rows for comparison service tests."""

    def __init__(self) -> None:
        self.rows = [
            {
                "id": "release-dify-1",
                "repository": "langgenius/dify",
                "source_type": "release",
                "title": "Enterprise SSO support",
                "body": "Enterprise SSO supports SAML and OIDC.",
                "source_url": "https://github.com/langgenius/dify/releases/1",
                "occurred_at": datetime(2026, 1, 4, tzinfo=timezone.utc),
                "comments_count": 0,
                "reactions_count": 2,
            },
            {
                "id": "issue-dify-1",
                "repository": "langgenius/dify",
                "source_type": "issue",
                "title": "SSO login feedback",
                "body": "Enterprise SSO works for our team.",
                "source_url": "https://github.com/langgenius/dify/issues/1",
                "occurred_at": datetime(2026, 1, 8, tzinfo=timezone.utc),
                "comments_count": 3,
                "reactions_count": 1,
            },
            {
                "id": "release-ragflow-1",
                "repository": "infiniflow/ragflow",
                "source_type": "release",
                "title": "Enterprise authentication",
                "body": "Enterprise SSO is not supported in this release.",
                "source_url": "https://github.com/infiniflow/ragflow/releases/1",
                "occurred_at": datetime(2026, 2, 4, tzinfo=timezone.utc),
                "comments_count": 0,
                "reactions_count": 0,
            },
            {
                "id": "issue-fastgpt-1",
                "repository": "labring/FastGPT",
                "source_type": "issue",
                "title": "Improve workflow editor",
                "body": "The workflow editor needs better validation.",
                "source_url": "https://github.com/labring/FastGPT/issues/1",
                "occurred_at": datetime(2026, 3, 4, tzinfo=timezone.utc),
                "comments_count": 2,
                "reactions_count": 5,
            },
        ]

    def repositories_for_projects(self, user_id, project_ids):
        assert user_id == "user-1"
        assert project_ids == PROJECT_IDS
        return ["langgenius/dify", "infiniflow/ragflow", "labring/FastGPT"]

    def comparison_evidence(self, user_id, project_ids, filters):
        assert user_id == "user-1"
        assert project_ids == PROJECT_IDS
        assert filters == FILTERS
        return self.rows

    def comparison_coverage(self, user_id, project_ids, filters):
        assert user_id == "user-1"
        assert project_ids == PROJECT_IDS
        assert filters == FILTERS
        return {
            "langgenius/dify": {"warning": None},
            "infiniflow/ragflow": {"warning": "部分同步"},
            "labring/FastGPT": {"warning": "数据覆盖不足"},
        }


def test_comparison_uses_unknown_without_supporting_evidence() -> None:
    service = ComparisonService(FakeComparisonRepository(), user_id="user-1")

    result = service.compare(PROJECT_IDS, ["enterprise_sso"], FILTERS)
    cell = result.rows[0].cells["labring/FastGPT"]

    assert cell.status == "unknown"
    assert cell.display_label == "尚未确认"
    assert cell.evidence_ids == []
    assert cell.coverage_warning == "数据覆盖不足"


def test_comparison_requires_evidence_for_supported_and_not_supported_cells() -> None:
    service = ComparisonService(FakeComparisonRepository(), user_id="user-1")

    result = service.compare(PROJECT_IDS, ["enterprise_sso"], FILTERS)
    dify = result.rows[0].cells["langgenius/dify"]
    ragflow = result.rows[0].cells["infiniflow/ragflow"]

    assert dify.status == "supported"
    assert dify.evidence_ids == ["release-dify-1", "issue-dify-1"]
    assert dify.first_evidence_date == date(2026, 1, 4)
    assert dify.community_signal_count == 1
    assert ragflow.status == "not_supported"
    assert ragflow.evidence_ids == ["release-ragflow-1"]
    assert ragflow.coverage_warning == "部分同步"


def test_comparison_marks_conflicting_evidence_unknown() -> None:
    repository = FakeComparisonRepository()
    repository.rows.extend(
        [
            {
                "id": "release-fastgpt-positive",
                "repository": "labring/FastGPT",
                "source_type": "release",
                "title": "SSO support",
                "body": "Enterprise SSO is supported.",
                "source_url": "https://github.com/labring/FastGPT/releases/2",
                "occurred_at": datetime(2026, 4, 4, tzinfo=timezone.utc),
                "comments_count": 0,
                "reactions_count": 0,
            },
            {
                "id": "issue-fastgpt-negative",
                "repository": "labring/FastGPT",
                "source_type": "issue",
                "title": "SSO unavailable",
                "body": "Enterprise SSO is not supported.",
                "source_url": "https://github.com/labring/FastGPT/issues/2",
                "occurred_at": datetime(2026, 5, 4, tzinfo=timezone.utc),
                "comments_count": 1,
                "reactions_count": 0,
            },
        ]
    )

    result = ComparisonService(repository, user_id="user-1").compare(
        PROJECT_IDS,
        ["enterprise_sso"],
        FILTERS,
    )

    cell = result.rows[0].cells["labring/FastGPT"]
    assert cell.status == "unknown"
    assert cell.display_label == "尚未确认"
    assert cell.evidence_ids == ["release-fastgpt-positive", "issue-fastgpt-negative"]
