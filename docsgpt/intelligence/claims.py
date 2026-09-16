"""Deterministic validation for generated OpenScout claims."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from docsgpt.intelligence.schemas import Claim, ClaimKind, Coverage, Evidence


@dataclass(frozen=True)
class ClaimValidation:
    """Validation details for one generated claim collection.

    ``valid_claims`` is intentionally retained when another claim is invalid.
    Query callers can therefore show supported evidence while refusing only the
    unsupported part of a response.
    """

    claims: list[Claim]
    valid_claims: list[Claim]
    invalid_claims: list[Claim]
    unknown_evidence_ids: dict[str, list[str]]
    missing_evidence_claim_ids: list[str]

    @property
    def valid(self) -> bool:
        """Return whether every generated claim is supported by the response."""
        return not self.invalid_claims

    @property
    def is_valid(self) -> bool:
        """Return the validation status under a descriptive alias."""
        return self.valid

    @property
    def needs_regeneration(self) -> bool:
        """Return whether the generator should be given one retry."""
        return not self.valid

    @property
    def invalid_claim_ids(self) -> list[str]:
        """Return invalid claim ids in their original response order."""
        return [claim.id for claim in self.invalid_claims]


def validate_claims(
    claims: Sequence[Claim],
    evidence: Sequence[Evidence],
    coverage: Coverage,
) -> ClaimValidation:
    """Validate every claim citation against the returned evidence ids.

    Facts and statistics require at least one citation. Inference claims may
    be uncited, but any citation they do provide must still refer to returned
    evidence. ``coverage`` remains part of the interface so SQL-backed
    validation can use the same boundary without changing query callers.

    Args:
        claims: Generated claims to validate.
        evidence: Evidence returned for the same query.
        coverage: Coverage for the query's data scope.

    Returns:
        A validation result that separates supported claims from claims that
        cannot be safely displayed as factual conclusions.
    """
    del coverage
    claim_list = list(claims)
    evidence_ids = {item.id for item in evidence}
    valid_claims: list[Claim] = []
    invalid_claims: list[Claim] = []
    unknown_evidence_ids: dict[str, list[str]] = {}
    missing_evidence_claim_ids: list[str] = []

    for claim in claim_list:
        unknown = sorted(set(claim.evidence_ids) - evidence_ids)
        missing = claim.kind in {ClaimKind.FACT, ClaimKind.STATISTIC} and not claim.evidence_ids
        if unknown:
            unknown_evidence_ids[claim.id] = unknown
        if missing:
            missing_evidence_claim_ids.append(claim.id)
        if unknown or missing:
            invalid_claims.append(claim)
        else:
            valid_claims.append(claim)

    return ClaimValidation(
        claims=claim_list,
        valid_claims=valid_claims,
        invalid_claims=invalid_claims,
        unknown_evidence_ids=unknown_evidence_ids,
        missing_evidence_claim_ids=missing_evidence_claim_ids,
    )


__all__ = ["ClaimValidation", "validate_claims"]
