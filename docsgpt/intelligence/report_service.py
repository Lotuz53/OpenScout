"""Structured, evidence-backed OpenScout report creation and rendering."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4
from xml.sax.saxutils import escape

from pydantic import Field, ValidationError, model_validator

from docsgpt.intelligence.comparison import ComparisonResult
from docsgpt.intelligence.schemas import (
    Coverage,
    IntelligenceModel,
    MAX_EVIDENCE_EXCERPT_LENGTH,
    MAX_FILTER_VALUE_LENGTH,
    MAX_ID_LENGTH,
    MAX_PROJECT_IDS,
    MAX_REPORT_RESULTS,
    MAX_URL_LENGTH,
    QueryResult,
    SourceType,
)
from docsgpt.core.settings import settings


REPORT_SECTION_HEADINGS = (
    "执行摘要",
    "功能对比",
    "反馈趋势",
    "产品机会线索",
    "风险与证据限制",
    "完整来源",
)


class ReportSection(IntelligenceModel):
    """One fixed report section with deterministic text blocks."""

    heading: str = Field(min_length=1, max_length=256)
    paragraphs: list[Annotated[str, Field(max_length=32_000)]] = Field(
        default_factory=list,
        max_length=128,
    )
    bullets: list[Annotated[str, Field(max_length=8000)]] = Field(
        default_factory=list,
        max_length=256,
    )


class ReportSource(IntelligenceModel):
    """A source card shared by Markdown and PDF renderers."""

    id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    title: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    repository: str = Field(min_length=1, max_length=MAX_FILTER_VALUE_LENGTH)
    source_type: str = Field(min_length=1, max_length=64)
    excerpt: str = Field(default="", max_length=MAX_EVIDENCE_EXCERPT_LENGTH)


def _empty_report_coverage() -> Coverage:
    """Return a safe empty coverage value for legacy reports."""
    return Coverage(
        repositories=[],
        date_from=None,
        date_to=None,
        counts={source_type: 0 for source_type in SourceType},
    )


class ReportDocument(IntelligenceModel):
    """The immutable structured document used by every report renderer."""

    title: str = Field(min_length=1, max_length=256)
    user_id: str = Field(min_length=1, max_length=MAX_FILTER_VALUE_LENGTH)
    project_ids: list[Annotated[str, Field(min_length=1, max_length=MAX_ID_LENGTH)]] = Field(
        max_length=MAX_PROJECT_IDS,
    )
    sections: list[ReportSection] = Field(max_length=16)
    sources: list[ReportSource] = Field(max_length=512)
    coverage: Coverage = Field(default_factory=_empty_report_coverage)
    id: Annotated[str, Field(min_length=1, max_length=MAX_ID_LENGTH)] | None = None
    source_ids: list[Annotated[str, Field(min_length=1, max_length=MAX_ID_LENGTH)]] = Field(
        default_factory=list,
        max_length=512,
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    @classmethod
    def fill_source_ids(cls, value: Any) -> Any:
        """Keep source identity metadata synchronized with source cards."""
        if not isinstance(value, Mapping) or value.get("source_ids"):
            return value
        sources = value.get("sources") or []
        source_ids = [
            source.get("id") if isinstance(source, Mapping) else getattr(source, "id", None)
            for source in sources
            if (source.get("id") if isinstance(source, Mapping) else getattr(source, "id", None))
        ]
        if not source_ids:
            return value
        result = dict(value)
        result["source_ids"] = source_ids
        return result


class ReportNotFoundError(LookupError):
    """Raised when an owner cannot read a requested report."""


class ReportExportError(RuntimeError):
    """Raised when rendering a saved report fails without deleting it."""


class ReportSizeLimitError(ValueError):
    """Raised when a report exceeds a configured rendering limit."""


class ReportService:
    """Create and export reports from saved query, comparison, and statistic data."""

    def __init__(
        self,
        repository: Any | None = None,
        user_id: str | None = None,
        *,
        query_service: Any | None = None,
    ) -> None:
        """Initialize the report service with an owner-scoped repository."""
        self.repository = repository
        self.user_id = user_id
        self.query_service = query_service
        self._memory_reports: dict[str, dict[str, Any]] = {}

    def create(
        self,
        user_id: str,
        project_ids: Sequence[str],
        results: Sequence[QueryResult | ComparisonResult],
    ) -> dict[str, Any]:
        """Build and persist a report without executing another query.

        Args:
            user_id: Authenticated owner identifier.
            project_ids: Projects represented by the supplied saved results.
            results: Saved query results or compatible comparison/statistic mappings.

        Returns:
            The persisted report row when a repository is configured, otherwise
            the structured report JSON.
        """
        if not user_id:
            raise ValueError("user_id is required for reports")
        if self.user_id and self.user_id != user_id:
            raise ValueError("report user_id does not match the service owner")
        self.user_id = user_id
        normalized_project_ids = _normalize_project_ids(project_ids)
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            raise ValueError("results must be a non-empty list")
        if not results:
            raise ValueError("results must be a non-empty list")
        if len(results) > MAX_REPORT_RESULTS:
            raise ValueError(f"results must contain at most {MAX_REPORT_RESULTS} items")
        validated_results = [_validate_result(result) for result in results]

        document = _build_report_document(
            user_id=user_id,
            project_ids=normalized_project_ids,
            results=validated_results,
        )
        report_data = document.model_dump(mode="json")
        self._memory_reports[document.id or ""] = {
            "id": document.id,
            "user_id": user_id,
            "report_data": report_data,
        }

        saver = getattr(self.repository, "save_report", None)
        if callable(saver):
            return saver(user_id, report_data)
        return report_data

    def get(self, report_id: str) -> dict[str, Any]:
        """Return a saved owner-scoped report row without rendering it."""
        return self._load_row(report_id)

    def export(self, report_id: str, format: str) -> bytes:
        """Render a saved report and never rerun its source query.

        Args:
            report_id: Persisted report identifier.
            format: Either ``markdown`` or ``pdf``.

        Returns:
            Rendered report bytes.

        Raises:
            ValueError: If the requested format is unsupported.
            ReportNotFoundError: If the report is missing or not owned.
            ReportExportError: If the renderer fails; the saved row is untouched.
        """
        if format not in {"markdown", "pdf"}:
            raise ValueError("format must be markdown or pdf")
        row = self._load_row(report_id)
        try:
            document = ReportDocument.model_validate(row.get("report_data", row))
            _enforce_report_size(document)
            rendered = render_markdown(document) if format == "markdown" else render_pdf(document)
        except ReportSizeLimitError:
            raise
        except ValidationError as exc:
            raise ReportSizeLimitError("report exceeds configured size limits") from exc
        except Exception as exc:
            raise ReportExportError("report export failed; retryable") from exc
        return rendered.encode("utf-8") if isinstance(rendered, str) else rendered

    def _load_row(self, report_id: str) -> dict[str, Any]:
        """Load one report through the configured owner-scoped adapter."""
        owner = self.user_id
        getter = getattr(self.repository, "get_report", None)
        if callable(getter):
            if not owner:
                raise ValueError("user_id is required for report lookup")
            row = getter(report_id, owner)
            if row is None:
                raise ReportNotFoundError(report_id)
            return dict(row)

        row = self._memory_reports.get(report_id)
        if row is None or (owner and row.get("user_id") != owner):
            raise ReportNotFoundError(report_id)
        return dict(row)


def render_markdown(report: ReportDocument) -> str:
    """Render a validated report document as UTF-8 Markdown."""
    _require_report_document(report)
    _enforce_report_size(report)
    lines = [f"# {report.title}", ""]
    for section in report.sections:
        lines.extend([f"## {section.heading}", ""])
        lines.extend(_render_section_markdown(section))
        lines.append("")

    if not any(section.heading == "完整来源" for section in report.sections):
        lines.extend(["## 完整来源", "", "暂无来源。", ""])
    else:
        lines.extend(_render_sources_markdown(report.sources))
    return "\n".join(lines).rstrip() + "\n"


def render_pdf(report: ReportDocument) -> bytes:
    """Render a validated report document as a PDF with CJK-capable text."""
    _require_report_document(report)
    _enforce_report_size(report)
    try:
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise ReportExportError("ReportLab is required for PDF export") from exc

    font_name = _register_cjk_font(pdfmetrics, TTFont, UnicodeCIDFont)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "OpenScoutReportTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=18,
        leading=24,
        alignment=TA_LEFT,
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "OpenScoutReportHeading",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=13,
        leading=18,
        spaceBefore=8,
        spaceAfter=5,
    )
    body_style = ParagraphStyle(
        "OpenScoutReportBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9.5,
        leading=14,
        wordWrap="CJK",
        splitLongWords=True,
        spaceAfter=4,
    )
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=report.title,
        author="OpenScout AI",
    )
    story: list[Any] = [Paragraph(_pdf_text(report.title), title_style)]
    for section in report.sections:
        story.extend([Paragraph(_pdf_text(section.heading), heading_style), Spacer(1, 2 * mm)])
        for paragraph in section.paragraphs:
            story.append(Paragraph(_pdf_text(paragraph), body_style))
        for bullet in section.bullets:
            story.append(Paragraph(_pdf_text(f"- {bullet}"), body_style))

    if not any(section.heading == "完整来源" for section in report.sections):
        story.extend(
            [
                Paragraph(_pdf_text("完整来源"), heading_style),
                Paragraph(_pdf_text("暂无来源。"), body_style),
            ]
        )
    elif report.sources:
        # Sources are rendered from the same source list as Markdown, so URL and
        # evidence identity cannot drift between export formats.
        for source in report.sources:
            source_line = f"[{source.id}] {source.repository} / {source.source_type} / {source.title} / {source.url}"
            story.append(Paragraph(_pdf_text(source_line), body_style))
            if source.excerpt:
                story.append(Paragraph(_pdf_text(source.excerpt), body_style))

    document.build(story)
    return buffer.getvalue()


def _build_report_document(
    *,
    user_id: str,
    project_ids: Sequence[str],
    results: Sequence[QueryResult | ComparisonResult],
) -> ReportDocument:
    """Assemble fixed report sections from saved structured result objects."""
    views = [_result_mapping(result) for result in results]
    summary: list[str] = []
    comparison: list[str] = []
    trends: list[str] = []
    opportunities: list[str] = []
    risks: list[str] = []
    sources: list[ReportSource] = []
    source_ids: set[str] = set()

    for index, view in enumerate(views, start=1):
        answer = _text(view.get("answer"))
        if answer:
            summary.append(f"结果 {index}：{answer}")

        claims = view.get("claims") or []
        for claim in claims:
            claim_view = _mapping(claim)
            claim_text = _text(claim_view.get("text"))
            claim_kind = _text(claim_view.get("kind"))
            evidence_ids = _string_list(claim_view.get("evidence_ids"))
            if claim_kind == "inference" and claim_text:
                opportunities.append(_claim_line(claim_text, claim_view.get("confidence"), evidence_ids))
            elif claim_text:
                comparison.append(_claim_line(claim_text, claim_view.get("confidence"), evidence_ids))
            if claim_kind in {"fact", "statistic"} and not evidence_ids:
                risks.append(f"无有效证据引用的{claim_kind}主张：{claim_text}")

        evidence_views = [_mapping(item) for item in (view.get("evidence") or [])]
        issue_evidence = [
            item for item in evidence_views if _text(item.get("source_type")) in {"issue", "issue_comment"}
        ]
        trends.extend(
            f"{_text(item.get('repository'))}：{_text(item.get('title'))}"
            for item in issue_evidence
            if _text(item.get("title"))
        )
        for item in evidence_views:
            source_id = _text(item.get("id"))
            source_url = _text(item.get("source_url") or item.get("url"))
            if not source_id or not source_url or source_id in source_ids:
                continue
            source_ids.add(source_id)
            sources.append(
                ReportSource(
                    id=source_id,
                    title=_text(item.get("title")),
                    url=source_url,
                    repository=_text(item.get("repository")),
                    source_type=_text(item.get("source_type")),
                    excerpt=_text(item.get("excerpt")),
                )
            )

        _append_result_details(view, comparison, trends, risks)

    if not summary:
        summary.append("当前报告由已保存的结构化结果生成。")
    if not comparison:
        comparison.append("暂无独立功能对比结果。")
    if not trends:
        trends.append("暂无反馈趋势统计结果。")
    if not opportunities:
        opportunities.append("暂无产品机会推断。")
    if not risks:
        risks.append("当前结果未标记额外风险。")
    if not sources:
        risks.append("当前结果没有可展示的来源 URL。")

    sections = [
        ReportSection(heading="执行摘要", paragraphs=summary),
        ReportSection(heading="功能对比", bullets=comparison),
        ReportSection(heading="反馈趋势", bullets=trends),
        ReportSection(heading="产品机会线索", bullets=opportunities),
        ReportSection(heading="风险与证据限制", bullets=risks),
        ReportSection(
            heading="完整来源",
            paragraphs=["以下来源与报告中的证据标识保持一致。"] if sources else ["暂无来源。"],
        ),
    ]
    return ReportDocument(
        id=str(uuid4()),
        title="OpenScout AI 产品情报报告",
        user_id=user_id,
        project_ids=project_ids,
        sections=sections,
        sources=sources,
        coverage=_coverage_for_views(views),
        source_ids=[source.id for source in sources],
    )


def _coverage_for_views(views: Sequence[Mapping[str, Any]]) -> Coverage:
    """Preserve the first validated query coverage in a saved report."""
    for view in views:
        raw_coverage = view.get("coverage")
        if not isinstance(raw_coverage, Mapping):
            continue
        try:
            return Coverage.model_validate(raw_coverage)
        except ValidationError:
            continue
    return _empty_report_coverage()


def _append_result_details(
    view: Mapping[str, Any],
    comparison: list[str],
    trends: list[str],
    risks: list[str],
) -> None:
    """Add deterministic comparison, aggregate, coverage, and trace details."""
    rows = view.get("rows") or []
    if view.get("cells"):
        rows = [view]
    for row in rows:
        row_view = _mapping(row)
        dimension = _text(row_view.get("dimension"))
        cells = row_view.get("cells")
        if isinstance(cells, Mapping):
            for repository, cell in cells.items():
                cell_view = _mapping(cell)
                label = _text(cell_view.get("display_label") or cell_view.get("status"))
                comparison.append(f"{repository} / {dimension}：{label}")
        elif dimension and "value" in row_view:
            trends.append(f"{dimension}={_text(row_view.get('value'))}")

    if view.get("capped"):
        risks.append("统计结果达到数据上限，趋势和数量可能不完整。")
    coverage = _mapping(view.get("coverage"))
    if coverage.get("capped"):
        risks.append("查询覆盖范围达到数据上限。")
    trace = _mapping(view.get("trace"))
    fallback_reason = _text(trace.get("fallback_reason"))
    if fallback_reason:
        risks.append(f"检索回退原因：{fallback_reason}")


def _result_mapping(value: Any) -> Mapping[str, Any]:
    """Coerce Pydantic results or JSON objects without rerunning their query."""
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        result = model_dump(mode="json")
        if isinstance(result, Mapping):
            return result
    raise TypeError("results must contain QueryResult or structured mappings")


def _validate_result(value: Any) -> QueryResult | ComparisonResult:
    """Validate one report input against a known intelligence result schema."""
    if isinstance(value, (QueryResult, ComparisonResult)):
        return value
    for model in (QueryResult, ComparisonResult):
        try:
            return model.model_validate(value)
        except ValidationError:
            continue
    raise ValueError("results must contain QueryResult or ComparisonResult")


def _mapping(value: Any) -> Mapping[str, Any]:
    """Return a safe mapping view for optional nested result data."""
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        result = model_dump(mode="json")
        if isinstance(result, Mapping):
            return result
    return {}


def _claim_line(text: str, confidence: Any, evidence_ids: Sequence[str]) -> str:
    """Render a claim with confidence and evidence identity metadata."""
    confidence_text = _text(confidence) or "low"
    evidence_text = ", ".join(evidence_ids) if evidence_ids else "无"
    return f"[{confidence_text}] {text}（证据：{evidence_text}）"


def _render_section_markdown(section: ReportSection) -> list[str]:
    """Render one section's paragraphs and bullets."""
    lines: list[str] = []
    lines.extend(section.paragraphs)
    lines.extend(f"- {bullet}" for bullet in section.bullets)
    if not lines:
        lines.append("暂无内容。")
    return lines


