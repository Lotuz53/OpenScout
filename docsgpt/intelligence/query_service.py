"""The OpenScout query application service with optional filters and reranking."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from inspect import Parameter, signature
from typing import Any

from pydantic import ValidationError

from docsgpt.intelligence.analytics import AggregateQuery, AggregateResult
from docsgpt.intelligence.claims import validate_claims
from docsgpt.intelligence.confidence import confidence_for_claim
from docsgpt.intelligence.filters import (
    compile_metadata_filter,
    filter_provenance,
    merge_filters,
)
from docsgpt.intelligence.query_router import QueryRouter, RouteDecision
from docsgpt.intelligence.reranker import NoOpReranker, Reranker, safe_rerank
from docsgpt.intelligence.schemas import (
    Claim,
    ClaimKind,
    Confidence,
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
GRAPHRAG_DISABLED = "graphrag_disabled"
GRAPHRAG_INCOMPLETE = "graphrag_incomplete"
GRAPHRAG_TIMEOUT = "graphrag_timeout"
GRAPHRAG_UNAVAILABLE = "graphrag_unavailable"


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


def _coerce_claim(value: Any) -> Claim:
    """Coerce one generator claim while retaining uncited facts for validation."""
    if isinstance(value, Claim):
        return value
    try:
        return Claim.model_validate(value)
    except ValidationError:
        if not isinstance(value, Mapping):
            raise
        raw_kind = value.get("kind")
        try:
            kind = raw_kind if isinstance(raw_kind, ClaimKind) else ClaimKind(raw_kind)
        except (TypeError, ValueError):
            raise
        evidence_ids = value.get("evidence_ids") or []
        if kind not in {ClaimKind.FACT, ClaimKind.STATISTIC} or evidence_ids:
            raise
        claim_id = value.get("id")
        text = value.get("text")
        if not isinstance(claim_id, str) or not claim_id:
            raise
        if not isinstance(text, str):
            raise
        return Claim.model_construct(
            id=claim_id,
            text=text,
            kind=kind,
            evidence_ids=[],
            confidence=Confidence.LOW,
        )


def _coerce_generated(value: Any) -> tuple[str, list[Claim], bool]:
    """Accept a small generator contract while keeping the result strongly typed."""
    answer = ""
    raw_claims: Any = []
    has_conflict = False
    if isinstance(value, Mapping):
        answer = str(value.get("answer") or "")
        raw_claims = value.get("claims") or []
        has_conflict = bool(value.get("has_conflict") or value.get("conflict"))
    elif isinstance(value, tuple) and len(value) == 2:
        answer = str(value[0] or "")
        raw_claims = value[1] or []
    elif isinstance(value, tuple) and len(value) == 3:
        answer = str(value[0] or "")
        raw_claims = value[1] or []
        has_conflict = bool(value[2])
    elif isinstance(value, str):
        answer = value
    elif value is not None:
        answer = str(getattr(value, "answer", "") or "")
        raw_claims = getattr(value, "claims", value)
        has_conflict = bool(
            getattr(value, "has_conflict", False) or getattr(value, "conflict", False)
        )

    if isinstance(raw_claims, (Claim, Mapping)):
        raw_claims = [raw_claims]
    if isinstance(raw_claims, Claim):
        raw_claims = [raw_claims]
    claims = [
        _coerce_claim(claim)
        for claim in (raw_claims or [])
    ]
    if not answer and claims:
        answer = " ".join(claim.text for claim in claims)
    return answer or NO_EVIDENCE_ANSWER, claims, has_conflict


def _aggregate_query(
    question: str,
    filters: QueryFilters,
    user_id: str,
) -> AggregateQuery:
    """Translate an aggregate question into a safe SQL query shape."""
    normalized = question.casefold()
    metric = "count"
    if "median" in normalized or "中位" in normalized:
        metric = "median_comments"
    elif "reaction" in normalized or "点赞" in normalized:
        metric = "sum_reactions"

    dimension = "repository"
    if "source" in normalized or "来源" in normalized or "类型" in normalized:
        dimension = "source_type"
    elif "label" in normalized or "标签" in normalized:
        dimension = "label"
    elif "month" in normalized or "月" in normalized or "趋势" in normalized:
        dimension = "month"
    elif "state" in normalized or "状态" in normalized:
        dimension = "state"
    return AggregateQuery(
        metric=metric,
        dimension=dimension,
        user_id=user_id,
        filters=filters,
    )


def _format_aggregate_result(result: AggregateResult) -> str:
    """Render SQL values into the answer without asking an LLM to count."""
    if not result.rows:
        summary = "SQL统计结果：当前范围内没有符合条件的数据。"
    else:
        values = "; ".join(
            f"{row.dimension}={_format_aggregate_value(row.value)}"
            for row in result.rows
        )
        summary = (
            f"SQL统计结果（{result.metric}，按{result.dimension}）：{values}"
        )
    return summary


def _format_aggregate_value(value: int | float) -> str:
    """Format aggregate numbers without introducing presentation rounding."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _aggregate_claims(
    result: AggregateResult,
    evidence: Sequence[Evidence],
) -> list[Claim]:
    """Expose each SQL row as a cited statistic claim for result consumers.

    The aggregate value is computed by SQL; representative evidence ids keep
    the statistic traceable in the shared result contract without asking the
    language model to reproduce or validate the number.
    """
    evidence_ids = [item.id for item in evidence]
    if not evidence_ids:
        return []
    return [
        Claim(
            id=f"aggregate:{result.metric}:{result.dimension}:{index}",
            text=(
                f"{result.metric}（按{result.dimension}）："
                f"{row.dimension}={_format_aggregate_value(row.value)}"
            ),
            kind=ClaimKind.STATISTIC,
            evidence_ids=evidence_ids,
        )
        for index, row in enumerate(result.rows)
    ]


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
    validation = validate_claims(claims, evidence, coverage)
    if not validation.valid:
        messages = [
            f"{claim_id}: {', '.join(ids)}"
            for claim_id, ids in validation.unknown_evidence_ids.items()
        ]
        if validation.missing_evidence_claim_ids:
            messages.append(
                "missing evidence for "
                + ", ".join(validation.missing_evidence_claim_ids)
            )
        raise ValueError("invalid claim citations: " + "; ".join(messages))
    return validation.valid_claims


