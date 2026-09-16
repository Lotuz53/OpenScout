"""Evidence-backed product comparison for OpenScout intelligence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from docsgpt.intelligence.schemas import IntelligenceModel, QueryFilters, SourceType


ComparisonStatus = Literal["supported", "not_supported", "unknown"]

_STATUS_LABELS = {
    "supported": "已支持",
    "not_supported": "不支持",
    "unknown": "尚未确认",
}
_FEATURE_ALIASES = {
    "enterprise_sso": ("enterprise sso", "sso", "single sign-on", "saml", "oidc"),
}
_POSITIVE_CUES = (
    "support",
    "supported",
    "available",
    "enabled",
    "works",
    "worked",
    "added",
    "introduced",
    "implements",
    "provides",
    "有",
    "支持",
    "可用",
)
_NEGATIVE_CUES = (
    "not supported",
    "unsupported",
    "not available",
    "unavailable",
    "not implemented",
    "unimplemented",
    "does not support",
    "doesn't support",
    "cannot",
    "can't",
    "without",
    "missing",
    "lack",
    "request",
    "need",
    "fails",
    "failed",
    "failure",
    "unavailable",
    "不支持",
    "缺少",
    "需要",
    "失败",
)
_COMMUNITY_SOURCES = {SourceType.ISSUE.value, SourceType.ISSUE_COMMENT.value}


class ComparisonCell(IntelligenceModel):
    """One product's evidence-backed status for a feature dimension."""

    status: ComparisonStatus
    display_label: str
    first_evidence_date: date | None = None
    community_signal_count: int = 0
    evidence_ids: list[str] = Field(default_factory=list)
    coverage_warning: str | None = None

    @property
    def signal_count(self) -> int:
        """Return the shorter name used by matrix consumers."""
        return self.community_signal_count


class ComparisonRow(IntelligenceModel):
    """Comparison cells for one requested feature dimension."""

    dimension: str
    cells: dict[str, ComparisonCell]


class ComparisonResult(IntelligenceModel):
    """Complete product comparison matrix and coverage warnings."""

    repositories: list[str]
    rows: list[ComparisonRow]
    coverage_warnings: dict[str, str | None] = Field(default_factory=dict)


class ComparisonService:
    """Build a comparison matrix from owner-scoped source records."""

    def __init__(self, repository: Any, user_id: str | None = None) -> None:
        """Initialize the service with a repository and authenticated owner."""
        self.repository = repository
        self.user_id = user_id

    def compare(
        self,
        project_ids: Sequence[str],
        dimensions: Sequence[str],
        filters: QueryFilters,
    ) -> ComparisonResult:
        """Compare requested feature dimensions using only matching evidence.

        A positive or negative status is emitted only when deterministic text
        evidence supports that status. Missing evidence and contradictory
        positive/negative evidence remain ``unknown`` so the matrix never
        fills a product cell from model knowledge or an empty result.
        """
        owner = self._require_owner()
        normalized_dimensions = _normalize_dimensions(dimensions)
        if not normalized_dimensions:
            raise ValueError("dimensions must not be empty")

        project_scope = list(project_ids)
        rows = list(
            self.repository.comparison_evidence(owner, project_scope, filters) or []
        )
        repositories = self._repositories(owner, project_scope, rows)
        coverage = self._coverage(owner, project_scope, filters)

        comparison_rows = [
            ComparisonRow(
                dimension=dimension,
                cells={
                    repository: _build_cell(
                        dimension,
                        [row for row in rows if _row_repository(row) == repository],
                        _coverage_warning(coverage.get(repository)),
                    )
                    for repository in repositories
                },
            )
            for dimension in normalized_dimensions
        ]
        return ComparisonResult(
            repositories=repositories,
            rows=comparison_rows,
            coverage_warnings={
                repository: _coverage_warning(coverage.get(repository))
                for repository in repositories
            },
        )

    def _repositories(
        self,
        owner: str,
        project_ids: Sequence[str],
        rows: Sequence[Any],
    ) -> list[str]:
        """Resolve every selected product, including products without evidence."""
        resolver = getattr(self.repository, "repositories_for_projects", None)
        values = resolver(owner, list(project_ids)) if callable(resolver) else []
        repositories = [_row_repository(value) or str(value) for value in values or []]
        repositories.extend(_row_repository(row) for row in rows)
        return _unique_strings(repositories)

    def _coverage(
        self,
        owner: str,
        project_ids: Sequence[str],
        filters: QueryFilters,
    ) -> dict[str, Any]:
        """Read per-product coverage warnings without changing evidence scope."""
        reader = getattr(self.repository, "comparison_coverage", None)
        if not callable(reader):
            return {}
        raw = reader(owner, list(project_ids), filters)
        if isinstance(raw, Mapping):
            return {str(key): value for key, value in raw.items()}
        coverage: dict[str, Any] = {}
        for row in raw or []:
            repository = _row_repository(row)
            if repository:
                coverage[repository] = row
        return coverage

    def _require_owner(self) -> str:
        """Require an authenticated owner before querying comparison data."""
        if not self.user_id:
            raise ValueError("user_id is required for comparison")
        return self.user_id


def _normalize_dimensions(dimensions: Sequence[str]) -> list[str]:
    """Normalize and de-duplicate dimension names while preserving order."""
    result: list[str] = []
    for dimension in dimensions:
        if not isinstance(dimension, str):
            raise ValueError("dimensions must contain strings")
        normalized = dimension.strip().lower().replace("-", "_").replace(" ", "_")
        if not normalized:
            raise ValueError("dimensions must contain non-empty strings")
        if normalized not in result:
            result.append(normalized)
    return result


