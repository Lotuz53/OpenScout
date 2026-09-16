"""Summarize OpenScout evaluation runs and Stage A release gates."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any

try:
    from .metrics import citation_precision, ndcg_at_k, recall_at_k
except ImportError:  # pragma: no cover - exercised by the file entry point
    from metrics import citation_precision, ndcg_at_k, recall_at_k


TRACKED_METRICS = (
    "recall_at_5",
    "ndcg_at_10",
    "answer_score",
    "citation_score",
    "faithfulness_score",
)
SUMMARY_METRICS = TRACKED_METRICS + ("latency_ms", "input_tokens", "output_tokens")
RELEASE_GATE_THRESHOLDS = {
    "factual_accuracy": 0.80,
    "citation_precision": 0.90,
    "complex_success": 0.75,
    "non_graphrag_latency_ms": 10_000.0,
}


def load_records(path: str | Path) -> list[dict[str, Any]]:
    """Read one JSONL result file."""
    result_path = Path(path)
    records: list[dict[str, Any]] = []
    with result_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, Mapping):
                raise ValueError(f"{result_path}:{line_number} must be a JSON object")
            records.append(dict(value))
    if not records:
        raise ValueError(f"{result_path} contains no result records")
    return records


def _metric_value(record: Mapping[str, Any], metric: str) -> float | None:
    """Read a metric, calculating retrieval metrics for older result files."""
    value = record.get(metric)
    if value is None and metric == "recall_at_5":
        value = recall_at_k(
            record.get("expected_urls") or [],
            record.get("retrieved_urls") or [],
            5,
        )
    elif value is None and metric == "ndcg_at_10":
        value = ndcg_at_k(
            record.get("expected_urls") or [],
            record.get("retrieved_urls") or [],
            10,
        )
    elif value is None and metric == "citation_score":
        value = citation_precision(
            record.get("cited_urls") or [],
            record.get("expected_urls") or [],
        )
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def aggregate_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return means for tracked metrics and operational measurements."""
    metrics: dict[str, float] = {}
    for metric in SUMMARY_METRICS:
        values = [
            value
            for record in records
            if (value := _metric_value(record, metric)) is not None
        ]
        if values:
            metrics[metric] = mean(values)
    return {"questions": len(records), "metrics": metrics}


def _mean_metric(records: Sequence[Mapping[str, Any]], metric: str) -> float | None:
    """Return one metric mean while preserving missing-data information."""
    values = [
        value
        for record in records
        if (value := _metric_value(record, metric)) is not None
    ]
    return mean(values) if values else None


