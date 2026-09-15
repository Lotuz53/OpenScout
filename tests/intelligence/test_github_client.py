from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.intelligence.github_client import GitHubClient, GitHubRateLimitError


DATE_FROM = datetime(2025, 9, 14, tzinfo=timezone.utc)
DATE_TO = datetime(2026, 9, 14, tzinfo=timezone.utc)


def make_response(payload, *, link: str = "") -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.headers = {"Link": link}
    response.status_code = 200
    return response


def test_iter_issues_filters_pull_requests_and_stops_at_limit() -> None:
    loader = MagicMock()
    loader._make_request.return_value = make_response(
        [
            {"id": 1, "number": 1, "title": "issue", "updated_at": "2026-01-01T00:00:00Z"},
            {"id": 2, "number": 2, "title": "pr", "pull_request": {}},
        ]
    )
    client = GitHubClient(loader=loader)

    rows = list(client.iter_issues("o/r", DATE_FROM, DATE_TO, limit=1))

    assert [row["id"] for row in rows] == [1]
    loader._make_request.assert_called_once_with(
        "https://api.github.com/repos/o/r/issues",
        params={"state": "all", "per_page": 100, "page": 1},
    )


def test_iter_issues_follows_next_page_until_limit() -> None:
    loader = MagicMock()
    loader._make_request.side_effect = [
        make_response(
            [{"id": 1, "updated_at": "2026-01-01T00:00:00Z"}],
            link='<https://api.github.com/repos/o/r/issues?page=2>; rel="next"',
        ),
        make_response([{"id": 2, "updated_at": "2026-01-02T00:00:00Z"}]),
    ]
    client = GitHubClient(loader=loader)

    rows = list(client.iter_issues("o/r", DATE_FROM, DATE_TO, limit=2))

    assert [row["id"] for row in rows] == [1, 2]
    assert loader._make_request.call_count == 2


def test_iter_comments_returns_oldest_limited_comments() -> None:
    loader = MagicMock()
    loader._make_request.return_value = make_response(
        [
            {"id": 3, "created_at": "2026-01-03T00:00:00Z"},
            {"id": 1, "created_at": "2026-01-01T00:00:00Z"},
            {"id": 2, "created_at": "2026-01-02T00:00:00Z"},
        ]
    )
    client = GitHubClient(loader=loader)

    rows = list(client.iter_comments("o/r", 42, limit=2))

    assert [row["id"] for row in rows] == [1, 2]


@patch("docsgpt.parser.remote.github_loader.requests.get")
def test_rate_limit_is_recoverable(mock_get) -> None:
    response = MagicMock()
    response.status_code = 403
    response.json.return_value = {"message": "API rate limit exceeded"}
    response.headers = {
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": "1800000000",
    }
    mock_get.return_value = response

    with pytest.raises(GitHubRateLimitError) as exc:
        list(GitHubClient().iter_releases("o/r", DATE_FROM, DATE_TO))

    assert exc.value.reset_at.timestamp() == 1800000000
