"""Shared contracts for the OpenScout intelligence domain."""

from __future__ import annotations

import json
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class IntelligenceModel(BaseModel):
    """Base model for immutable, strict OpenScout contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceType(StrEnum):
    """Supported GitHub evidence sources."""

    DOCUMENTATION = "documentation"
    ISSUE = "issue"
    ISSUE_COMMENT = "issue_comment"
    RELEASE = "release"


class QueryIntent(StrEnum):
    """Question categories supported by the intelligence query service."""

    FACTUAL = "factual"
    TEMPORAL = "temporal"
    COMPARATIVE = "comparative"
    AGGREGATE = "aggregate"
    RELATIONAL = "relational"


class RetrievalStrategy(StrEnum):
    """Retrieval strategies available to the query router."""

    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"
    SQL_PLUS_HYBRID = "sql_plus_hybrid"
    SPLIT_HYBRID = "split_hybrid"
    GRAPHRAG = "graphrag"


class ClaimKind(StrEnum):
    """Kinds of statements that can appear in a query result."""

    FACT = "fact"
    STATISTIC = "statistic"
    INFERENCE = "inference"


class Confidence(StrEnum):
    """Deterministic confidence labels assigned to claims."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IntelligenceProject(IntelligenceModel):
    """A user's fixed-repository intelligence project."""

    id: str
    user_id: str
    repository: str
    window_start: date
    window_end: date
    status: Literal["draft", "syncing", "ready", "partial", "failed"]
    last_synced_at: datetime | None = None
    external_updated_at: datetime | None = None


class IntelligenceRecord(IntelligenceModel):
    """A normalized, traceable GitHub object."""

    id: str | None = None
    repository: str
    source_type: SourceType
    external_id: str
    title: str
    body: str
    source_url: HttpUrl
    state: str | None = None
    labels: list[str] = Field(default_factory=list)
    comments_count: int = 0
    reactions_count: int = 0
    version: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    content_hash: str

    def to_repository_params(self, project_id: str) -> dict[str, Any]:
        """Return JSON-compatible parameters for the intelligence repository.

        Args:
            project_id: The owning intelligence project identifier.

        Returns:
            A dictionary containing record columns and serialized metadata.
        """
        data = self.model_dump(mode="json")
        data["project_id"] = project_id
        data["metadata"] = json.dumps(
            {
                key: data[key]
                for key in (
                    "state",
                    "labels",
                    "comments_count",
                    "reactions_count",
                    "version",
                    "created_at",
                    "updated_at",
                    "published_at",
                )
            },
            ensure_ascii=False,
        )
        return data


SyncFailureSource = SourceType | Literal["sync"]


class SyncFailure(IntelligenceModel):
    """A source-specific synchronization failure."""

    source_type: SyncFailureSource
    category: Literal[
        "rate_limit",
        "auth",
        "not_found",
        "network",
        "invalid_payload",
        "local",
    ]
    retryable: bool
    message: str


class QueryFilters(IntelligenceModel):
    """Explicit filters applied to an intelligence query."""

    repositories: list[str] = Field(default_factory=list)
    source_types: list[SourceType] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None


class QueryRequest(IntelligenceModel):
    """A user question, optional explicit intent, and explicit filters."""

    question: str = Field(min_length=1, max_length=2000)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    intent: QueryIntent | None = None


class Evidence(IntelligenceModel):
    """A source excerpt that supports a query claim."""

    id: str
    record_id: str
    repository: str
    source_type: SourceType
    title: str
    excerpt: str
    source_url: HttpUrl
    occurred_at: datetime | None = None
    author: str | None = None


class Claim(IntelligenceModel):
    """A generated statement with traceable evidence references."""

    id: str
    text: str
    kind: ClaimKind
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.LOW

    @model_validator(mode="after")
    def require_evidence_for_facts(self) -> Claim:
        """Require evidence for factual and statistical statements."""
        if self.kind in {ClaimKind.FACT, ClaimKind.STATISTIC} and not self.evidence_ids:
            raise ValueError("evidence_ids required for factual claims")
        return self


class Coverage(IntelligenceModel):
    """The data scope used to produce a result or synchronization summary."""

    repositories: list[str]
    date_from: date | None
    date_to: date | None
    counts: dict[SourceType, int]
    capped: bool = False
    last_synced_at: datetime | None = None


class FilterSource(IntelligenceModel):
    """A filter value and the boundary that supplied it."""

    field: Literal["repositories", "source_types", "date_from", "date_to"]
    value: Any
    source: Literal["explicit", "inferred"]


class SyncSummary(IntelligenceModel):
    """The outcome of synchronizing a project."""

    status: Literal["complete", "partial", "failed"]
    counts: dict[SourceType, int]
    failures: list[SyncFailure] = Field(default_factory=list)
    coverage: Coverage


class RetrievalTrace(IntelligenceModel):
    """Information needed to explain how a query was answered."""

    intent: QueryIntent
    strategy: RetrievalStrategy
    fallback_reason: str | None = None
    applied_filters: QueryFilters
    explicit_filters: QueryFilters = Field(default_factory=QueryFilters)
    inferred_filters: QueryFilters = Field(default_factory=QueryFilters)
    filter_sources: list[FilterSource] = Field(default_factory=list)


class RouteDecision(IntelligenceModel):
    """Validated intent, strategy, confidence, and route-level filters."""

    intent: QueryIntent
    strategy: RetrievalStrategy
    confidence: float = Field(ge=0.0, le=1.0)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    fallback_reason: str | None = None


class QueryResult(IntelligenceModel):
    """A complete evidence-backed query response."""

    answer: str
    claims: list[Claim]
    evidence: list[Evidence]
    coverage: Coverage
    latency_ms: int
    trace: RetrievalTrace