def release_gate_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate the measured Stage A quality gates from frozen records."""
    factual = [record for record in records if record.get("question_type") == "factual"]
    complex_questions = [
        record
        for record in records
        if record.get("question_type") in {"comparative", "comprehensive"}
    ]
    non_graphrag = [
        record for record in records if record.get("question_subtype") != "relational"
    ]
    input_tokens = _mean_metric(records, "input_tokens")
    output_tokens = _mean_metric(records, "output_tokens")
    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    return {
        "factual_accuracy": {
            "value": _mean_metric(factual, "answer_score"),
            "threshold": RELEASE_GATE_THRESHOLDS["factual_accuracy"],
            "sample_size": len(factual),
        },
        "citation_precision": {
            "value": _mean_metric(records, "citation_score"),
            "threshold": RELEASE_GATE_THRESHOLDS["citation_precision"],
            "sample_size": len(records),
        },
        "complex_success": {
            "value": _mean_metric(complex_questions, "answer_score"),
            "threshold": RELEASE_GATE_THRESHOLDS["complex_success"],
            "sample_size": len(complex_questions),
        },
        "non_graphrag_latency_ms": {
            "value": _mean_metric(non_graphrag, "latency_ms"),
            "threshold": RELEASE_GATE_THRESHOLDS["non_graphrag_latency_ms"],
            "sample_size": len(non_graphrag),
        },
        "token_cost": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "sample_size": len(records),
        },
        "question_type_metrics": {
            question_type: aggregate_records(
                [record for record in records if record.get("question_type") == question_type]
            )
            for question_type in sorted(
                {
                    str(record.get("question_type"))
                    for record in records
                    if record.get("question_type")
                }
            )
        },
    }


def _demo_contract_status() -> tuple[bool, str]:
    """Check the five demo scenarios against the same recorded fixture."""
    try:
        from .run_eval import FixtureExecutor
    except ImportError:  # pragma: no cover - exercised by the file entry point
        from run_eval import FixtureExecutor

    project_root = Path(__file__).resolve().parent.parent
    demo_path = project_root / "evaluation/demo/questions.json"
    fixture_path = project_root / "tests/intelligence/fixtures/github_objects.json"
    with demo_path.open(encoding="utf-8") as stream:
        scenarios = json.load(stream)
    if not isinstance(scenarios, list) or len(scenarios) != 5:
        return False, "expected exactly five demo scenarios"

    executor = FixtureExecutor(fixture_path, strategy="routed", top_k=10)
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            return False, "demo scenario is not an object"
        response = executor.query(
            {
                "question": scenario.get("question"),
                "filters": {
                    "repositories": scenario.get("repositories"),
                    "date_from": scenario.get("date_from"),
                    "date_to": scenario.get("date_to"),
                },
            }
        )
        evidence_by_id = {
            str(item.get("id")): item
            for item in response.get("evidence") or []
            if isinstance(item, Mapping) and item.get("id")
        }
        if not response.get("claims") or not evidence_by_id:
            return False, f"{scenario.get('id', 'unknown')} has no claims or evidence"
        for claim in response["claims"]:
            if not isinstance(claim, Mapping):
                return False, f"{scenario.get('id', 'unknown')} has an invalid claim"
            if claim.get("kind") in {"fact", "statistic"} and not claim.get("evidence_ids"):
                return False, f"{scenario.get('id', 'unknown')} has an uncited fact"
        if not all(
            str(item.get("source_url", "")).startswith("https://github.com/")
            for item in evidence_by_id.values()
        ):
            return False, f"{scenario.get('id', 'unknown')} has a non-GitHub source"
    return True, "5/5 scenarios passed the fixture evidence contract"


def _format_gate_value(value: float | None, metric: str) -> str:
    """Format a gate measurement for Markdown."""
    if value is None:
        return "n/a"
    if metric.endswith("_ms"):
        return f"{value:.1f} ms"
    return f"{value:.3f}"


def render_release_gates(
    result_name: str,
    records: Sequence[Mapping[str, Any]],
    *,
    demo_passed: bool,
    demo_detail: str,
) -> str:
    """Render measured Stage A gates and operational costs as Markdown."""
    measurements = release_gate_metrics(records)
    gate_rows = (
        ("factual_accuracy", "事实题正确率", "answer_score"),
        ("citation_precision", "引用精确率", "citation_score"),
        ("complex_success", "比较/综合问题成功率", "answer_score"),
        ("non_graphrag_latency_ms", "非 GraphRAG 平均延迟", "latency_ms"),
    )
    lines = [
        "# OpenScout Stage A 门槛实测摘要",
        "",
        f"- 结果文件：`{result_name}`",
        f"- 题目数：{len(records)}（封存 holdout）",
        "- 执行器：提交到仓库的 deterministic lexical proxy；不是生产 embedding 或线上延迟测量。",
        "- 非 GraphRAG 延迟排除了 `question_subtype=relational` 的题目。",
        "- token 成本以平均 input/output/total tokens 报告；当前没有货币价格模型。",
        "",
        "## 质量门槛",
        "",
        "| 门槛 | 实测值 | 要求 | 结果 | 样本数 |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    measured_passed = True
    for gate_name, label, metric in gate_rows:
        measurement = measurements[gate_name]
        value = measurement["value"]
        threshold = measurement["threshold"]
        passed = (
            value is not None
            and (value <= threshold if gate_name.endswith("latency_ms") else value >= threshold)
        )
        measured_passed = measured_passed and passed
        operator = "≤" if gate_name.endswith("latency_ms") else "≥"
        lines.append(
            f"| {label} | {_format_gate_value(value, metric)} | "
            f"{operator} {_format_gate_value(threshold, metric)} | "
            f"{'PASS' if passed else 'FAIL'} | {measurement['sample_size']} |"
        )

    demo_status = "PASS" if demo_passed else "FAIL"
    lines.extend(
        [
            f"| 五个演示场景无未引用事实 | {demo_detail} | 所有 fact/statistic claim 有 evidence_ids | {demo_status} | 5 |",
            "",
            "## Token 成本",
            "",
            "| 项目 | 平均值 | 样本数 |",
            "| --- | ---: | ---: |",
        ]
    )
    token_cost = measurements["token_cost"]
    for key, label in (
        ("input_tokens", "input tokens"),
        ("output_tokens", "output tokens"),
        ("total_tokens", "total tokens"),
    ):
        value = token_cost[key]
        lines.append(
            f"| {label} | {_format_gate_value(value, key)} | {token_cost['sample_size']} |"
        )

    lines.extend(
        [
            "",
            "## 分题型测量",
            "",
            "| 题型 | 样本数 | answer_score | citation_score | latency_ms |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for question_type, summary in measurements["question_type_metrics"].items():
        metrics = summary["metrics"]
        lines.append(
            f"| {question_type} | {summary['questions']} | "
            f"{_format_metric(metrics.get('answer_score'))} | "
            f"{_format_metric(metrics.get('citation_score'))} | "
            f"{_format_metric(metrics.get('latency_ms'))} |"
        )

    overall_passed = measured_passed and demo_passed
    lines.extend(
        [
            "",
            f"## 发布判断：{'PASS' if overall_passed else 'FAIL / 保留为实验'}",
            "",
            "本摘要只记录当前封存快照上的实测值；门槛未通过时不得在 README、简历或演示中宣称 Stage A 已达标。",
            f"演示检查：{demo_detail}。运行时路由验收仍由 `tests/integration/test_openscout_stage_a.py` 覆盖。",
            "",
        ]
    )
    return "\n".join(lines)


def summarize_release_gates(result_path: str | Path) -> str:
    """Load a frozen result and return the Stage A release-gate summary."""
    records = load_records(result_path)
    demo_passed, demo_detail = _demo_contract_status()
    return render_release_gates(
        Path(result_path).name,
        records,
        demo_passed=demo_passed,
        demo_detail=demo_detail,
    )


def _format_metric(value: float | None) -> str:
    """Format a metric for a compact Markdown comparison table."""
    return "n/a" if value is None else f"{value:.3f}"


def render_summary(
    baseline_name: str,
    candidate_name: str,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> str:
    """Render a Markdown comparison with the promotion decision."""
    baseline_metrics = baseline.get("metrics") or {}
    candidate_metrics = candidate.get("metrics") or {}
    lines = [
        f"# OpenScout evaluation: {baseline_name} vs {candidate_name}",
        "",
        "| Metric | Baseline | Candidate | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for metric in SUMMARY_METRICS:
        baseline_value = baseline_metrics.get(metric)
        candidate_value = candidate_metrics.get(metric)
        delta = (
            candidate_value - baseline_value
            if isinstance(baseline_value, (int, float))
            and isinstance(candidate_value, (int, float))
            else None
        )
        lines.append(
            f"| {metric} | {_format_metric(baseline_value)} | "
            f"{_format_metric(candidate_value)} | {_format_metric(delta)} |"
        )
    lines.extend(
        [
            "",
            f"- Questions: baseline {baseline.get('questions', 0)}, "
            f"candidate {candidate.get('questions', 0)}.",
            "- Measurement status: deterministic lexical proxy over the committed "
            "Stage A fixture; this is not production embedding or hybrid quality evidence.",
            "- Promotion decision: Hybrid remains non-default "
            "(promotion.default: false) until production measurements and review support promotion.",
        ]
    )
    return "\n".join(lines) + "\n"


def summarize_paths(
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    baseline_name: str = "baseline",
    candidate_name: str = "candidate",
) -> str:
    """Load two JSONL runs and return their Markdown comparison."""
    baseline_records = load_records(baseline_path)
    candidate_records = load_records(candidate_path)
    return render_summary(
        baseline_name,
        candidate_name,
        aggregate_records(baseline_records),
        aggregate_records(candidate_records),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the comparison command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", help="baseline name or JSONL path")
    parser.add_argument(
        "--candidate", help="candidate name or JSONL path"
    )
    parser.add_argument(
        "--release-gates",
        action="store_true",
        help="summarize the frozen routed holdout against Stage A release gates",
    )
    parser.add_argument("--split", default="dev", choices=("dev", "holdout"))
    parser.add_argument(
        "--results-dir",
        default=str(Path(__file__).resolve().parent / "results"),
    )
    parser.add_argument("--output", help="optional Markdown output path")
    parser.add_argument("--force", action="store_true", help="overwrite an existing summary")
    args = parser.parse_args(argv)
    results_dir = Path(args.results_dir).resolve()
    result_split = "holdout" if args.release_gates else args.split

    def result_path(value: str) -> Path:
        candidate = Path(value)
        if candidate.exists():
            return candidate.resolve()
        return results_dir / f"{value}.{result_split}.jsonl"

    try:
        if args.release_gates:
            candidate_name = args.candidate or "routed"
            candidate_path = result_path(candidate_name)
            summary = summarize_release_gates(candidate_path)
            output_path = (
                Path(args.output).resolve()
                if args.output
                else results_dir / "stage-a-summary.md"
            )
        else:
            if not args.baseline or not args.candidate:
                parser.error("--baseline and --candidate are required unless --release-gates is used")
            baseline_path = result_path(args.baseline)
            candidate_path = result_path(args.candidate)
            summary = summarize_paths(
                baseline_path,
                candidate_path,
                baseline_name=args.baseline,
                candidate_name=args.candidate,
            )
            output_path = (
                Path(args.output).resolve()
                if args.output
                else results_dir / f"{args.baseline}-vs-{args.candidate}.{args.split}.md"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and not args.force:
            raise FileExistsError(
                f"summary already exists: {output_path}; use --force to overwrite"
            )
        mode = "w" if args.force else "x"
        with output_path.open(mode, encoding="utf-8") as stream:
            stream.write(summary)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"summary failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RELEASE_GATE_THRESHOLDS",
    "SUMMARY_METRICS",
    "TRACKED_METRICS",
    "aggregate_records",
    "load_records",
    "release_gate_metrics",
    "render_release_gates",
    "render_summary",
    "summarize_release_gates",
    "summarize_paths",
]