def _build_cell(
    dimension: str,
    rows: Sequence[Any],
    coverage_warning: str | None,
) -> ComparisonCell:
    """Classify matching records and construct one deterministic matrix cell."""
    positive: list[Mapping[str, Any]] = []
    negative: list[Mapping[str, Any]] = []
    for raw_row in rows:
        row = _as_mapping(raw_row)
        classification = _classify_row(dimension, row)
        if classification == "positive":
            positive.append(row)
        elif classification == "negative":
            negative.append(row)

    matching = positive + negative
    evidence_ids = _evidence_ids(matching)
    if positive and negative:
        status: ComparisonStatus = "unknown"
    elif positive:
        status = "supported"
    elif negative:
        status = "not_supported"
    else:
        status = "unknown"

    selected = positive if status == "supported" else negative if status == "not_supported" else matching
    return ComparisonCell(
        status=status,
        display_label=_STATUS_LABELS[status],
        first_evidence_date=_first_evidence_date(selected),
        community_signal_count=sum(
            1 for row in selected if _source_type(row) in _COMMUNITY_SOURCES
        ),
        evidence_ids=evidence_ids,
        coverage_warning=coverage_warning,
    )


def _classify_row(dimension: str, row: Mapping[str, Any]) -> str | None:
    """Return positive/negative only for explicit deterministic text evidence."""
    text = " ".join(
        str(row.get(field) or "") for field in ("title", "body", "excerpt")
    ).casefold()
    terms = _FEATURE_ALIASES.get(dimension, _dimension_terms(dimension))
    matched_term = next((term for term in terms if _contains_term(text, term)), None)
    if matched_term is None:
        return None
    if _has_negative_cue(text, matched_term):
        return "negative"
    source_type = _source_type(row)
    if source_type in {SourceType.DOCUMENTATION.value, SourceType.RELEASE.value}:
        return "positive"
    if any(cue in text for cue in _POSITIVE_CUES):
        return "positive"
    return None


def _dimension_terms(dimension: str) -> tuple[str, ...]:
    """Generate safe text terms for an arbitrary requested dimension."""
    readable = dimension.replace("_", " ").strip()
    return tuple(dict.fromkeys((readable, dimension)))


def _contains_term(text: str, term: str) -> bool:
    """Match a term without matching it inside a larger ASCII word."""
    escaped = re.escape(term.casefold()).replace(r"\ ", r"\s+")
    return bool(re.search(rf"(?<!\w){escaped}(?!\w)", text))


def _has_negative_cue(text: str, term: str) -> bool:
    """Detect negative/request language close to the matched feature term."""
    escaped = re.escape(term.casefold()).replace(r"\ ", r"\s+")
    term_pattern = rf"(?<!\w){escaped}(?!\w)"
    patterns = (
        rf"{term_pattern}(?:\W+\w+){{0,5}}\W+(?:not\s+supported|unsupported|"
        rf"not\s+available|unavailable|not\s+implemented|missing|lacks?|fails?)",
        rf"(?:not\s+supported|unsupported|not\s+available|unavailable|"
        rf"not\s+implemented|does\s+not\s+support|doesn't\s+support|"
        rf"without|missing|lacks?|cannot|can't|request|need|fails?)"
        rf"(?:\W+\w+){{0,5}}\W+{term_pattern}",
    )
    if any(re.search(pattern, text) for pattern in patterns):
        return True

    for match in re.finditer(term_pattern, text):
        window = text[max(0, match.start() - 60) : match.end() + 60]
        if any(cue in window for cue in _NEGATIVE_CUES):
            return True
    return False


def _as_mapping(row: Any) -> Mapping[str, Any]:
    """Convert repository rows or Pydantic rows to a read-only mapping."""
    if isinstance(row, Mapping):
        return row
    if hasattr(row, "model_dump"):
        return row.model_dump()
    return {}


def _row_repository(row: Any) -> str:
    """Read a repository name from either a row or a string value."""
    if isinstance(row, str):
        return row
    return str(_as_mapping(row).get("repository") or "")


def _source_type(row: Mapping[str, Any]) -> str:
    """Normalize enum and text source type values."""
    value = row.get("source_type")
    return str(getattr(value, "value", value or ""))


def _evidence_id(row: Mapping[str, Any]) -> str | None:
    """Resolve the stable source id used by matrix expanders."""
    for key in ("evidence_id", "id", "record_id", "external_id"):
        value = row.get(key)
        if value:
            return str(value)
    return None


def _evidence_ids(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return unique evidence ids in date/id order."""
    ordered = sorted(
        rows,
        key=lambda row: (_row_date(row) or date.max, _evidence_id(row) or ""),
    )
    result: list[str] = []
    for row in ordered:
        evidence_id = _evidence_id(row)
        if evidence_id and evidence_id not in result:
            result.append(evidence_id)
    return result


def _first_evidence_date(rows: Sequence[Mapping[str, Any]]) -> date | None:
    """Return the earliest available date for selected evidence."""
    dates = [value for row in rows if (value := _row_date(row)) is not None]
    return min(dates) if dates else None


def _row_date(row: Mapping[str, Any]) -> date | None:
    """Normalize a repository timestamp/date to a calendar date."""
    value = row.get("occurred_at") or row.get("published_at") or row.get("created_at")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    return None


def _coverage_warning(value: Any) -> str | None:
    """Extract a displayable warning from a coverage row or string."""
    if isinstance(value, Mapping):
        warning = value.get("warning") or value.get("coverage_warning")
        return str(warning) if warning else None
    return str(value) if value else None


def _unique_strings(values: Sequence[str]) -> list[str]:
    """Drop empty and duplicate repository names without changing order."""
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


__all__ = [
    "ComparisonCell",
    "ComparisonResult",
    "ComparisonRow",
    "ComparisonService",
]
