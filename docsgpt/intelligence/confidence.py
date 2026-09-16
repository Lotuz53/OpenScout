"""Deterministic confidence rules for OpenScout claims."""

from __future__ import annotations

from collections.abc import Sequence

from docsgpt.intelligence.schemas import (
    Claim,
    ClaimKind,
    Confidence,
    Coverage,
    Evidence,
    SourceType,
)


_OFFICIAL_SOURCE_TYPES = {SourceType.DOCUMENTATION, SourceType.RELEASE}
_COMMUNITY_SOURCE_TYPES = {SourceType.ISSUE, SourceType.ISSUE_COMMENT}


def confidence_for_claim(
    claim: Claim,
    evidence: Sequence[Evidence],
    coverage: Coverage,
    has_conflict: bool,
) -> Confidence:
    """Calculate confidence from source and coverage facts, never model input.

    Official documentation or release evidence directly supports a factual
    claim at high confidence. A complete, uncapped statistic is high
    confidence because its value is produced by SQL. Community-only support
    reaches medium confidence only when at least two distinct Issue authors
    corroborate it. Inferences, conflicts, stale coverage, and weaker support
    remain low confidence.

    Args:
        claim: Generated claim whose self-reported confidence is ignored.
        evidence: Evidence returned for the query.
        coverage: Coverage for the query's data scope.
        has_conflict: Whether the claim has conflicting supporting sources.

    Returns:
        One deterministic ``Confidence`` label.
    """
    cited = [item for item in evidence if item.id in set(claim.evidence_ids)]
    if claim.kind == ClaimKind.INFERENCE or not cited:
        return Confidence.LOW
    if has_conflict or _coverage_is_stale(coverage):
        return Confidence.LOW
    if any(item.source_type in _OFFICIAL_SOURCE_TYPES for item in cited):
        return Confidence.HIGH
    if claim.kind == ClaimKind.STATISTIC:
        return Confidence.HIGH if not coverage.capped else Confidence.LOW

    issue_authors = {
        item.author.strip().casefold()
        for item in cited
        if item.source_type in _COMMUNITY_SOURCE_TYPES
        and item.author is not None
        and item.author.strip()
    }
    if len(issue_authors) >= 2:
        return Confidence.MEDIUM
    return Confidence.LOW


def _coverage_is_stale(coverage: Coverage) -> bool:
    """Detect a query window that extends beyond its last successful sync."""
    if coverage.last_synced_at is None or coverage.date_to is None:
        return False
    return coverage.last_synced_at.date() < coverage.date_to


__all__ = ["confidence_for_claim"]
