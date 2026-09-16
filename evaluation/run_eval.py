"""Run reproducible OpenScout evaluations against a query executor."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from .metrics import citation_precision, ndcg_at_k, recall_at_k
except ImportError:  # pragma: no cover - exercised by the file entry point
    from metrics import citation_precision, ndcg_at_k, recall_at_k


QUESTION_TYPES = {"factual", "temporal", "comparative", "comprehensive"}
REQUIRED_QUESTION_FIELDS = {
    "id",
    "snapshot_id",
    "type",
    "question",
    "answer_points",
    "evidence_urls",
    "repositories",
    "date_from",
    "date_to",
    "acceptance",
}
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class FixtureRecord:
    """A normalized record read from the committed intelligence fixture."""

    id: str
    repository: str
    source_type: str
    title: str
    body: str
    source_url: str
    occurred_at: datetime | None
    labels: tuple[str, ...] = ()
    version: str | None = None


def _as_mapping(value: Any) -> dict[str, Any]:
    """Convert a Pydantic response or mapping to a plain dictionary."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise TypeError("query executor must return a mapping or Pydantic model")
    return dict(value)


def _resolve_path(value: str | Path, config_path: Path) -> Path:
    """Resolve a config path from the repository or config directory."""
    raw_path = Path(value)
    if raw_path.is_absolute():
        return raw_path
    project_root = Path(__file__).resolve().parent.parent
    candidates = (
        Path.cwd() / raw_path,
        project_root / raw_path,
        config_path.parent / raw_path,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _parse_date(value: Any, field_name: str) -> date | None:
    """Parse an optional ISO date from a question or filter."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date or null")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date or null") from exc


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a fixture timestamp without requiring a date-time dependency."""
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    """Return a UTC timestamp representation for a run record."""
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def config_hash(config: Mapping[str, Any]) -> str:
    """Hash a parsed YAML config using canonical JSON serialization."""
    payload = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_config(path: str | Path) -> tuple[dict[str, Any], Path]:
    """Load and minimally validate an evaluation YAML config."""
    config_path = Path(path).resolve()
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, Mapping):
        raise ValueError("evaluation config must be a YAML object")
    config = dict(config)
    if not config.get("snapshot_id"):
        raise ValueError("evaluation config requires snapshot_id")
    if not isinstance(config.get("dataset"), Mapping):
        raise ValueError("evaluation config requires dataset paths")
    if not isinstance(config.get("executor"), Mapping):
        raise ValueError("evaluation config requires an executor")
    return config, config_path


def load_questions(path: str | Path, snapshot_id: str) -> list[dict[str, Any]]:
    """Load and validate one fixed-snapshot JSONL question split."""
    questions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    question_path = Path(path)
    with question_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                question = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{question_path}:{line_number} is not valid JSON"
                ) from exc
            if not isinstance(question, Mapping):
                raise ValueError(f"{question_path}:{line_number} must be a JSON object")
            question = dict(question)
            missing = REQUIRED_QUESTION_FIELDS - question.keys()
            if missing:
                missing_fields = ", ".join(sorted(missing))
                raise ValueError(
                    f"{question_path}:{line_number} is missing {missing_fields}"
                )
            question_id = question["id"]
            if not isinstance(question_id, str) or not question_id:
                raise ValueError(f"{question_path}:{line_number} requires a string id")
            if question_id in seen_ids:
                raise ValueError(f"duplicate question id: {question_id}")
            seen_ids.add(question_id)
            if question["snapshot_id"] != snapshot_id:
                raise ValueError(
                    f"{question_id} belongs to snapshot {question['snapshot_id']!r}, "
                    f"not {snapshot_id!r}"
                )
            question_type = question["type"]
            if question_type not in QUESTION_TYPES:
                raise ValueError(f"{question_id} has unsupported type {question_type!r}")
            for field_name in ("answer_points", "evidence_urls", "repositories"):
                values = question[field_name]
                if not isinstance(values, list) or not all(
                    isinstance(item, str) and item for item in values
                ):
                    raise ValueError(f"{question_id}.{field_name} must be a list of strings")
            if not isinstance(question["question"], str) or not question["question"].strip():
                raise ValueError(f"{question_id}.question must be non-empty")
            if not isinstance(question["acceptance"], Mapping):
                raise ValueError(f"{question_id}.acceptance must be an object")
            start = _parse_date(question["date_from"], f"{question_id}.date_from")
            end = _parse_date(question["date_to"], f"{question_id}.date_to")
            if start and end and end < start:
                raise ValueError(f"{question_id} has a reversed date range")
            if question_type == "comprehensive" and question.get("subtype") not in {
                "aggregate",
                "relational",
            }:
                raise ValueError(
                    f"{question_id} comprehensive questions require aggregate or relational subtype"
                )
            questions.append(question)
    if not questions:
        raise ValueError(f"{question_path} contains no questions")
    return questions


