"""The OpenScout query application service with optional filters and reranking."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from inspect import Parameter, signature
from typing import Any

from docsgpt.intelligence.filters import (
    compile_metadata_filter,
    filter_provenance,
    merge_filters,
)
from docsgpt.intelligence.reranker import NoOpReranker, Reranker, safe_rerank
from docsgpt.intelligence.schemas import (
    Claim,
    ClaimKind,
    Coverage,
    Evidence,
    QueryFilters,
    QueryIntent,
    QueryRequest,
    QueryResult,
    RetrievalStrategy,
    RetrievalTrace,
    SourceType,
)


logger = logging.getLogger(__name__)

NO_EVIDENCE_ANSWER = "当前收录数据无法支持该结论。"


def _optional_method(instance: Any, name: str) -> Any:
    """Read an optional adapter method without triggering dynamic mocks."""
    instance_attributes = getattr(instance, "__dict__", {})
    if name in instance_attributes:
        return instance_attributes[name]
    if any(name in parent.__dict__ for parent in type(instance).__mro__):
        return getattr(instance, name, None)
    return None


class _EmptyRetriever:
    """Safe fallback used until application wiring supplies a hybrid index."""

    def retrieve(self, question: str, filters: QueryFilters) -> list[Evidence]:
        """Return no evidence without attempting an unconfigured search."""
        del question, filters
        return []


class _EvidenceOnlyGenerator:
    """Deterministic fallback that never invents an unsupported fact."""

    def generate(self, question: str, evidence: Sequence[Evidence]) -> dict[str, Any]:
        """Return an honest insufficient-evidence answer."""
        del question, evidence
        return {"answer": NO_EVIDENCE_ANSWER, "claims": []}


def _empty_coverage(filters: QueryFilters) -> Coverage:
    """Build zero-count coverage for an empty/unconfigured intelligence index."""
    return Coverage(
        repositories=list(filters.repositories),
        date_from=filters.date_from,
        date_to=filters.date_to,
        counts={source_type: 0 for source_type in SourceType},
    )


def _coerce_evidence(items: Sequence[Evidence | Mapping[str, Any]]) -> list[Evidence]:
    """Normalize typed or mapping evidence returned by a retriever."""
    return [
        item if isinstance(item, Evidence) else Evidence.model_validate(item)
        for item in items
    ]


def _coerce_generated(value: Any) -> tuple[str, list[Claim]]:
    """Accept a small generator contract while keeping the result strongly typed."""
    answer = ""
    raw_claims: Any = []
    if isinstance(value, Mapping):
        answer = str(value.get("answer") or "")
        raw_claims = value.get("claims") or []
    elif isinstance(value, tuple) and len(value) == 2:
        answer = str(value[0] or "")
        raw_claims = value[1] or []
    elif isinstance(value, str):
        answer = value
    elif value is not None:
        answer = str(getattr(value, "answer", "") or "")
        raw_claims = getattr(value, "claims", value)

    if isinstance(raw_claims, Claim):
        raw_claims = [raw_claims]
    claims = [
        claim if isinstance(claim, Claim) else Claim.model_validate(claim)
        for claim in (raw_claims or [])
    ]
    if not answer and claims:
        answer = " ".join(claim.text for claim in claims)
    return answer or NO_EVIDENCE_ANSWER, claims


def enforce_citations(
    *,
    claims: Sequence[Claim],
    evidence: Sequence[Evidence],
    coverage: Coverage,
) -> list[Claim]:
    """Ensure every factual claim cites evidence returned for this query.

    ``coverage`` is accepted as part of the boundary so later SQL-backed
    claims can share this validator without changing the query service API.
    """
    del coverage
    evidence_ids = {item.id for item in evidence}
    for claim in claims:
        if claim.kind in {ClaimKind.FACT, ClaimKind.STATISTIC}:
            unknown = set(claim.evidence_ids) - evidence_ids
            if unknown:
                raise ValueError(
                    "claim cites unknown evidence: "
                    + ", ".join(sorted(unknown))
                )
    return list(claims)


class QueryService:
    """Execute hybrid retrieval, optional reranking, and evidence validation."""

    def __init__(
        self,
        retriever: Any | None = None,
        generator: Any | None = None,
        coverage: Callable[..., Coverage] | Coverage | None = None,
        reranker: Reranker | None = None,
        filter_inferer: Callable[[str], QueryFilters | Mapping[str, Any]] | None = None,
    ) -> None:
        """Initialize the service with injectable retrieval dependencies.

        Args:
            retriever: Object exposing retrieve; a DocsGPT retriever that
                exposes only search is also supported as a narrow adapter.
            generator: Object exposing generate(question, evidence).
            coverage: A Coverage value or callable accepting filters and
                optionally the authenticated user id.
            reranker: Optional provider-neutral reranker. When omitted, the
                Hybrid order is preserved.
            filter_inferer: Optional parser for implicit question filters.
        """
        self.retriever = retriever or _EmptyRetriever()
        self.generator = generator or _EvidenceOnlyGenerator()
        self.coverage = coverage or _empty_coverage
        self.reranker = reranker
        self.filter_inferer = filter_inferer

    def _infer_filters(self, question: str) -> QueryFilters:
        """Resolve implicit filters without blocking a query on parser errors."""
        if self.filter_inferer is None:
            return QueryFilters()
        try:
            inferred = self.filter_inferer(question)
            return (
                inferred
                if isinstance(inferred, QueryFilters)
                else QueryFilters.model_validate(inferred)
            )
        except Exception:
            logger.exception("filter inference failed; using explicit filters only")
            return QueryFilters()

    def _retrieve(
        self,
        request: QueryRequest,
        filters: QueryFilters | None = None,
    ) -> list[Evidence]:
        """Call the preferred retrieve method or adapt DocsGPT's search API."""
        effective_filters = filters if filters is not None else request.filters
        metadata_filter = compile_metadata_filter(effective_filters)
        retrieve_filtered = _optional_method(self.retriever, "retrieve_filtered")
        if callable(retrieve_filtered):
            items = retrieve_filtered(
                request.question,
                effective_filters,
                metadata_filter=metadata_filter,
            )
            return _coerce_evidence(items or [])

        retrieve = getattr(self.retriever, "retrieve", None)
        if callable(retrieve):
            items = retrieve(request.question, effective_filters)
        else:
            search_filtered = _optional_method(self.retriever, "search_filtered")
            if callable(search_filtered):
                items = search_filtered(
                    request.question,
                    metadata_filter=metadata_filter,
                )
                return _coerce_evidence(items or [])
            search = getattr(self.retriever, "search", None)
            if not callable(search):
                raise TypeError("retriever must expose retrieve or search")
            items = search(request.question)
        return _coerce_evidence(items or [])

    def _coverage(self, filters: QueryFilters, user_id: str) -> Coverage:
        """Resolve coverage from a fixed value or injected callable."""
        if isinstance(self.coverage, Coverage):
            return self.coverage
        try:
            parameters = signature(self.coverage).parameters.values()
        except (TypeError, ValueError):
            parameters = ()
        accepts_user = any(
            parameter.name == "user_id"
            or parameter.kind == Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        if accepts_user:
            result = self.coverage(filters, user_id)
        else:
            result = self.coverage(filters)
        return result if isinstance(result, Coverage) else Coverage.model_validate(result)

    def query(self, request: QueryRequest, user_id: str) -> QueryResult:
        """Retrieve evidence, generate claims, and return a traced result."""
        started = time.perf_counter()
        explicit_filters = request.filters
        inferred_filters = self._infer_filters(request.question)
        effective_filters = merge_filters(explicit_filters, inferred_filters)
        evidence = self._retrieve(request, effective_filters)
        if self.reranker is not None:
            evidence = safe_rerank(
                self.reranker,
                request.question,
                evidence,
                len(evidence),
            )
        generated = self.generator.generate(request.question, evidence)
        answer, claims = _coerce_generated(generated)
        coverage = self._coverage(effective_filters, user_id)
        claims = enforce_citations(
            claims=claims,
            evidence=evidence,
            coverage=coverage,
        )
        return QueryResult(
            answer=answer,
            claims=claims,
            evidence=evidence,
            coverage=coverage,
            latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
            trace=RetrievalTrace(
                intent=QueryIntent.FACTUAL,
                strategy=(
                    RetrievalStrategy.HYBRID_RERANK
                    if self.reranker is not None
                    and not isinstance(self.reranker, NoOpReranker)
                    else RetrievalStrategy.HYBRID
                ),
                applied_filters=effective_filters,
                explicit_filters=explicit_filters,
                inferred_filters=inferred_filters,
                filter_sources=filter_provenance(
                    explicit_filters,
                    inferred_filters,
                ),
            ),
        )


__all__ = ["QueryService", "enforce_citations"]
