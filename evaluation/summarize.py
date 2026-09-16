"""Summarize two OpenScout evaluation JSONL runs."""

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
    parser.add_argument("--baseline", required=True, help="baseline name or JSONL path")
    parser.add_argument(
        "--candidate", required=True, help="candidate name or JSONL path"
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

    def result_path(value: str) -> Path:
        candidate = Path(value)
        if candidate.exists():
            return candidate.resolve()
        return results_dir / f"{value}.{args.split}.jsonl"

    baseline_path = result_path(args.baseline)
    candidate_path = result_path(args.candidate)
    output_path = (
        Path(args.output).resolve()
        if args.output
        else results_dir / f"{args.baseline}-vs-{args.candidate}.{args.split}.md"
    )
    try:
        summary = summarize_paths(
            baseline_path,
            candidate_path,
            baseline_name=args.baseline,
            candidate_name=args.candidate,
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
    "SUMMARY_METRICS",
    "TRACKED_METRICS",
    "aggregate_records",
    "load_records",
    "render_summary",
    "summarize_paths",
]