def _render_sources_markdown(sources: Sequence[ReportSource]) -> list[str]:
    """Render the canonical evidence source list."""
    lines = [
        "",
        *(
            f"- `{source.id}` | {source.repository} | {source.source_type} | [{source.title}]({source.url})"
            for source in sources
        ),
    ]
    if not sources:
        lines.append("暂无来源。")
    return lines


def _register_cjk_font(pdfmetrics: Any, tt_font: Any, cid_font: Any) -> str:
    """Register an embeddable local CJK font, with a ReportLab fallback."""
    font_candidates = []
    configured = os.environ.get("OPENSCOUT_CJK_FONT")
    if configured:
        font_candidates.append(Path(configured))
    font_candidates.extend(
        [
            Path(__file__).resolve().parent / "resources" / "fonts" / "NotoSansCJKsc-Regular.ttf",
            Path("/System/Library/Fonts/Supplemental/Hiragino Sans GB.ttc"),
            Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        ]
    )
    for index, path in enumerate(font_candidates):
        if not path.is_file():
            continue
        name = f"OpenScoutCJK{index}"
        try:
            kwargs = {"subfontIndex": 0} if path.suffix.lower() == ".ttc" else {}
            pdfmetrics.registerFont(tt_font(name, str(path), **kwargs))
            return name
        except Exception:
            continue

    # STSong-Light is a Unicode CJK fallback supplied by PDF viewers. It keeps
    # exports functional in minimal Linux containers without silently dropping
    # Chinese text; local fonts above are preferred and embedded when present.
    pdfmetrics.registerFont(cid_font("STSong-Light"))
    return "STSong-Light"


