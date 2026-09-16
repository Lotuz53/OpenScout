"""Tests for deterministic per-claim confidence scoring."""

from datetime import date, datetime, timezone

import pytest

from docsgpt.intelligence.confidence import confidence_for_claim
from docsgpt.intelligence.schemas import (
    Claim,
    ClaimKind,
    Confidence,
    Coverage,
    Evidence,
    SourceType,
)


def _evidence(
    evidence_id: str,
    source_type: SourceType,
    *,
    author: str | None = None,
) -> Evidence:
    """Build one deterministic evidence item for confidence tests."""
    return Evidence(
        id=evidence_id,
        record_id=f"{source_type.value}:{evidence_id}",
        repository="langgenius/dify",
        source_type=source_type,
        title=evidence_id,
        excerpt="Evidence excerpt.",
        source_url=f"https://github.com/langgenius/dify/{source_type.value}/{evidence_id}",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        author=author,
    )


def _claim(kind: ClaimKind, evidence_ids: list[str]) -> Claim:
    """Build a claim whose model confidence is intentionally untrusted."""
    return Claim(
        id="claim-1",
        text="Dify supports the feature.",
        kind=kind,
        evidence_ids=evidence_ids,
        confidence=Confidence.HIGH,
    )


def _coverage(*, capped: bool = False) -> Coverage:
    """Build complete or capped coverage for one repository."""
    return Coverage(
        repositories=["langgenius/dify"],
        date_from=None,
        date_to=None,
        counts={SourceType.ISSUE: 2, SourceType.RELEASE: 1},
        capped=capped,
    )


def official_release_case() -> dict:
    """Return a directly supported official-release case."""
    return {
        "claim": _claim(ClaimKind.FACT, ["release-1"]),
        "evidence": [_evidence("release-1", SourceType.RELEASE)],
        "coverage": _coverage(),
        "has_conflict": False,
    }


def complete_sql_case() -> dict:
    """Return a complete SQL statistic case."""
    return {
        "claim": _claim(ClaimKind.STATISTIC, ["issue-1"]),
        "evidence": [_evidence("issue-1", SourceType.ISSUE, author="alice")],
        "coverage": _coverage(),
        "has_conflict": False,
    }


def two_author_issue_case() -> dict:
    """Return two mutually supporting issues from different authors."""
    return {
        "claim": _claim(ClaimKind.FACT, ["issue-1", "issue-2"]),
        "evidence": [
            _evidence("issue-1", SourceType.ISSUE, author="alice"),
            _evidence("issue-2", SourceType.ISSUE, author="bob"),
        ],
        "coverage": _coverage(),
        "has_conflict": False,
    }


def single_issue_case() -> dict:
    """Return a claim supported by one community issue."""
    return {
        "claim": _claim(ClaimKind.FACT, ["issue-1"]),
        "evidence": [_evidence("issue-1", SourceType.ISSUE, author="alice")],
        "coverage": _coverage(),
        "has_conflict": False,
    }


def conflict_case() -> dict:
    """Return a claim whose evidence has an explicit conflict marker."""
    case = official_release_case()
    case["has_conflict"] = True
    return case


def inference_case() -> dict:
    """Return an unsupported AI inference."""
    return {
        "claim": _claim(ClaimKind.INFERENCE, []),
        "evidence": [],
        "coverage": _coverage(),
        "has_conflict": False,
    }


@pytest.mark.parametrize(
    "case,expected",
    [
        (official_release_case(), Confidence.HIGH),
        (complete_sql_case(), Confidence.HIGH),
        (two_author_issue_case(), Confidence.MEDIUM),
        (single_issue_case(), Confidence.LOW),
        (conflict_case(), Confidence.LOW),
        (inference_case(), Confidence.LOW),
    ],
)
def test_confidence_rules(case: dict, expected: Confidence) -> None:
    """Apply the fixed confidence rules without trusting model scores."""
    assert confidence_for_claim(**case) == expected


def test_capped_coverage_does_not_produce_high_sql_confidence() -> None:
    """An incomplete aggregate scope cannot receive a high confidence label."""
    case = complete_sql_case()
    case["coverage"] = _coverage(capped=True)

    assert confidence_for_claim(**case) == Confidence.LOW


def test_stale_coverage_forces_low_confidence() -> None:
    """A query window beyond the last sync cannot receive high confidence."""
    case = official_release_case()
    case["coverage"] = Coverage(
        repositories=["langgenius/dify"],
        date_from=None,
        date_to=date(2026, 2, 1),
        counts={SourceType.RELEASE: 1},
        last_synced_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert confidence_for_claim(**case) == Confidence.LOW
