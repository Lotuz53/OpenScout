"""Deterministic selection of high-signal records for GraphRAG ingestion."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone

from docsgpt.intelligence.schemas import IntelligenceRecord, SourceType


GRAPH_RECORD_TYPES = frozenset(
    {
        SourceType.DOCUMENTATION,
        SourceType.ISSUE,
        SourceType.RELEASE,
    }
)
"""Record types that may be sent to the GraphRAG extraction pipeline."""


def signal_score(
    comments: int,
    reactions: int,
    max_comments: int,
    max_reactions: int,
) -> float:
    """Normalize community activity into a deterministic issue signal score.

    Args:
        comments: Number of comments on the issue.
        reactions: Number of reactions on the issue.
        max_comments: Maximum comment count in the issue comparison set.
        max_reactions: Maximum reaction count in the issue comparison set.

    Returns:
        A weighted score where comments contribute 60% and reactions 40%.
    """
    comment_score = max(0, comments) / max(1, max_comments)
    reaction_score = max(0, reactions) / max(1, max_reactions)
    return 0.6 * comment_score + 0.4 * reaction_score


def _updated_at(record: IntelligenceRecord) -> datetime:
    """Return an aware timestamp suitable for descending deterministic sorting."""
    value = record.updated_at
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sort_issues(
    issues: Sequence[IntelligenceRecord],
) -> list[IntelligenceRecord]:
    """Sort issues by signal, recency, and external id with stable tie breaks."""
    if not issues:
        return []
    max_comments = max(max(0, issue.comments_count) for issue in issues)
    max_reactions = max(max(0, issue.reactions_count) for issue in issues)
    scored = [
        (
            signal_score(
                issue.comments_count,
                issue.reactions_count,
                max_comments,
                max_reactions,
            ),
            issue,
        )
        for issue in issues
    ]
    scored.sort(key=lambda item: str(item[1].external_id))
    scored.sort(key=lambda item: _updated_at(item[1]), reverse=True)
    scored.sort(key=lambda item: item[0], reverse=True)
    return [issue for _, issue in scored]


def select_graph_records(
    records: Sequence[IntelligenceRecord],
    issue_limit: int = 300,
) -> list[IntelligenceRecord]:
    """Select GraphRAG records while capping high-volume issue sources.

    Documentation and release records are always retained. Issue comments are
    excluded because their content is already represented by the bounded issue
    context and comments are not an independent GraphRAG source. Issues are
    ranked separately for each repository using normalized comments and
    reactions, then capped at ``issue_limit`` per repository.

    Args:
        records: Persisted intelligence records to consider.
        issue_limit: Maximum number of issues retained for each repository.

    Returns:
        Documentation, release, and selected issue records in deterministic
        source order.

    Raises:
        ValueError: If ``issue_limit`` is negative.
    """
    if issue_limit < 0:
        raise ValueError("issue_limit must be non-negative")
    records = list(records)

    always_keep = [
        record
        for record in records
        if record.source_type in {
            SourceType.DOCUMENTATION,
            SourceType.RELEASE,
        }
    ]
    issues_by_repository: dict[str, list[IntelligenceRecord]] = defaultdict(list)
    for record in records:
        if record.source_type == SourceType.ISSUE:
            issues_by_repository[record.repository].append(record)

    selected_issues: list[IntelligenceRecord] = []
    for repository in sorted(issues_by_repository):
        selected_issues.extend(
            _sort_issues(issues_by_repository[repository])[:issue_limit]
        )

    return [*always_keep, *selected_issues]


__all__ = ["GRAPH_RECORD_TYPES", "select_graph_records", "signal_score"]
