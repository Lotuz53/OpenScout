"""Check OpenScout evaluation metrics against a committed baseline."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

try:
    from .summarize import TRACKED_METRICS, aggregate_records, load_records
except ImportError:  # pragma: no cover - exercised by the file entry point
    from summarize import TRACKED_METRICS, aggregate_records, load_records


def _metric_values(path: str | Path) -> dict[str, float]:
    """Read metrics from JSONL records, a summary JSON object, or a metric map."""
    source_path = Path(path)
    if source_path.suffix == ".jsonl":
        return {
            key: float(value)
            for key, value in aggregate_records(load_records(source_path))["metrics"].items()
        }
    with source_path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if isinstance(value, list):
        records = [item for item in value if isinstance(item, Mapping)]
        return {
            key: float(metric)
            for key, metric in aggregate_records(records)["metrics"].items()
        }
    if not isinstance(value, Mapping):
        raise ValueError(f"{source_path} must contain a JSON object or array")
    metrics = value.get("metrics", value)
    if not isinstance(metrics, Mapping):
        raise ValueError(f"{source_path} does not contain a metric mapping")
    result: dict[str, float] = {}
    for key, metric in metrics.items():
        try:
            result[str(key)] = float(metric)
        except (TypeError, ValueError):
            continue
    return result


def check_regression(
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    max_drop: float = 0.05,
) -> list[str]:
    """Return tracked metrics that dropped more than max_drop points."""
    if max_drop < 0:
        raise ValueError("max_drop must be non-negative")
    baseline = _metric_values(baseline_path)
    candidate = _metric_values(candidate_path)
    failures: list[str] = []
    for metric in TRACKED_METRICS:
        if metric not in baseline or metric not in candidate:
            failures.append(f"{metric}: missing from baseline or candidate")
            continue
        drop = baseline[metric] - candidate[metric]
        if drop > max_drop:
            failures.append(
                f"{metric}: dropped {drop:.3f} "
                f"(baseline {baseline[metric]:.3f}, candidate {candidate[metric]:.3f})"
            )
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    """Run the regression gate command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--max-drop", type=float, default=0.05)
    args = parser.parse_args(argv)
    try:
        failures = check_regression(
            args.baseline,
            args.candidate,
            max_drop=args.max_drop,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"regression check failed: {exc}", file=sys.stderr)
        return 2
    if failures:
        print("regression gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"regression gate passed: no tracked metric dropped more than {args.max_drop:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["check_regression", "main"]
