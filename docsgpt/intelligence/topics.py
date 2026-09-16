"""Deterministic issue-topic clustering and trend contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from pydantic import Field

from docsgpt.intelligence.schemas import IntelligenceModel, IntelligenceRecord, QueryFilters


ALGORITHM_VERSION = "spherical-kmeans-v1"
MAX_ITERATIONS = 50
_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*|[\u4e00-\u9fff]{2,}")
_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "and",
        "are",
        "been",
        "before",
        "being",
        "but",
        "can",
        "could",
        "does",
        "for",
        "from",
        "have",
        "into",
        "its",
        "more",
        "not",
        "our",
        "should",
        "that",
        "the",
        "their",
        "there",
        "these",
        "this",
        "through",
        "with",
        "would",
        "问题",
        "支持",
        "用户",
        "使用",
    }
)


class TopicCluster(IntelligenceModel):
    """A reproducible cluster of issue records."""

    id: str
    label: str
    record_ids: list[str] = Field(default_factory=list)
    centroid: list[float]
    snapshot_id: str
    algorithm_version: str = ALGORITHM_VERSION


class TopicTrend(IntelligenceModel):
    """A monthly count for one persisted topic and repository."""

    cluster_id: str
    label: str
    repository: str
    month: str
    count: int
    snapshot_id: str


def cluster_issues(
    issues: Sequence[IntelligenceRecord],
    vectors: Mapping[str, Sequence[float]],
    max_clusters: int = 12,
) -> list[TopicCluster]:
    """Cluster issue embeddings with deterministic spherical k-means.

    Records are sorted by a stable source id before any numeric operation. The
    first centroid is the smallest id and each following centroid is the
    vector farthest from the nearest selected centroid. This makes both the
    cluster numbering and the result independent of input order.

    Args:
        issues: Records whose embeddings should be grouped.
        vectors: Embeddings keyed by record id, stable source id, or external id.
        max_clusters: Upper bound for the number of clusters.

    Returns:
        Topic clusters with normalized centroids and a reproducible snapshot id.

    Raises:
        ValueError: If an embedding is missing, malformed, zero-length, or
            contains non-finite values.
    """
    if max_clusters < 1:
        raise ValueError("max_clusters must be positive")

    records = sorted(issues, key=_record_id)
    if not records:
        return []

    record_ids = [_record_id(record) for record in records]
    normalized_vectors = _normalized_vectors(records, vectors)
    cluster_count = min(
        len(records),
        int(max_clusters),
        max(2, round(math.sqrt(len(records) / 2))),
    )
    centroids = _initial_centroids(normalized_vectors, record_ids, cluster_count)
    assignments = _assign(normalized_vectors, centroids)

    for _ in range(MAX_ITERATIONS):
        updated_centroids = _update_centroids(normalized_vectors, assignments, centroids)
        updated_assignments = _assign(normalized_vectors, updated_centroids)
        centroids = updated_centroids
        if np.array_equal(assignments, updated_assignments):
            assignments = updated_assignments
            break
        assignments = updated_assignments

    assignments = _assign(normalized_vectors, centroids)
    provisional = [
        TopicCluster(
            id=f"topic-{index + 1}",
            label=_cluster_label(records, assignments, index),
            record_ids=[
                record_ids[row_index]
                for row_index, assignment in enumerate(assignments)
                if int(assignment) == index
            ],
            centroid=[float(value) for value in centroids[index].tolist()],
            snapshot_id="pending",
        )
        for index in range(cluster_count)
    ]
    snapshot_id = _snapshot_id(record_ids, normalized_vectors, provisional)
    return [cluster.model_copy(update={"snapshot_id": snapshot_id}) for cluster in provisional]


def persist_topic_run(
    repository: Any,
    project_id: str,
    clusters: Sequence[TopicCluster],
) -> Any:
    """Persist one clustering snapshot through the intelligence repository.

    The pure clustering function deliberately does not know about database
    transactions. Callers that have a project-scoped repository can use this
    helper immediately after clustering, preserving the algorithm version,
    snapshot id, record ids, and centroids as one JSONB run.
    """
    if not clusters:
        return None
    snapshot_ids = {cluster.snapshot_id for cluster in clusters}
    versions = {cluster.algorithm_version for cluster in clusters}
    if len(snapshot_ids) != 1 or len(versions) != 1:
        raise ValueError("clusters must share one snapshot and algorithm version")
    return repository.save_topic_run(
        project_id=project_id,
        snapshot_id=clusters[0].snapshot_id,
        algorithm_version=clusters[0].algorithm_version,
        clusters=[cluster.model_dump(mode="json") for cluster in clusters],
    )


def topic_trends(
    project_ids: Sequence[str],
    filters: QueryFilters,
    *,
    repository: Any | None = None,
    user_id: str | None = None,
) -> list[TopicTrend]:
    """Return owner-scoped monthly topic counts from persisted snapshots.

    ``repository`` is injectable for tests and background jobs. When omitted,
    a read-only PostgreSQL connection is opened lazily so importing this module
    never creates a database connection.
    """
    if not user_id:
        raise ValueError("user_id is required for topic trends")
    if repository is None:
        from docsgpt.storage.db.repositories.intelligence import IntelligenceRepository
        from docsgpt.storage.db.session import db_readonly

        with db_readonly() as connection:
            rows = IntelligenceRepository(connection).topic_trends(
                user_id,
                list(project_ids),
                filters,
            )
    else:
        rows = repository.topic_trends(user_id, list(project_ids), filters)
    return [row if isinstance(row, TopicTrend) else TopicTrend.model_validate(row) for row in rows]


def _record_id(record: IntelligenceRecord) -> str:
    """Return the stable key used for ordering, lookup, and persistence."""
    if record.id:
        return str(record.id)
    return f"{record.source_type.value}:{record.external_id}"


def _normalized_vectors(
    records: Sequence[IntelligenceRecord],
    vectors: Mapping[str, Sequence[float]],
) -> np.ndarray:
    """Resolve and row-normalize vectors in stable record order."""
    keyed_vectors = {str(key): value for key, value in vectors.items()}
    values: list[np.ndarray] = []
    width: int | None = None
    for record in records:
        stable_id = _record_id(record)
        vector = next(
            (
                keyed_vectors[key]
                for key in (stable_id, str(record.id or ""), str(record.external_id))
                if key and key in keyed_vectors
            ),
            None,
        )
        if vector is None:
            raise ValueError(f"missing embedding for {stable_id}")
        array = np.asarray(vector, dtype=float)
        if array.ndim != 1 or not array.size:
            raise ValueError(f"embedding for {stable_id} must be a non-empty vector")
        if not np.isfinite(array).all():
            raise ValueError(f"embedding for {stable_id} contains non-finite values")
        if width is None:
            width = int(array.size)
        elif array.size != width:
            raise ValueError("all embeddings must have the same dimension")
        norm = float(np.linalg.norm(array))
        if norm == 0:
            raise ValueError(f"embedding for {stable_id} must not be zero")
        values.append(array / norm)
    return np.vstack(values)


def _initial_centroids(vectors: np.ndarray, record_ids: Sequence[str], count: int) -> np.ndarray:
    """Select farthest-point seeds with lexicographic tie-breaking."""
    selected = [0]
    while len(selected) < count:
        centroid_vectors = vectors[selected]
        similarities = vectors @ centroid_vectors.T
        distances = 1.0 - similarities.max(axis=1)
        best_distance = max(
            distances[index] for index in range(len(record_ids)) if index not in selected
        )
        tied = [
            index
            for index in range(len(record_ids))
            if index not in selected and abs(float(distances[index]) - float(best_distance)) <= 1e-12
        ]
        best_index = min(tied, key=lambda index: record_ids[index])
        selected.append(best_index)
    return vectors[selected].copy()


def _assign(vectors: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    """Assign each normalized vector to its highest cosine centroid."""
    return np.argmax(vectors @ centroids.T, axis=1).astype(int)


def _update_centroids(
    vectors: np.ndarray,
    assignments: np.ndarray,
    previous: np.ndarray,
) -> np.ndarray:
    """Average each cluster and normalize, preserving empty seeds."""
    updated = previous.copy()
    for index in range(len(previous)):
        members = vectors[assignments == index]
        if not len(members):
            continue
        mean = members.mean(axis=0)
        norm = float(np.linalg.norm(mean))
        if norm:
            updated[index] = mean / norm
    return updated


def _cluster_label(
    records: Sequence[IntelligenceRecord],
    assignments: np.ndarray,
    cluster_index: int,
) -> str:
    """Create a compact label from the five most frequent title terms."""
    counts: Counter[str] = Counter()
    for record, assignment in zip(records, assignments):
        if int(assignment) != cluster_index:
            continue
        for token in _TOKEN_PATTERN.findall(record.title.casefold()):
            normalized = token.strip("'-_")
            if normalized and normalized not in _STOPWORDS and not normalized.isdigit():
                counts[normalized] += 1
    words = sorted(counts, key=lambda word: (-counts[word], word))[:5]
    return " / ".join(words) if words else f"主题 {cluster_index + 1}"


def _snapshot_id(
    record_ids: Sequence[str],
    vectors: np.ndarray,
    clusters: Sequence[TopicCluster],
) -> str:
    """Hash stable inputs and outputs into a reproducible snapshot id."""
    payload = {
        "algorithm_version": ALGORITHM_VERSION,
        "records": [
            {"id": record_id, "vector": [round(float(value), 12) for value in vector]}
            for record_id, vector in zip(record_ids, vectors.tolist())
        ],
        "clusters": [
            {
                "id": cluster.id,
                "record_ids": cluster.record_ids,
                "centroid": [round(value, 12) for value in cluster.centroid],
            }
            for cluster in clusters
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = [
    "ALGORITHM_VERSION",
    "TopicCluster",
    "TopicTrend",
    "cluster_issues",
    "persist_topic_run",
    "topic_trends",
]
