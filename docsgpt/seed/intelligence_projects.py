"""Idempotent Stage A OpenScout project definitions and seed helper."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

STAGE_A_WINDOW_START = date(2025, 9, 14)
STAGE_A_WINDOW_END = date(2026, 9, 14)


@dataclass(frozen=True)
class StageAProject:
    """One fixed Stage A repository and its initial collection window."""

    repository: str
    window_start: date = STAGE_A_WINDOW_START
    window_end: date = STAGE_A_WINDOW_END


def stage_a_projects() -> list[StageAProject]:
    """Return the exact three repositories included in Stage A."""
    return [
        StageAProject("langgenius/dify"),
        StageAProject("infiniflow/ragflow"),
        StageAProject("labring/FastGPT"),
    ]


def seed_stage_a_projects(repository: Any, user_id: str) -> list[dict[str, Any]]:
    """Create missing Stage A projects without duplicating existing rows.

    Args:
        repository: An ``IntelligenceRepository`` or compatible test double.
        user_id: Owner that should receive the fixed project set.

    Returns:
        The existing or newly created project rows in Stage A order.
    """
    if not user_id:
        raise ValueError("user_id is required")

    rows: list[dict[str, Any]] = []
    for project in stage_a_projects():
        existing = repository.find_project(user_id, project.repository)
        if existing is None:
            existing = repository.create_project(
                user_id=user_id,
                repository=project.repository,
                window_start=project.window_start,
                window_end=project.window_end,
            )
        rows.append(existing)
    return rows


__all__ = [
    "STAGE_A_WINDOW_END",
    "STAGE_A_WINDOW_START",
    "StageAProject",
    "seed_stage_a_projects",
    "stage_a_projects",
]
