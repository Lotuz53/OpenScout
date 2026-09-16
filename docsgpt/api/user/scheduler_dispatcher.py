"""Schedule dispatcher: poll Postgres, claim due rows under FOR UPDATE SKIP LOCKED,
advance next_run_at atomically with the run claim, then enqueue.

Per-schedule IANA tz semantics (croniter+zoneinfo) outside Celery's app-wide tz,
plus Postgres-native dedup avoid Redis visibility_timeout double-fires.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from docsgpt.agents.scheduler_utils import next_cron_run
from docsgpt.core.settings import settings
from docsgpt.storage.db.engine import get_engine
from docsgpt.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from docsgpt.storage.db.repositories.schedules import SchedulesRepository

logger = logging.getLogger(__name__)


def _sync_task():
    """Resolve the OpenScout synchronization task without importing it eagerly."""
    from docsgpt.intelligence.tasks import sync_intelligence_project

    return sync_intelligence_project


def _normalize_dt(value: Any) -> Optional[datetime]:
    """Accept a datetime / ISO string / None and return a tz-aware UTC dt."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else (
            value.replace(tzinfo=timezone.utc)
        )
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else (
            parsed.replace(tzinfo=timezone.utc)
        )
    return None


def _compute_next(
    schedule: Dict[str, Any],
    *,
    after: datetime,
) -> Optional[datetime]:
    """Next next_run_at for a recurring schedule, or None when past end_at."""
    cron = schedule.get("cron")
    if not cron:
        return None
    end_at = _normalize_dt(schedule.get("end_at"))
    candidate = next_cron_run(cron, schedule.get("timezone"), after=after)
    if end_at is not None and candidate > end_at:
        return None
    return candidate


class IntelligenceSyncDispatcher:
    """Dispatch owner-scoped OpenScout syncs for a stable schedule slot."""

    def __init__(self, sync_task: Any | None = None, user_id: str | None = None) -> None:
        """Initialize a dispatcher.

        Args:
            sync_task: Celery task-like object. When omitted, the production
                task is resolved lazily to avoid an import cycle.
            user_id: Default owner used by :meth:`dispatch`.
        """
        self._sync_task = sync_task
        self._user_id = user_id

    def dispatch(
        self,
        project_id: str,
        *,
        scheduled_at: datetime,
        user_id: str | None = None,
    ) -> Any:
        """Queue one project sync with a project-and-slot idempotency key.

        Args:
            project_id: UUID of the project to synchronize.
            scheduled_at: The logical schedule slot, normalized to UTC.
            user_id: Optional owner override for this dispatch.

        Returns:
            The result returned by Celery's ``apply_async``.

        Raises:
            ValueError: If the schedule slot or owner is missing/invalid.
        """
        normalized_at = _normalize_dt(scheduled_at)
        if normalized_at is None:
            raise ValueError("scheduled_at must be a valid datetime")
        target_user = user_id or self._user_id
        if not target_user:
            raise ValueError("user_id is required for an intelligence sync")

        task = self._sync_task or _sync_task()
        idempotency_key = f"openscout-sync:{project_id}:{normalized_at.isoformat()}"
        return task.apply_async(
            kwargs={
                "project_id": str(project_id),
                "user_id": str(target_user),
                "idempotency_key": idempotency_key,
            },
            queue="docsgpt",
        )


# Keep the domain name discoverable for callers that describe the operation as
# an OpenScout sync rather than an intelligence sync.
OpenScoutSyncDispatcher = IntelligenceSyncDispatcher


def _daily_slot(value: datetime | str | None) -> datetime:
    """Return a UTC logical slot, stable for every dispatch on one day."""
    normalized = _normalize_dt(value) if value is not None else None
    if value is not None and normalized is None:
        raise ValueError("scheduled_at must be a valid datetime")
    now = normalized or datetime.now(timezone.utc)
    if value is not None:
        return now
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def dispatch_daily_intelligence_syncs(
    *,
    scheduled_at: datetime | str | None = None,
) -> Dict[str, int]:
    """Dispatch one daily sync for every persisted OpenScout project.

    RedBeat invokes the caller once per day. The logical UTC day is included
    in every project's idempotency key, so a repeated beat tick cannot execute
    the same project slot twice.
    """
    if not settings.POSTGRES_URI:
        return {"dispatched": 0, "skipped": 0}

    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as conn:
        result = conn.execute(
            text(
                """
                SELECT id::text AS project_id, user_id
                FROM intelligence_projects
                ORDER BY created_at ASC, id ASC
                """
            )
        )
        projects = result.mappings().all()

    slot = _daily_slot(scheduled_at)
    dispatcher = IntelligenceSyncDispatcher()
    counts = {"dispatched": 0, "skipped": 0}
    for project in projects:
        try:
            dispatcher.dispatch(
                str(project["project_id"]),
                user_id=str(project["user_id"]),
                scheduled_at=slot,
            )
        except Exception:  # noqa: BLE001 - one project must not block the daily sweep
            logger.exception(
                "Could not dispatch daily intelligence sync for project %s",
                project.get("project_id"),
            )
            counts["skipped"] += 1
        else:
            counts["dispatched"] += 1
    return counts


