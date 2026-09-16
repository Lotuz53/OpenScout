"""End-to-end acceptance checks for the Stage A OpenScout demo."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from flask import Flask, request
from flask.testing import FlaskClient
from flask_restx import Api

from docsgpt.api.user.intelligence.routes import intelligence_ns
from docsgpt.intelligence.report_service import REPORT_SECTION_HEADINGS, ReportService
from docsgpt.intelligence.schemas import (
    Claim,
    Coverage,
    Evidence,
    QueryIntent,
    QueryRequest,
    QueryResult,
    RetrievalStrategy,
    RetrievalTrace,
)
from evaluation.run_eval import FixtureExecutor


REPOSITORIES = [
    "langgenius/dify",
    "infiniflow/ragflow",
    "labring/FastGPT",
]
DEMO_PATH = Path(__file__).resolve().parents[2] / "evaluation/demo/questions.json"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "tests/intelligence/fixtures/github_objects.json"
)


def load_demo_scenarios(path: Path = DEMO_PATH) -> list[dict[str, Any]]:
    """Load and validate the five fixed-snapshot demo scenarios."""
    with path.open(encoding="utf-8") as stream:
        scenarios = json.load(stream)
    if not isinstance(scenarios, list) or len(scenarios) != 5:
        raise ValueError("Stage A demo must contain exactly five scenarios")

    ids: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("demo scenarios must be JSON objects")
        required = {"id", "label", "snapshot_id", "type", "question", "repositories"}
        missing = required - scenario.keys()
        if missing:
            raise ValueError(f"demo scenario is missing: {', '.join(sorted(missing))}")
        scenario_id = scenario["id"]
        if not isinstance(scenario_id, str) or not scenario_id or scenario_id in ids:
            raise ValueError("demo scenario ids must be unique non-empty strings")
        ids.add(scenario_id)
        if scenario["snapshot_id"] != "stage-a-2026-09-14":
            raise ValueError(f"{scenario_id} does not use the frozen Stage A snapshot")
        if scenario["type"] not in {"factual", "temporal", "comparative", "comprehensive"}:
            raise ValueError(f"{scenario_id} has an unsupported question type")
        if not isinstance(scenario["question"], str) or not scenario["question"].strip():
            raise ValueError(f"{scenario_id}.question must be non-empty")
        repositories = scenario["repositories"]
        if not isinstance(repositories, list) or not repositories:
            raise ValueError(f"{scenario_id}.repositories must be non-empty")
        if not all(repository in REPOSITORIES for repository in repositories):
            raise ValueError(f"{scenario_id}.repositories contains an unknown repository")
        if scenario["type"] == "comprehensive" and scenario.get("subtype") not in {
            "aggregate",
            "relational",
        }:
            raise ValueError(f"{scenario_id} comprehensive questions require a subtype")
    return scenarios


def _query_intent(question: str) -> QueryIntent:
    """Map the fixed demo wording to the public query intent contract."""
    normalized = question.casefold()
    if "relate" in normalized or "relationship" in normalized:
        return QueryIntent.RELATIONAL
    if "compare" in normalized:
        return QueryIntent.COMPARATIVE
    if "list" in normalized or "recorded" in normalized:
        return QueryIntent.AGGREGATE
    return QueryIntent.FACTUAL


class FixtureQueryService:
    """Adapt the deterministic evaluation executor to the query API contract."""

    def __init__(self) -> None:
        self.executor = FixtureExecutor(FIXTURE_PATH, strategy="routed", top_k=10)

    def query(self, query_request: QueryRequest, _user_id: str) -> QueryResult:
        """Return a validated evidence-backed result from the frozen fixture."""
        raw = self.executor.query(query_request.model_dump(mode="json"))
        evidence = [Evidence.model_validate(item) for item in raw["evidence"]]
        claims = [Claim.model_validate(item) for item in raw["claims"]]
        counts = Counter(item.source_type for item in evidence)
        filters = query_request.filters
        repositories = filters.repositories or list(
            dict.fromkeys(item.repository for item in evidence)
        )
        coverage = Coverage(
            repositories=repositories,
            date_from=filters.date_from,
            date_to=filters.date_to,
            counts=dict(counts),
            last_synced_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )
        trace = RetrievalTrace(
            intent=_query_intent(query_request.question),
            strategy=RetrievalStrategy.HYBRID,
            applied_filters=filters,
            explicit_filters=filters,
        )
        return QueryResult(
            answer=str(raw["answer"]),
            claims=claims,
            evidence=evidence,
            coverage=coverage,
            latency_ms=int(raw["latency_ms"]),
            trace=trace,
        )


class OpenScoutClient:
    """Small authenticated client used by the Stage A acceptance test."""

    def __init__(self, http_client: FlaskClient) -> None:
        self.http_client = http_client

    def query(self, scenario: dict[str, Any]) -> dict[str, Any]:
        """Execute one demo scenario through the public query route."""
        response = self.http_client.post(
            "/api/intelligence/query",
            headers={"Authorization": "Bearer stage-a-test"},
            json={
                "question": scenario["question"],
                "filters": {
                    "repositories": scenario["repositories"],
                    "date_from": scenario.get("date_from"),
                    "date_to": scenario.get("date_to"),
                },
            },
        )
        assert response.status_code == 200, response.get_json()
        result = response.get_json()
        assert isinstance(result, dict)
        return result


@pytest.fixture
def openscout_client(monkeypatch: pytest.MonkeyPatch) -> OpenScoutClient:
    """Build an isolated API app backed by the recorded Stage A fixture."""
    app = Flask(__name__)
    api = Api(app)
    api.add_namespace(intelligence_ns)
    service = FixtureQueryService()

    @app.before_request
    def set_test_token() -> None:
        request.decoded_token = (
            {"sub": "stage-a-demo"}
            if request.headers.get("Authorization")
            else None
        )

    monkeypatch.setattr(
        "docsgpt.api.user.intelligence.routes.build_query_service",
        lambda: service,
    )
    return OpenScoutClient(app.test_client())


def test_stage_a_demo_has_no_uncited_fact(openscout_client: OpenScoutClient) -> None:
    """Run all five demo paths and reject factual claims without evidence."""
    scenarios = load_demo_scenarios()
    assert {scenario["id"] for scenario in scenarios} == {
        "discover-trends",
        "representative-issues",
        "release-relationship",
        "compare-products",
        "generate-report",
    }

    results = []
    for scenario in scenarios:
        result = openscout_client.query(scenario)
        assert result["claims"]
        assert result["evidence"]
        assert all(
            claim["evidence_ids"]
            for claim in result["claims"]
            if claim["kind"] in {"fact", "statistic"}
        )
        assert all(
            evidence["source_url"].startswith("https://github.com/")
            for evidence in result["evidence"]
        )
        results.append(result)

    report_service = ReportService()
    report = report_service.create(
        "stage-a-demo",
        REPOSITORIES,
        [results[-1]],
    )
    markdown = report_service.export(report["id"], "markdown").decode("utf-8")
    assert all(heading in markdown for heading in REPORT_SECTION_HEADINGS)
    assert "https://github.com/" in markdown
