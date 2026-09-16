"""Contract tests for public GitHub repository preflight checks."""

from unittest.mock import MagicMock

import pytest

from docsgpt.intelligence.preflight import (
    RepositoryPreflight,
    RepositoryPreflightService,
)


@pytest.fixture
def github() -> MagicMock:
    """Provide the GitHub metadata client used by the preflight service."""
    return MagicMock()


@pytest.mark.parametrize(
    "status,private,expected",
    [
        (404, False, "not_found"),
        (200, True, "private_not_supported"),
        (200, False, None),
    ],
)
def test_preflight_classifies_repository(
    status: int,
    private: bool,
    expected: str | None,
    github: MagicMock,
) -> None:
    """Classify missing, private, and usable repositories distinctly."""
    github.repository_metadata.return_value = {
        "status": status,
        "private": private,
        "archived": False,
    }

    result = RepositoryPreflightService(github).check("https://github.com/o/r")

    assert result.error_code == expected


def test_preflight_passes_normalized_repository_to_github(github: MagicMock) -> None:
    """Repository URLs are normalized before metadata lookup."""
    github.repository_metadata.return_value = {
        "status": 200,
        "private": False,
        "archived": False,
    }

    result = RepositoryPreflightService(github).check(
        "https://github.com/o/r.git/"
    )

    assert result.repository == "o/r"
    github.repository_metadata.assert_called_once_with("o/r")


def test_preflight_reports_scope_warnings_and_estimates(github: MagicMock) -> None:
    """Expose archive, empty, estimate, and collection-cap information."""
    github.repository_metadata.return_value = {
        "status": 200,
        "private": False,
        "archived": True,
        "empty": True,
        "default_branch": "master",
        "estimated_counts": {"issues": 1000, "releases": 4, "documents": 12},
        "warnings": ["部分数量估算暂不可用"],
    }

    result = RepositoryPreflightService(github).check("o/r")

    assert result == RepositoryPreflight(
        repository="o/r",
        default_branch="master",
        archived=True,
        estimated_counts={"issues": 1000, "releases": 4, "documents": 12},
        warnings=[
            "部分数量估算暂不可用",
            "该仓库已归档，数据可能不会继续更新。",
            "该仓库目前为空，首次同步可能没有可用内容。",
            "Issue 数量达到 1000 条上限，首次同步将按上限采集。",
        ],
    )


def test_preflight_rejects_non_github_repository(github: MagicMock) -> None:
    """Reject arbitrary URLs before making an external request."""
    result = RepositoryPreflightService(github).check("https://example.com/o/r")

    assert result.error_code == "invalid_repository"
    github.repository_metadata.assert_not_called()
