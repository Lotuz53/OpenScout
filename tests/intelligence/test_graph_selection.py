from datetime import datetime, timedelta, timezone

from docsgpt.intelligence.graph_selection import select_graph_records, signal_score
from docsgpt.intelligence.schemas import IntelligenceRecord, SourceType


RETRIEVED_AT = datetime(2026, 9, 16, tzinfo=timezone.utc)


def _record(
    source_type: SourceType,
    external_id: str,
    *,
    comments_count: int = 0,
    reactions_count: int = 0,
    updated_at: datetime | None = None,
) -> IntelligenceRecord:
    """Build one persisted record for graph-selection tests."""
    return IntelligenceRecord(
        id=f"{source_type.value}:{external_id}",
        repository="owner/repo",
        source_type=source_type,
        external_id=external_id,
        title=f"{source_type.value} {external_id}",
        body="Graph evidence.",
        source_url=f"https://github.com/owner/repo/{source_type.value}/{external_id}",
        comments_count=comments_count,
        reactions_count=reactions_count,
        updated_at=updated_at,
        retrieved_at=RETRIEVED_AT,
        content_hash=f"hash-{source_type.value}-{external_id}",
    )


def test_signal_score_normalizes_comments_and_reactions() -> None:
    assert signal_score(5, 10, 10, 20) == 0.5


def test_graph_subset_caps_issues_but_keeps_docs_and_releases() -> None:
    issues = [
        _record(
            SourceType.ISSUE,
            str(index),
            comments_count=index,
            reactions_count=index,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
            + timedelta(minutes=index),
        )
        for index in range(301)
    ]
    documentation = _record(SourceType.DOCUMENTATION, "README.md")
    release = _record(SourceType.RELEASE, "v1.0.0")
    comment = _record(SourceType.ISSUE_COMMENT, "42:1")

    selected = select_graph_records(
        [comment, *issues, documentation, release],
        issue_limit=300,
    )

    assert len([record for record in selected if record.source_type == SourceType.ISSUE]) == 300
    assert all(
        record in selected
        for record in (documentation, release)
    )
    assert comment not in selected
    selected_issue_ids = {
        record.external_id
        for record in selected
        if record.source_type == SourceType.ISSUE
    }
    assert "0" not in selected_issue_ids
    assert "300" in selected_issue_ids


def test_graph_issue_ties_use_updated_at_then_external_id() -> None:
    older = _record(
        SourceType.ISSUE,
        "20",
        comments_count=1,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    newer = _record(
        SourceType.ISSUE,
        "10",
        comments_count=1,
        updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    same_time_low_id = _record(
        SourceType.ISSUE,
        "2",
        comments_count=1,
        updated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    same_time_high_id = _record(
        SourceType.ISSUE,
        "10a",
        comments_count=1,
        updated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )

    selected = select_graph_records(
        [same_time_high_id, older, same_time_low_id, newer],
        issue_limit=4,
    )

    assert [record.external_id for record in selected] == [
        "10a",
        "2",
        "10",
        "20",
    ]
