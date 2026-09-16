import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from docsgpt.intelligence.normalizer import (
    content_hash,
    is_supported_document,
    normalize_comment,
    normalize_document,
    normalize_issue,
    normalize_release,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "github_objects.json"
UTC_A = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
UTC_B = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("README.md", True),
        ("docs/guide.md", True),
        ("src/main.py", False),
        ("documentation.md", False),
    ],
)
def test_supported_document_scope(path: str, expected: bool) -> None:
    assert is_supported_document(path) is expected


def test_issue_hash_ignores_retrieval_time() -> None:
    raw_issue = {
        "id": 101,
        "number": 7,
        "title": "Add export",
        "body": "Please add an export option.",
        "html_url": "https://github.com/o/r/issues/7",
        "state": "open",
        "labels": [{"name": "feature"}],
        "comments": 2,
        "reactions": {"total_count": 3},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }

    first = normalize_issue("o/r", raw_issue, retrieved_at=UTC_A)
    second = normalize_issue("o/r", raw_issue, retrieved_at=UTC_B)

    assert first.content_hash == second.content_hash


def test_normalize_issue_rejects_pull_requests() -> None:
    with pytest.raises(ValueError, match="outside the intelligence Issue scope"):
        normalize_issue(
            "o/r",
            {"id": 1, "number": 1, "pull_request": {}},
            retrieved_at=UTC_A,
        )


def test_content_hash_is_stable_for_mapping_order() -> None:
    assert content_hash(" body ", {"b": 2, "a": 1}) == content_hash("body", {"a": 1, "b": 2})


def _normalize_fixture_records(fixture: dict) -> list[dict]:
    retrieved_at = datetime.fromisoformat(fixture["retrieved_at"].replace("Z", "+00:00"))
    records = []
    records.extend(
        normalize_document(
            item["repository"],
            item["path"],
            item["body"],
            item["source_url"],
            retrieved_at,
        ).model_dump(mode="json")
        for item in fixture["documents"]
    )
    records.extend(
        normalize_issue(item["repository"], item["raw"], retrieved_at).model_dump(mode="json")
        for item in fixture["issues"]
    )
    records.extend(
        normalize_comment(item["repository"], item["issue_number"], item["raw"], retrieved_at).model_dump(mode="json")
        for item in fixture["comments"]
    )
    records.extend(
        normalize_release(item["repository"], item["raw"], retrieved_at).model_dump(mode="json")
        for item in fixture["releases"]
    )
    return records


def test_normalized_fixture_matches_expected_json() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    actual = _normalize_fixture_records(fixture)

    assert len(actual) == 20
    assert actual == fixture["expected"]
