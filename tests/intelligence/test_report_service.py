"""Contract tests for evidence-backed OpenScout intelligence reports."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pypdf import PdfReader

from docsgpt.intelligence.report_service import (
    REPORT_SECTION_HEADINGS,
    ReportDocument,
    ReportService,
    ReportSource,
    ReportSection,
    render_markdown,
    render_pdf,
)
from docsgpt.intelligence.schemas import (
    Claim,
    ClaimKind,
    Confidence,
    Coverage,
    Evidence,
    QueryIntent,
    QueryResult,
    RetrievalStrategy,
    SourceType,
)


REPORT_ID = str(uuid4())
PROJECT_ID = str(uuid4())
SOURCE_URL = "https://github.com/langgenius/dify/releases/tag/v1.0"


@pytest.fixture
def query_result() -> QueryResult:
    """Provide one complete persisted query result for report tests."""
    return QueryResult(
        answer="Dify added SSO support.",
        claims=[
            Claim(
                id="claim-1",
                text="Dify added SSO support.",
                kind=ClaimKind.FACT,
                evidence_ids=["evidence-1"],
                confidence=Confidence.HIGH,
            )
        ],
        evidence=[
            Evidence(
                id="evidence-1",
                record_id="release:1",
                repository="langgenius/dify",
                source_type=SourceType.RELEASE,
                title="Dify 1.0",
                excerpt="Added SSO support.",
                source_url=SOURCE_URL,
            )
        ],
        coverage=Coverage(
            repositories=["langgenius/dify"],
            date_from=date(2025, 9, 14),
            date_to=date(2026, 9, 14),
            counts={SourceType.RELEASE: 1},
        ),
        latency_ms=1,
        trace={
            "intent": QueryIntent.FACTUAL,
            "strategy": RetrievalStrategy.HYBRID,
            "applied_filters": {"repositories": ["langgenius/dify"]},
        },
    )


@pytest.fixture
def report(query_result: QueryResult) -> ReportDocument:
    """Provide a report document with every fixed section represented."""
    return ReportDocument(
        id=REPORT_ID,
        title="OpenScout AI 产品情报报告",
        user_id="user-1",
        project_ids=[PROJECT_ID],
        sections=[
            ReportSection(heading=heading, paragraphs=["Dify added SSO support."])
            for heading in REPORT_SECTION_HEADINGS
        ],
        sources=[
            ReportSource(
                id=query_result.evidence[0].id,
                title=query_result.evidence[0].title,
                url=str(query_result.evidence[0].source_url),
                repository=query_result.evidence[0].repository,
                source_type=query_result.evidence[0].source_type,
                excerpt=query_result.evidence[0].excerpt,
            )
        ],
    )


def extract_pdf_text(data: bytes) -> str:
    """Extract all page text for parity checks against Markdown."""
    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_markdown_and_pdf_share_source_ids(report: ReportDocument) -> None:
    """Both renderers must expose the same source identity and URL."""
    markdown = render_markdown(report)
    pdf_text = extract_pdf_text(render_pdf(report))

    assert "github.com/langgenius/dify" in markdown
    assert "github.com/langgenius/dify" in pdf_text
    assert "evidence-1" in markdown
    assert "evidence-1" in pdf_text
    assert all(heading in markdown for heading in REPORT_SECTION_HEADINGS)
    assert all(heading in pdf_text for heading in REPORT_SECTION_HEADINGS)


def test_pdf_embeds_bundled_cjk_font(report: ReportDocument) -> None:
    """Use the repository font so CJK output is portable across environments."""
    pdf = render_pdf(report)

    assert b"/FontFile2" in pdf
    assert b"STSong-Light" not in pdf


def test_renderers_accept_only_report_documents(report: ReportDocument) -> None:
    """Renderers must not silently render an unvalidated JSON mapping."""
    with pytest.raises(TypeError):
        render_markdown(report.model_dump(mode="json"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        render_pdf(report.model_dump(mode="json"))  # type: ignore[arg-type]


def test_create_persists_all_fixed_sections(query_result: QueryResult) -> None:
    """The stored JSON must contain the six report sections before rendering."""
    report_data = ReportService().create("user-1", [PROJECT_ID], [query_result])

    assert [section["heading"] for section in report_data["sections"]] == list(
        REPORT_SECTION_HEADINGS
    )
    assert report_data["source_ids"] == ["evidence-1"]
    assert report_data["coverage"]["repositories"] == ["langgenius/dify"]
    assert report_data["coverage"]["date_from"] == "2025-09-14"
    assert report_data["coverage"]["date_to"] == "2026-09-14"
    assert report_data["coverage"]["counts"] == {"release": 1}


def test_create_rejects_unvalidated_result_mapping() -> None:
    with pytest.raises(ValueError, match="QueryResult or ComparisonResult"):
        ReportService().create("user-1", [PROJECT_ID], [{"answer": "forged"}])


class StoredReports:
    """Small repository double that keeps report JSON between export attempts."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}

    def save_report(self, user_id: str, report_data: dict[str, object]) -> dict[str, object]:
        row = {
            "id": REPORT_ID,
            "user_id": user_id,
            "report_data": report_data,
        }
        self.rows[REPORT_ID] = row
        return row

    def get_report(self, report_id: str, user_id: str) -> dict[str, object] | None:
        row = self.rows.get(report_id)
        return row if row and row["user_id"] == user_id else None


def test_export_retry_does_not_rerun_query(query_result: QueryResult) -> None:
    """Exports must render saved report JSON and never invoke query again."""
    repository = StoredReports()
    query_service = MagicMock()
    report_service = ReportService(
        repository=repository,
        user_id="user-1",
        query_service=query_service,
    )
    saved = report_service.create("user-1", [PROJECT_ID], [query_result])

    report_service.export(str(saved["id"]), "pdf")
    report_service.export(str(saved["id"]), "pdf")

    query_service.query.assert_not_called()