def _pdf_text(value: Any) -> str:
    """Escape plain text for ReportLab's paragraph mini-markup."""
    return escape(_text(value)).replace("\n", "<br/>")


def _normalize_project_ids(project_ids: Sequence[str]) -> list[str]:
    """Normalize project ids while preserving request order."""
    if not isinstance(project_ids, Sequence) or isinstance(project_ids, (str, bytes)):
        raise ValueError("project_ids must be a non-empty list")
    normalized = [str(project_id) for project_id in project_ids if str(project_id)]
    if not normalized:
        raise ValueError("project_ids must be a non-empty list")
    if len(normalized) > MAX_PROJECT_IDS:
        raise ValueError(f"project_ids must contain at most {MAX_PROJECT_IDS} items")
    return list(dict.fromkeys(normalized))


def _string_list(value: Any) -> list[str]:
    """Normalize a nullable sequence of values into strings."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]


def _text(value: Any) -> str:
    """Convert optional enum, URL, and scalar values to display text."""
    if value is None:
        return ""
    return str(value)


def _require_report_document(report: Any) -> None:
    """Reject unvalidated mappings at the renderer boundary."""
    if not isinstance(report, ReportDocument):
        raise TypeError("renderer expects ReportDocument")


def _enforce_report_size(report: ReportDocument) -> None:
    """Reject oversized validated documents before Markdown/PDF rendering."""
    serialized_size = len(report.model_dump_json())
    if serialized_size > settings.INTELLIGENCE_MAX_REPORT_CHARS:
        raise ReportSizeLimitError(
            "report exceeds configured size limit of "
            f"{settings.INTELLIGENCE_MAX_REPORT_CHARS} characters"
        )


__all__ = [
    "REPORT_SECTION_HEADINGS",
    "ReportDocument",
    "ReportExportError",
    "ReportNotFoundError",
    "ReportSizeLimitError",
    "ReportService",
    "ReportSource",
    "ReportSection",
    "render_markdown",
    "render_pdf",
]