def dispatch_due_runs() -> Dict[str, int]:
    """One dispatcher tick; returns counts for schedule_syncs-style logging."""
    if not settings.POSTGRES_URI:
        return {"enqueued": 0, "skipped": 0, "advanced": 0}

    from docsgpt.api.user.tasks import execute_scheduled_run

    now = datetime.now(timezone.utc)
    grace = timedelta(seconds=max(0, settings.SCHEDULE_MISFIRE_GRACE))
    engine = get_engine()
    counts = {"enqueued": 0, "skipped": 0, "advanced": 0}
    enqueue_args: List[str] = []

    with engine.begin() as conn:
        schedules_repo = SchedulesRepository(conn)
        runs_repo = ScheduleRunsRepository(conn)
        for schedule in schedules_repo.list_due():
            scheduled_for = _normalize_dt(schedule.get("next_run_at"))
            if scheduled_for is None:
                continue

            trigger_type = schedule.get("trigger_type")
            agent_id_raw = schedule.get("agent_id")
            agent_id = str(agent_id_raw) if agent_id_raw else None

            # Misfire grace applies to recurring only — once-tasks fire late, not vanish.
            if (
                trigger_type == "recurring"
                and grace > timedelta(0)
                and (now - scheduled_for) > grace
            ):
                runs_repo.record_skipped(
                    str(schedule["id"]),
                    schedule["user_id"],
                    agent_id,
                    scheduled_for,
                    error_type="missed",
                    error="misfire grace exceeded",
                )
                counts["skipped"] += 1
                nxt = _compute_next(schedule, after=now)
                if nxt is None:
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"status": "completed", "next_run_at": None,
                         "last_run_at": now},
                    )
                else:
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"next_run_at": nxt, "last_run_at": now},
                    )
                counts["advanced"] += 1
                continue

            # Overlap guard: never enqueue while a previous run is active.
            if runs_repo.has_active_run(str(schedule["id"])):
                runs_repo.record_skipped(
                    str(schedule["id"]),
                    schedule["user_id"],
                    agent_id,
                    scheduled_for,
                    error_type="overlap",
                    error="previous run still active",
                )
                counts["skipped"] += 1
                if trigger_type == "recurring":
                    nxt = _compute_next(schedule, after=scheduled_for)
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"next_run_at": nxt, "last_run_at": now},
                    )
                else:
                    # Once: null next_run_at so we don't re-pick; the in-flight
                    # run will terminal-flip the schedule when it finishes.
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"next_run_at": None, "last_run_at": now},
                    )
                continue

            # Dedup primitive: two racing dispatchers see exactly one row.
            run = runs_repo.record_pending(
                str(schedule["id"]),
                schedule["user_id"],
                agent_id,
                scheduled_for,
                trigger_source="cron",
            )
            if run is None:
                counts["skipped"] += 1
            else:
                enqueue_args.append(str(run["id"]))
                counts["enqueued"] += 1

            # Advance: recurring picks next tick, once nulls next_run_at
            # (worker terminal-flips status on completion).
            if trigger_type == "recurring":
                nxt = _compute_next(schedule, after=scheduled_for)
                if nxt is None:
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"status": "completed", "next_run_at": None,
                         "last_run_at": now},
                    )
                else:
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"next_run_at": nxt, "last_run_at": now},
                    )
            else:
                schedules_repo.update_internal(
                    str(schedule["id"]),
                    {"next_run_at": None, "last_run_at": now},
                )
            counts["advanced"] += 1

    # Enqueue after commit so the worker sees the schedule_runs row on pick-up.
    for run_id in enqueue_args:
        try:
            execute_scheduled_run.apply_async(args=[run_id], queue="docsgpt")
        except Exception:
            logger.exception(
                "dispatcher: failed to enqueue execute_scheduled_run for %s",
                run_id,
            )
    return counts