def _tokens(value: str) -> set[str]:
    """Tokenize English fixture text deterministically for the local proxy."""
    return {token.casefold() for token in TOKEN_PATTERN.findall(value)}


def _fixture_records(corpus_path: Path) -> list[FixtureRecord]:
    """Read normalized records from a recorded GitHub fixture."""
    with corpus_path.open(encoding="utf-8") as stream:
        corpus = json.load(stream)
    raw_records = corpus.get("expected") if isinstance(corpus, Mapping) else None
    if not isinstance(raw_records, list):
        raise ValueError("fixture corpus must contain an expected record list")

    records: list[FixtureRecord] = []
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            raise ValueError("fixture records must be JSON objects")
        source_type = str(raw.get("source_type") or "")
        repository = str(raw.get("repository") or "")
        source_url = str(raw.get("source_url") or "")
        external_id = str(raw.get("external_id") or source_url)
        if not repository or not source_type or not source_url:
            raise ValueError("fixture record is missing repository, source_type, or source_url")
        occurred_at = next(
            (
                _parse_datetime(raw.get(field_name))
                for field_name in ("published_at", "created_at", "updated_at")
                if raw.get(field_name)
            ),
            None,
        )
        record_id = str(raw.get("id") or f"{repository}:{source_type}:{external_id}")
        labels = tuple(str(label) for label in raw.get("labels") or [])
        records.append(
            FixtureRecord(
                id=record_id,
                repository=repository,
                source_type=source_type,
                title=str(raw.get("title") or ""),
                body=str(raw.get("body") or ""),
                source_url=source_url,
                occurred_at=occurred_at,
                labels=labels,
                version=str(raw["version"]) if raw.get("version") else None,
            )
        )
    if not records:
        raise ValueError("fixture corpus contains no records")
    return records