def _score_claims(
    claims: Sequence[Claim],
    evidence: Sequence[Evidence],
    coverage: Coverage,
    has_conflict: bool,
) -> list[Claim]:
    """Replace every model-provided confidence value with a deterministic one."""
    return [
        claim.model_copy(
            update={
                "confidence": confidence_for_claim(
                    claim,
                    evidence,
                    coverage,
                    has_conflict,
                )
            }
        )
        for claim in claims
    ]


class QueryService:
    """Execute hybrid retrieval, optional reranking, and evidence validation."""

    def __init__(
        self,
        retriever: Any | None = None,
        generator: Any | None = None,
        coverage: Callable[..., Coverage] | Coverage | None = None,
        reranker: Reranker | None = None,
        filter_inferer: Callable[[str], QueryFilters | Mapping[str, Any]] | None = None,
        router: QueryRouter | None = None,
        analytics: Any | None = None,
        graph_retriever: Any | None = None,
        graph_enabled: bool | None = None,
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
            router: Optional constrained intent router. When omitted, the
                original factual Hybrid path is preserved.
            analytics: Optional SQL-first aggregate service used by routed
                aggregate questions.
            graph_retriever: Optional GraphRAG adapter exposing ``retrieve`` or
                ``search``. It is only called for a routed relational question.
            graph_enabled: Optional explicit GraphRAG kill-switch. ``False``
                records a disabled fallback without calling the adapter.
        """
        self.retriever = retriever or _EmptyRetriever()
        self.generator = generator or _EvidenceOnlyGenerator()
        self.coverage = coverage or _empty_coverage
        self.reranker = reranker
        self.filter_inferer = filter_inferer
        self.router = router
        self.analytics = analytics
        self.graph_retriever = graph_retriever
        self.graph_enabled = graph_enabled

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

    def _bind_user(self, user_id: str) -> None:
        """Bind the authenticated owner to runtime-owned dependencies.

        Production adapters are constructed before a request is executed so
        the route remains a thin application boundary. They receive the
        owner here, immediately before retrieval, while injected test doubles
        remain unaffected because optional methods are resolved statically.
        """
        for dependency in (
            self.retriever,
            self.generator,
            self.coverage,
            self.analytics,
            self.graph_retriever,
        ):
            binder = _optional_method(dependency, "set_user_id")
            if callable(binder):
                binder(user_id)

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

    def _run_analytics(
        self,
        route: RouteDecision | None,
        request: QueryRequest,
        filters: QueryFilters,
        user_id: str,
    ) -> AggregateResult | None:
        """Run SQL analytics only when an aggregate route is explicitly active."""
        if route is None or route.intent != QueryIntent.AGGREGATE:
            return None
        if self.analytics is None:
            return None
        run = getattr(self.analytics, "run", None)
        if not callable(run):
            raise TypeError("analytics must expose run")
        result = run(_aggregate_query(request.question, filters, user_id))
        return (
            result
            if isinstance(result, AggregateResult)
            else AggregateResult.model_validate(result)
        )

    def _retrieve_graph(
        self,
        request: QueryRequest,
        filters: QueryFilters,
    ) -> tuple[list[Evidence], str | None]:
        """Retrieve relational evidence through GraphRAG with one safe fallback.

        The intelligence layer accepts a narrow adapter boundary instead of
        constructing a source-aware ``GraphRAGRetriever`` itself. This keeps
        ownership and source selection in application wiring while allowing
        tests and deployments to provide either ``retrieve`` or ``search``.

        Returns:
            A pair of evidence and an optional fallback reason. A non-null
            reason means the caller must execute the ordinary Hybrid path once.
        """
        if self.graph_enabled is False:
            return [], GRAPHRAG_DISABLED
        retriever = self.graph_retriever
        if retriever is None:
            return [], GRAPHRAG_UNAVAILABLE
        if getattr(retriever, "enabled", True) is False:
            return [], GRAPHRAG_DISABLED

        try:
            retrieve = getattr(retriever, "retrieve", None)
            if callable(retrieve):
                result = retrieve(request.question, filters)
            else:
                search = getattr(retriever, "search", None)
                if not callable(search):
                    return [], GRAPHRAG_UNAVAILABLE
                result = search(request.question)
        except TimeoutError:
            logger.warning("GraphRAG retrieval timed out; falling back to Hybrid")
            return [], GRAPHRAG_TIMEOUT
        except Exception:
            logger.exception("GraphRAG retrieval failed; falling back to Hybrid")
            return [], GRAPHRAG_UNAVAILABLE

        status = None
        if isinstance(result, Mapping):
            status = result.get("status")
            result = result.get("evidence", result.get("results", result))
        else:
            status = getattr(result, "status", None)
            result = getattr(result, "evidence", result)
        normalized_status = str(status or "").casefold()
        if normalized_status in {"disabled", "unavailable"}:
            return [], (
                GRAPHRAG_DISABLED
                if normalized_status == "disabled"
                else GRAPHRAG_UNAVAILABLE
            )
        if normalized_status in {"incomplete", "pending"}:
            return [], GRAPHRAG_INCOMPLETE
        if result is None:
            return [], GRAPHRAG_INCOMPLETE
        try:
            evidence = _coerce_evidence(result)
        except Exception:
            logger.exception("GraphRAG returned invalid evidence; falling back to Hybrid")
            return [], GRAPHRAG_UNAVAILABLE
        if not evidence:
            return [], GRAPHRAG_INCOMPLETE
        return evidence, None

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

    def _generate_with_validation(
        self,
        request: QueryRequest,
        evidence: Sequence[Evidence],
        coverage: Coverage,
    ) -> tuple[str, list[Claim]]:
        """Generate claims, retry once on citation errors, then degrade safely."""
        generated = self.generator.generate(request.question, evidence)
        answer, claims, has_conflict = _coerce_generated(generated)
        validation = validate_claims(claims, evidence, coverage)
        if validation.valid:
            return answer, _score_claims(
                validation.valid_claims,
                evidence,
                coverage,
                has_conflict,
            )

        logger.warning("generated claims failed citation validation; retrying once")
        retry_generated = self.generator.generate(request.question, evidence)
        retry_answer, retry_claims, retry_conflict = _coerce_generated(retry_generated)
        retry_validation = validate_claims(retry_claims, evidence, coverage)
        if retry_validation.valid:
            return retry_answer, _score_claims(
                retry_validation.valid_claims,
                evidence,
                coverage,
                retry_conflict,
            )

        logger.warning("generated claims failed citation validation after retry")
        return NO_EVIDENCE_ANSWER, _score_claims(
            retry_validation.valid_claims,
            evidence,
            coverage,
            retry_conflict,
        )

    def query(self, request: QueryRequest, user_id: str) -> QueryResult:
        """Retrieve evidence, generate claims, and return a traced result."""
        started = time.perf_counter()
        self._bind_user(user_id)
        explicit_filters = request.filters
        route = self.router.route(request) if self.router is not None else None
        route_filters = route.filters if route is not None else QueryFilters()
        inferred_filters = merge_filters(
            route_filters,
            self._infer_filters(request.question),
        )
        effective_filters = merge_filters(explicit_filters, inferred_filters)
        aggregate_result = self._run_analytics(
            route,
            request,
            effective_filters,
            user_id,
        )
        fallback_reason = route.fallback_reason if route is not None else None
        strategy = route.strategy if route is not None else None
        if aggregate_result is not None and aggregate_result.evidence:
            evidence = list(aggregate_result.evidence)
        elif (
            route is not None
            and route.intent == QueryIntent.RELATIONAL
            and route.strategy == RetrievalStrategy.GRAPHRAG
        ):
            evidence, graph_fallback_reason = self._retrieve_graph(
                request,
                effective_filters,
            )
            if graph_fallback_reason is not None:
                evidence = self._retrieve(request, effective_filters)
                strategy = RetrievalStrategy.HYBRID
                fallback_reason = graph_fallback_reason
        else:
            evidence = self._retrieve(request, effective_filters)
        if self.reranker is not None:
            evidence = safe_rerank(
                self.reranker,
                request.question,
                evidence,
                len(evidence),
            )
        if aggregate_result is not None:
            coverage = aggregate_result.coverage
        else:
            coverage = self._coverage(effective_filters, user_id)
        answer, claims = self._generate_with_validation(
            request,
            evidence,
            coverage,
        )
        if aggregate_result is not None:
            claims = [
                claim for claim in claims if claim.kind != ClaimKind.STATISTIC
            ]
            claims.extend(
                _score_claims(
                    _aggregate_claims(aggregate_result, evidence),
                    evidence,
                    coverage,
                    False,
                )
            )
            aggregate_answer = _format_aggregate_result(aggregate_result)
            if answer != NO_EVIDENCE_ANSWER:
                aggregate_answer = f"{aggregate_answer}\n{answer}"
            answer = aggregate_answer
        return QueryResult(
            answer=answer,
            claims=claims,
            evidence=evidence,
            coverage=coverage,
            latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
            trace=RetrievalTrace(
                intent=route.intent if route is not None else QueryIntent.FACTUAL,
                strategy=(
                    strategy
                    if strategy is not None
                    else (
                        RetrievalStrategy.HYBRID_RERANK
                        if self.reranker is not None
                        and not isinstance(self.reranker, NoOpReranker)
                        else RetrievalStrategy.HYBRID
                    )
                ),
                fallback_reason=fallback_reason,
                applied_filters=effective_filters,
                explicit_filters=explicit_filters,
                inferred_filters=inferred_filters,
                filter_sources=filter_provenance(
                    explicit_filters,
                    inferred_filters,
                ),
            ),
        )


__all__ = [
    "GRAPHRAG_DISABLED",
    "GRAPHRAG_INCOMPLETE",
    "GRAPHRAG_TIMEOUT",
    "GRAPHRAG_UNAVAILABLE",
    "NO_EVIDENCE_ANSWER",
    "QueryService",
    "enforce_citations",
]