class FixtureExecutor:
    """Deterministic lexical proxy for a query executor on the fixed fixture."""

    name = "fixture_lexical_proxy"
    model = "lexical-proxy-v1"

    def __init__(self, corpus_path: str | Path, strategy: str, top_k: int = 10) -> None:
        """Load the fixture and configure the comparison strategy."""
        self.records = _fixture_records(Path(corpus_path))
        self.strategy = strategy
        self.top_k = max(1, int(top_k))

    def _filter_records(self, filters: Mapping[str, Any]) -> list[FixtureRecord]:
        """Apply repository, source, and date filters from the query payload."""
        repositories = {
            str(repository).casefold()
            for repository in filters.get("repositories") or []
        }
        source_types = {
            str(source_type).casefold()
            for source_type in filters.get("source_types") or []
        }
        date_from = _parse_date(filters.get("date_from"), "filters.date_from")
        date_to = _parse_date(filters.get("date_to"), "filters.date_to")
        selected: list[FixtureRecord] = []
        for record in self.records:
            if repositories and record.repository.casefold() not in repositories:
                continue
            if source_types and record.source_type.casefold() not in source_types:
                continue
            if date_from or date_to:
                if record.occurred_at is None:
                    continue
                occurred = record.occurred_at.date()
                if date_from and occurred < date_from:
                    continue
                if date_to and occurred > date_to:
                    continue
            selected.append(record)
        return selected

    def _score(self, question: str, record: FixtureRecord) -> float:
        """Score one fixture record without reading expected answer URLs."""
        query_tokens = _tokens(question)
        if not query_tokens:
            return 0.0
        searchable = " ".join(
            (
                record.repository,
                record.source_type.replace("_", " "),
                record.title,
                record.body,
                " ".join(record.labels),
                record.version or "",
            )
        )
        record_tokens = _tokens(searchable)
        overlap = query_tokens & record_tokens
        score = len(overlap) / len(query_tokens)
        if self.strategy == "hybrid":
            title_overlap = len(query_tokens & _tokens(record.title))
            score += 0.25 * title_overlap / len(query_tokens)
        return score

    def _rank(self, question: str, filters: Mapping[str, Any]) -> list[FixtureRecord]:
        """Return deterministic top-k records for a query payload."""
        scored = [
            (self._score(question, record), record)
            for record in self._filter_records(filters)
        ]
        scored = [(score, record) for score, record in scored if score > 0]
        scored.sort(key=lambda item: (-item[0], item[1].source_url))
        return [record for _, record in scored[: self.top_k]]

    @staticmethod
    def _evidence(record: FixtureRecord) -> dict[str, Any]:
        """Render a fixture record in the query API evidence shape."""
        return {
            "id": record.id,
            "record_id": record.id,
            "repository": record.repository,
            "source_type": record.source_type,
            "title": record.title,
            "excerpt": record.body[:500],
            "source_url": record.source_url,
            "occurred_at": _timestamp(record.occurred_at)
            if record.occurred_at
            else None,
        }

    def query(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Execute a POST /api/intelligence/query-compatible payload."""
        started = time.perf_counter()
        question = str(payload.get("question") or "")
        filters = payload.get("filters") or {}
        if not isinstance(filters, Mapping):
            raise ValueError("query filters must be an object")
        ranked = self._rank(question, filters)
        evidence = [self._evidence(record) for record in ranked]
        retrieved_urls = [record.source_url for record in ranked]
        cited_urls = retrieved_urls[:3]
        answer = " ".join(
            f"{record.repository} {record.source_type}: {record.title}"
            f" ({record.occurred_at.date().isoformat() if record.occurred_at else 'undated'}). "
            f"{record.body}"
            for record in ranked
        )
        if not answer:
            answer = "No matching evidence was found in the recorded snapshot."
        claims = [
            {
                "id": f"proxy-claim-{index}",
                "text": f"{record.title}: {record.body}",
                "kind": "fact",
                "evidence_ids": [record.id],
                "confidence": "low",
            }
            for index, record in enumerate(ranked[:3], start=1)
        ]
        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        return {
            "answer": answer,
            "claims": claims,
            "evidence": evidence,
            "retrieved_urls": retrieved_urls,
            "cited_urls": cited_urls,
            "latency_ms": latency_ms,
            "usage": {
                "input_tokens": len(_tokens(question)),
                "output_tokens": len(_tokens(answer)),
            },
            "model": self.model,
            "executor": self.name,
            "status": "measured_fixture",
        }


def _invoke_executor(executor: Any, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Invoke a callable, query method, or execute method supplied by a caller."""
    query = getattr(executor, "query", None)
    if callable(query):
        return _as_mapping(query(payload))
    execute = getattr(executor, "execute", None)
    if callable(execute):
        return _as_mapping(execute(payload))
    if callable(executor):
        return _as_mapping(executor(payload))
    raise TypeError("executor must be callable or expose query/execute")


def _item_url(item: Any) -> str | None:
    """Extract a source URL from a mapping, model, or URL-like value."""
    if isinstance(item, str):
        return item
    if hasattr(item, "model_dump"):
        item = item.model_dump(mode="json")
    if isinstance(item, Mapping):
        value = item.get("source_url") or item.get("url")
    else:
        value = getattr(item, "source_url", None) or getattr(item, "url", None)
    return str(value) if value else None


def _urls_from(value: Any) -> list[str]:
    """Normalize a response URL collection while preserving rank order."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [url for item in value if (url := _item_url(item))]


def _response_urls(response: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Extract ranked and cited URLs from common query response shapes."""
    evidence = response.get("evidence") or []
    evidence_urls = _urls_from(evidence)
    retrieved_urls = _urls_from(response.get("retrieved_urls"))
    if not retrieved_urls:
        retrieved_urls = evidence_urls

    cited_urls = _urls_from(response.get("cited_urls"))
    if not cited_urls:
        cited_urls = _urls_from(response.get("citations"))
    if not cited_urls:
        evidence_by_id = {}
        for item in evidence:
            if hasattr(item, "model_dump"):
                item = item.model_dump(mode="json")
            if isinstance(item, Mapping) and item.get("id") and _item_url(item):
                evidence_by_id[str(item["id"])] = str(_item_url(item))
        for claim in response.get("claims") or []:
            if hasattr(claim, "model_dump"):
                claim = claim.model_dump(mode="json")
            if not isinstance(claim, Mapping):
                continue
            for evidence_id in claim.get("evidence_ids") or []:
                url = evidence_by_id.get(str(evidence_id))
                if url and url not in cited_urls:
                    cited_urls.append(url)
    return retrieved_urls, cited_urls


def _response_usage(response: Mapping[str, Any]) -> tuple[int, int]:
    """Extract token counts from a response or return zero when unavailable."""
    usage = response.get("usage") or {}
    if not isinstance(usage, Mapping):
        usage = {}
    input_tokens = usage.get("input_tokens", response.get("input_tokens", 0))
    output_tokens = usage.get("output_tokens", response.get("output_tokens", 0))
    try:
        return max(0, int(input_tokens)), max(0, int(output_tokens))
    except (TypeError, ValueError):
        return 0, 0


def _answer_score(answer: str, answer_points: Sequence[str]) -> float:
    """Score the fraction of manually supplied answer points in an answer."""
    if not answer_points:
        return 0.0
    normalized_answer = " ".join(answer.casefold().split())
    matched = sum(
        " ".join(point.casefold().split()) in normalized_answer
        for point in answer_points
    )
    return matched / len(answer_points)


def _numeric(value: Any, default: float = 0.0) -> float:
    """Convert an optional score to a bounded float."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


def _build_record(
    *,
    run_id: str,
    timestamp: str,
    config: Mapping[str, Any],
    config_digest: str,
    question: Mapping[str, Any],
    response: Mapping[str, Any],
    elapsed_ms: int,
) -> dict[str, Any]:
    """Build one JSONL record with the stable evaluation schema."""
    retrieved_urls, cited_urls = _response_urls(response)
    expected_urls = [str(url) for url in question["evidence_urls"]]
    answer = str(response.get("answer") or "")
    answer_score = _answer_score(answer, question["answer_points"])
    citation_score = citation_precision(cited_urls, expected_urls)
    supplied_faithfulness = response.get("faithfulness_score")
    faithfulness_score = (
        _numeric(supplied_faithfulness)
        if supplied_faithfulness is not None
        else answer_score * citation_score
    )
    input_tokens, output_tokens = _response_usage(response)
    model_config = config.get("model") or {}
    if not isinstance(model_config, Mapping):
        model_config = {}
    model = str(response.get("model") or model_config.get("name") or "unknown")
    latency = response.get("latency_ms", elapsed_ms)
    try:
        latency_ms = max(0, int(latency))
    except (TypeError, ValueError):
        latency_ms = elapsed_ms
    executor_config = config.get("executor") or {}
    strategy = (
        executor_config.get("strategy", "unknown")
        if isinstance(executor_config, Mapping)
        else "unknown"
    )
    return {
        "run_id": run_id,
        "snapshot_id": config["snapshot_id"],
        "config_hash": config_digest,
        "question_id": question["id"],
        "question_type": question["type"],
        "question_subtype": question.get("subtype"),
        "expected_urls": expected_urls,
        "retrieved_urls": retrieved_urls,
        "retrieved_ranks": {
            url: rank for rank, url in enumerate(retrieved_urls, start=1)
        },
        "cited_urls": cited_urls,
        "answer_rule": question["acceptance"],
        "answer_score": answer_score,
        "answer_rule_score": answer_score,
        "citation_score": citation_score,
        "faithfulness_score": faithfulness_score,
        "recall_at_5": recall_at_k(expected_urls, retrieved_urls, 5),
        "ndcg_at_10": ndcg_at_k(expected_urls, retrieved_urls, 10),
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model": model,
        "executor": str(response.get("executor") or "custom"),
        "status": str(response.get("status") or "measured"),
        "retrieval_strategy": str(strategy),
        "timestamp": timestamp,
    }


def run_evaluation(
    config_path: str | Path,
    split: str,
    *,
    executor: Any | None = None,
    output_path: str | Path | None = None,
    force: bool = False,
    freeze: bool = False,
    now: datetime | None = None,
) -> Path:
    """Run one split and write an immutable JSONL result file.

    Args:
        config_path: YAML configuration path.
        split: Dataset split, normally dev or holdout.
        executor: Optional callable or query-compatible object. If omitted,
            the configured recorded fixture executor is used.
        output_path: Optional result destination.
        force: Allow an explicit overwrite of an existing development result.
        freeze: Mark this run as a holdout freeze; frozen outputs cannot
            overwrite an existing file.
        now: Optional timestamp injection for deterministic tests.

    Returns:
        The path of the newly written JSONL result file.
    """
    if split not in {"dev", "holdout"}:
        raise ValueError("split must be dev or holdout")
    if freeze and split != "holdout":
        raise ValueError("only the holdout split can be frozen")
    config, resolved_config_path = load_config(config_path)
    dataset_value = config["dataset"].get(split)
    if not dataset_value:
        raise ValueError(f"evaluation config has no dataset for {split}")
    dataset_path = _resolve_path(str(dataset_value), resolved_config_path)
    questions = load_questions(dataset_path, str(config["snapshot_id"]))
    executor_config = config["executor"]
    if not isinstance(executor_config, Mapping):
        raise ValueError("executor config must be an object")
    if executor is None:
        executor_type = str(executor_config.get("type") or "")
        if executor_type != "fixture":
            raise ValueError(
                "no executor supplied; only the fixture executor is available offline"
            )
        corpus_value = executor_config.get("corpus")
        if not corpus_value:
            raise ValueError("fixture executor requires corpus")
        executor = FixtureExecutor(
            _resolve_path(str(corpus_value), resolved_config_path),
            strategy=str(executor_config.get("strategy") or "vector"),
            top_k=int(executor_config.get("top_k", 10)),
        )

    name = str(config.get("name") or Path(config_path).stem)
    destination = (
        Path(output_path)
        if output_path
        else DEFAULT_RESULTS_DIR / f"{name}.{split}.jsonl"
    )
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if split == "holdout" or freeze:
            raise FileExistsError(
                f"result already exists: {destination}; holdout outputs are immutable"
            )
        if not force:
            raise FileExistsError(
                f"result already exists: {destination}; use --force for a development rerun"
            )

    run_id = uuid.uuid4().hex
    timestamp = _timestamp(now)
    digest = config_hash(config)
    records: list[dict[str, Any]] = []
    for question in questions:
        payload = {
            "question": question["question"],
            "filters": {
                "repositories": question["repositories"],
                "date_from": question["date_from"],
                "date_to": question["date_to"],
            },
        }
        started = time.perf_counter()
        response = _invoke_executor(executor, payload)
        elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
        records.append(
            _build_record(
                run_id=run_id,
                timestamp=timestamp,
                config=config,
                config_digest=digest,
                question=question,
                response=response,
                elapsed_ms=elapsed_ms,
            )
        )

    mode = "w" if force else "x"
    with destination.open(mode, encoding="utf-8") as stream:
        for record in records:
            stream.write(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            )
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    """Run the evaluation command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="evaluation YAML config")
    parser.add_argument("--split", choices=("dev", "holdout"), required=True)
    parser.add_argument("--output", help="optional JSONL output path")
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="freeze a holdout output and refuse overwrites",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="explicitly overwrite a development output",
    )
    args = parser.parse_args(argv)
    try:
        destination = run_evaluation(
            args.config,
            args.split,
            output_path=args.output,
            force=args.force,
            freeze=args.freeze,
        )
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "FixtureExecutor",
    "config_hash",
    "load_config",
    "load_questions",
    "run_evaluation",
]
