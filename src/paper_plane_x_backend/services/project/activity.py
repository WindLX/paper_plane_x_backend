"""Project activity store.

Activity records are the durable workbench event log for a project. They are
independent from the legacy ``projects.operation_logs`` JSON column, which stays
in place for backwards compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.project.activity_schema import (
    PROJECT_ACTIVITIES_TABLE,
)
from paper_plane_x_backend.utils.logging import log_verbose

if TYPE_CHECKING:
    from paper_plane_x_backend.services.data_process_tasks.models import (
        DataProcessTaskState,
    )

logger = logging.getLogger(__name__)

type ActivityCategory = Literal["project", "paper", "file", "task", "agent", "export"]
type ActivityStatus = Literal[
    "info", "queued", "running", "completed", "failed", "canceled"
]


class _Unset:
    """Sentinel marking an omitted keyword argument in partial updates."""

    __slots__ = ()


_UNSET = _Unset()


_TASK_STATUS_MAP: dict[str, ActivityStatus] = {
    "QUEUED": "queued",
    "RUNNING": "running",
    "CANCELING": "running",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "CANCELED": "canceled",
}

_TASK_EVENT_MAP: dict[str, str] = {
    "QUEUED": "task_queued",
    "RUNNING": "task_started",
    "CANCELING": "task_canceling",
    "COMPLETED": "task_completed",
    "FAILED": "task_failed",
    "CANCELED": "task_canceled",
}

_OPERATION_ACTIVITY_MAP: dict[str, tuple[ActivityCategory, str]] = {
    "link_paper": ("paper", "paper_linked"),
    "unlink_paper": ("paper", "paper_unlinked"),
    "update_project": ("project", "project_updated"),
    "create_project": ("project", "project_created"),
}


def map_operation_to_activity(
    operation: str,
) -> tuple[ActivityCategory, str] | None:
    """Map a legacy operation-log code to an activity category/event type.

    Unrecognized operations return ``None`` so the migration and the live emitter
    behave identically and never fabricate activity history.
    """
    return _OPERATION_ACTIVITY_MAP.get(operation)


def build_operation_log_activity_id(
    project_id: str,
    index: int,
    operation: str,
    timestamp: str,
) -> str:
    """Deterministic id for a migrated operation-log entry.

    The same seed is used by the live emitter in ``ProjectRepository`` and by the
    one-shot migration, so an entry can never be recorded twice.
    """
    seed = f"ppx:project-activity:{project_id}:{index}:{operation}:{timestamp}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def build_task_activity_id(project_id: str, task_id: str) -> str:
    """Deterministic id enforcing one activity row per project/task pair."""
    seed = f"ppx:project-task-activity:{project_id}:{task_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


@dataclass(slots=True)
class ActivityRecord:
    """In-memory representation of one project activity row."""

    activity_id: str
    project_id: str
    category: ActivityCategory
    event_type: str
    status: ActivityStatus
    object_name: str | None
    paper_id: str | None
    file_path: str | None
    task_id: str | None
    trace_ids: list[str] = field(default_factory=lambda: cast(list[str], []))
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    retry_of_task_id: str | None = None
    task_exists: bool = False
    detail: dict[str, Any] = field(default_factory=lambda: cast(dict[str, Any], {}))

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ActivityRecord":
        """Build a record from a raw SQLite row."""
        category = row.get("category")
        status = row.get("status")
        return cls(
            activity_id=str(row.get("activity_id") or ""),
            project_id=str(row.get("project_id") or ""),
            category=cast(
                ActivityCategory, category if isinstance(category, str) else "project"
            ),
            event_type=str(row.get("event_type") or ""),
            status=cast(ActivityStatus, status if isinstance(status, str) else "info"),
            object_name=_optional_str(row.get("object_name")),
            paper_id=_optional_str(row.get("paper_id")),
            file_path=_optional_str(row.get("file_path")),
            task_id=_optional_str(row.get("task_id")),
            trace_ids=_parse_str_list(row.get("trace_ids")),
            created_at=_as_datetime(row.get("created_at")),
            updated_at=_as_datetime(row.get("updated_at")),
            started_at=_as_datetime(row.get("started_at")),
            finished_at=_as_datetime(row.get("finished_at")),
            error=_optional_str(row.get("error")),
            retry_of_task_id=_optional_str(row.get("retry_of_task_id")),
            task_exists=bool(row.get("task_exists")),
            detail=_parse_dict(row.get("detail")),
        )

    def to_payload(self) -> dict[str, Any]:
        """Serialize to the shared API contract shape."""
        return {
            "activity_id": self.activity_id,
            "project_id": self.project_id,
            "category": self.category,
            "event_type": self.event_type,
            "status": self.status,
            "object_name": self.object_name,
            "paper_id": self.paper_id,
            "file_path": self.file_path,
            "task_id": self.task_id,
            "trace_ids": list(self.trace_ids),
            "created_at": _format_datetime(self.created_at),
            "updated_at": _format_datetime(self.updated_at),
            "started_at": _format_datetime(self.started_at),
            "finished_at": _format_datetime(self.finished_at),
            "error": self.error,
            "retry_of_task_id": self.retry_of_task_id,
            "task_exists": self.task_exists,
            "detail": dict(self.detail),
        }


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in cast(dict[Any, Any], value).items()}
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {str(k): v for k, v in cast(dict[Any, Any], parsed).items()}
    return {}


def _parse_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in cast(list[Any], value) if isinstance(item, str)]
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [item for item in cast(list[Any], parsed) if isinstance(item, str)]
    return []


def parse_operation_logs(value: object) -> list[dict[str, Any]]:
    """Parse the ``projects.operation_logs`` column into dict entries."""
    if isinstance(value, list):
        items = cast(list[Any], value)
    elif isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        items = cast(list[Any], parsed)
    else:
        return []
    return [
        {str(k): v for k, v in cast(dict[Any, Any], item).items()}
        for item in items
        if isinstance(item, dict)
    ]


class ProjectActivityStore:
    """Durable project activity repository."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------
    def record(
        self,
        *,
        project_id: str,
        category: ActivityCategory,
        event_type: str,
        status: ActivityStatus = "info",
        object_name: str | None = None,
        paper_id: str | None = None,
        file_path: str | None = None,
        task_id: str | None = None,
        trace_ids: Sequence[str] | None = None,
        detail: dict[str, Any] | None = None,
        activity_id: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error: str | None = None,
        retry_of_task_id: str | None = None,
        task_exists: bool = False,
    ) -> str:
        """Insert one activity row and return its id.

        Explicit ``activity_id`` values use ``INSERT OR IGNORE`` so deterministic
        ids make migration and live emission idempotent.
        """
        if not project_id:
            raise ValueError("project_id is required to record a project activity")
        now = datetime.now()
        resolved_id = activity_id or str(uuid.uuid4())
        created = created_at or now
        self._db.execute(
            """
            INSERT OR IGNORE INTO project_activities (
                activity_id, project_id, category, event_type, status,
                object_name, paper_id, file_path, task_id, trace_ids,
                created_at, updated_at, started_at, finished_at, error,
                retry_of_task_id, task_exists, detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_id,
                project_id,
                category,
                event_type,
                status,
                object_name,
                paper_id,
                file_path,
                task_id,
                json.dumps(list(trace_ids or []), ensure_ascii=False),
                created,
                updated_at or created,
                started_at,
                finished_at,
                error,
                retry_of_task_id,
                1 if task_exists else 0,
                json.dumps(dict(detail or {}), ensure_ascii=False),
            ),
        )
        log_verbose(
            logger,
            "event=project_activity.recorded project_id=%s activity_id=%s event_type=%s",
            project_id,
            resolved_id,
            event_type,
        )
        return resolved_id

    def record_pending(
        self,
        *,
        project_id: str,
        category: ActivityCategory,
        event_type: str,
        object_name: str | None = None,
        paper_id: str | None = None,
        file_path: str | None = None,
        task_id: str | None = None,
        trace_ids: Sequence[str] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> str:
        """Record a running activity that a caller later completes or fails."""
        now = datetime.now()
        return self.record(
            project_id=project_id,
            category=category,
            event_type=event_type,
            status="running",
            object_name=object_name,
            paper_id=paper_id,
            file_path=file_path,
            task_id=task_id,
            trace_ids=trace_ids,
            detail=detail,
            created_at=now,
            updated_at=now,
            started_at=now,
        )

    def update(
        self,
        activity_id: str,
        *,
        status: ActivityStatus | _Unset = _UNSET,
        object_name: str | None | _Unset = _UNSET,
        trace_ids: Sequence[str] | _Unset = _UNSET,
        detail: dict[str, Any] | _Unset = _UNSET,
        error: str | None | _Unset = _UNSET,
        started_at: datetime | None | _Unset = _UNSET,
        finished_at: datetime | None | _Unset = _UNSET,
        retry_of_task_id: str | None | _Unset = _UNSET,
        task_exists: bool | _Unset = _UNSET,
    ) -> None:
        """Partially update an existing activity row."""
        data: dict[str, Any] = {"updated_at": datetime.now()}
        if not isinstance(status, _Unset):
            data["status"] = status
        if not isinstance(object_name, _Unset):
            data["object_name"] = object_name
        if not isinstance(trace_ids, _Unset):
            data["trace_ids"] = json.dumps(list(trace_ids), ensure_ascii=False)
        if not isinstance(detail, _Unset):
            data["detail"] = json.dumps(dict(detail), ensure_ascii=False)
        if not isinstance(error, _Unset):
            data["error"] = error
        if not isinstance(started_at, _Unset):
            data["started_at"] = started_at
        if not isinstance(finished_at, _Unset):
            data["finished_at"] = finished_at
        if not isinstance(retry_of_task_id, _Unset):
            data["retry_of_task_id"] = retry_of_task_id
        if not isinstance(task_exists, _Unset):
            data["task_exists"] = 1 if task_exists else 0
        self._db.update(
            PROJECT_ACTIVITIES_TABLE,
            data,
            "activity_id = ?",
            (activity_id,),
        )

    def complete(
        self,
        activity_id: str,
        *,
        detail: dict[str, Any] | None = None,
        trace_ids: Sequence[str] | None = None,
        object_name: str | None | _Unset = _UNSET,
    ) -> None:
        """Mark an activity as completed."""
        self.update(
            activity_id,
            status="completed",
            finished_at=datetime.now(),
            error=None,
            object_name=object_name,
            trace_ids=trace_ids if trace_ids is not None else _UNSET,
            detail=detail if detail is not None else _UNSET,
        )

    def fail(
        self,
        activity_id: str,
        *,
        error: str | None = None,
        detail: dict[str, Any] | None = None,
        trace_ids: Sequence[str] | None = None,
        status: Literal["failed", "canceled"] = "failed",
    ) -> None:
        """Mark an activity as failed or canceled."""
        self.update(
            activity_id,
            status=status,
            finished_at=datetime.now(),
            error=error,
            trace_ids=trace_ids if trace_ids is not None else _UNSET,
            detail=detail if detail is not None else _UNSET,
        )

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def list(
        self,
        project_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        category: ActivityCategory | None = None,
        status: ActivityStatus | None = None,
        created_at_from: datetime | None = None,
        created_at_to: datetime | None = None,
        keyword: str | None = None,
    ) -> tuple[list[ActivityRecord], int]:
        """Return newest-first activities plus the filtered total."""
        where_clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if category is not None:
            where_clauses.append("category = ?")
            params.append(category)
        if status is not None:
            where_clauses.append("status = ?")
            params.append(status)
        if created_at_from is not None:
            where_clauses.append("created_at >= ?")
            params.append(created_at_from)
        if created_at_to is not None:
            where_clauses.append("created_at <= ?")
            params.append(created_at_to)
        keyword_clause, keyword_params = _build_keyword_filter(keyword)
        if keyword_clause:
            where_clauses.append(keyword_clause)
            params.extend(keyword_params)

        where_sql = " AND ".join(where_clauses)
        total_row = self._db.fetchone(
            f"SELECT COUNT(*) AS count FROM project_activities WHERE {where_sql}",
            tuple(params),
        )
        total = int(total_row["count"]) if total_row else 0
        rows = self._db.fetchall(
            f"""
            SELECT * FROM project_activities
            WHERE {where_sql}
            ORDER BY created_at DESC, activity_id DESC
            LIMIT ? OFFSET ?
            """,
            tuple([*params, limit, offset]),
        )
        return [ActivityRecord.from_row(row) for row in rows], total

    # ------------------------------------------------------------------
    # legacy operation-log migration
    # ------------------------------------------------------------------
    def migrate_operation_logs(self, project_id: str) -> int:
        """Backfill recognizable operation-log entries with deterministic ids.

        Idempotent: re-running skips rows already present because the ids are
        derived from the project, entry index, operation, and timestamp.
        """
        row = self._db.fetchone(
            "SELECT operation_logs FROM projects WHERE project_id = ?",
            (project_id,),
        )
        if row is None:
            return 0

        entries = parse_operation_logs(row.get("operation_logs"))
        migrated = 0
        for index, entry in enumerate(entries):
            operation = entry.get("operation")
            if not isinstance(operation, str):
                continue
            mapping = map_operation_to_activity(operation)
            if mapping is None:
                continue
            category, event_type = mapping
            raw_timestamp = entry.get("timestamp")
            timestamp = _as_datetime(raw_timestamp)
            if timestamp is None:
                # Never invent a timestamp for legacy history.
                logger.warning(
                    "event=project_activity.migration_skipped project_id=%s index=%s reason=invalid_timestamp",
                    project_id,
                    index,
                )
                continue
            activity_id = build_operation_log_activity_id(
                project_id,
                index,
                operation,
                raw_timestamp if isinstance(raw_timestamp, str) else "",
            )
            existing = self._db.fetchone(
                "SELECT 1 FROM project_activities WHERE activity_id = ?",
                (activity_id,),
            )
            if existing is not None:
                continue
            legacy_detail = entry.get("detail")
            detail_payload = (
                {str(k): v for k, v in cast(dict[Any, Any], legacy_detail).items()}
                if isinstance(legacy_detail, dict)
                else {}
            )
            paper_id = detail_payload.get("paper_id")
            self.record(
                activity_id=activity_id,
                project_id=project_id,
                category=category,
                event_type=event_type,
                status="info",
                paper_id=paper_id if isinstance(paper_id, str) else None,
                created_at=timestamp,
                updated_at=timestamp,
                detail={
                    "operation": operation,
                    "detail": detail_payload,
                    "migrated_from": "operation_logs",
                },
            )
            migrated += 1
        if migrated:
            logger.info(
                "event=project_activity.operation_logs_migrated project_id=%s count=%s",
                project_id,
                migrated,
            )
        return migrated

    # ------------------------------------------------------------------
    # task projection
    # ------------------------------------------------------------------
    def record_task_state(
        self,
        state: "DataProcessTaskState",
        *,
        project_ids: Sequence[str],
    ) -> None:
        """Project one task state onto every associated project.

        New associations create a row; previously recorded associations keep
        their row and are updated even after the paper is unlinked. Retries have a
        different ``task_id`` and therefore produce a new row linked through
        ``retry_of_task_id``.
        """
        now = datetime.now()
        status_key = state.status.value
        activity_status = _TASK_STATUS_MAP[status_key]
        event_type = _TASK_EVENT_MAP[status_key]
        trace_ids = _collect_trace_ids(state)
        detail = {
            "paper_id": state.paper_id or None,
            "task_status": status_key,
        }
        created_at = state.created_at or now
        trace_ids_json = json.dumps(trace_ids, ensure_ascii=False)
        detail_json = json.dumps(detail, ensure_ascii=False)
        # Matches the SET clause order below.
        shared_params = (
            event_type,
            activity_status,
            now,
            state.started_at,
            state.finished_at,
            state.error,
            state.retry_of_task_id,
            trace_ids_json,
            1,
            detail_json,
            state.paper_id or None,
        )

        unique_projects = [pid for pid in dict.fromkeys(project_ids) if pid]
        # A cancellation/upsert can race a project deletion; never write to a
        # project that no longer exists.
        if unique_projects:
            unique_projects = self._existing_project_ids(unique_projects)
        for project_id in unique_projects:
            self._db.execute(
                """
                INSERT OR IGNORE INTO project_activities (
                    activity_id, project_id, category, event_type, status,
                    object_name, paper_id, file_path, task_id, trace_ids,
                    created_at, updated_at, started_at, finished_at, error,
                    retry_of_task_id, task_exists, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    build_task_activity_id(project_id, state.task_id),
                    project_id,
                    "task",
                    event_type,
                    activity_status,
                    None,
                    state.paper_id or None,
                    None,
                    state.task_id,
                    json.dumps(trace_ids, ensure_ascii=False),
                    created_at,
                    now,
                    state.started_at,
                    state.finished_at,
                    state.error,
                    state.retry_of_task_id,
                    1,
                    json.dumps(detail, ensure_ascii=False),
                ),
            )
            self._db.execute(
                """
                UPDATE project_activities SET
                    event_type = ?, status = ?, updated_at = ?, started_at = ?,
                    finished_at = ?, error = ?, retry_of_task_id = ?,
                    trace_ids = ?, task_exists = ?, detail = ?, paper_id = ?
                WHERE project_id = ? AND task_id = ?
                """,
                (*shared_params, project_id, state.task_id),
            )

        # Keep recorded joins alive: update rows for projects the paper is no
        # longer associated with without creating new ones.
        base_params = shared_params
        if unique_projects:
            placeholders = ", ".join("?" for _ in unique_projects)
            self._db.execute(
                f"""
                UPDATE project_activities SET
                    event_type = ?, status = ?, updated_at = ?, started_at = ?,
                    finished_at = ?, error = ?, retry_of_task_id = ?,
                    trace_ids = ?, task_exists = ?, detail = ?, paper_id = ?
                WHERE task_id = ? AND project_id NOT IN ({placeholders})
                    AND project_id IN (SELECT project_id FROM projects)
                """,
                (*base_params, state.task_id, *unique_projects),
            )
        else:
            self._db.execute(
                """
                UPDATE project_activities SET
                    event_type = ?, status = ?, updated_at = ?, started_at = ?,
                    finished_at = ?, error = ?, retry_of_task_id = ?,
                    trace_ids = ?, task_exists = ?, detail = ?, paper_id = ?
                WHERE task_id = ?
                    AND project_id IN (SELECT project_id FROM projects)
                """,
                (*base_params, state.task_id),
            )

    def _existing_project_ids(self, project_ids: Sequence[str]) -> list[str]:
        """Drop captured project ids that no longer exist."""
        placeholders = ", ".join("?" for _ in project_ids)
        rows = self._db.fetchall(
            f"SELECT project_id FROM projects WHERE project_id IN ({placeholders})",
            tuple(project_ids),
        )
        existing = {
            str(row["project_id"])
            for row in rows
            if isinstance(row.get("project_id"), str)
        }
        return [project_id for project_id in project_ids if project_id in existing]

    def mark_task_missing(self, task_id: str) -> None:
        """Mark every activity referencing a deleted task as ``task_exists`` false."""
        self._db.execute(
            """
            UPDATE project_activities
            SET task_exists = 0, updated_at = ?
            WHERE task_id = ?
            """,
            (datetime.now(), task_id),
        )

    def mark_all_tasks_missing(self) -> None:
        """Mark all task activities as missing after a tasks-table wipe."""
        self._db.execute(
            """
            UPDATE project_activities
            SET task_exists = 0, updated_at = ?
            WHERE task_id IS NOT NULL
            """,
            (datetime.now(),),
        )


def migrate_legacy_operation_logs(db: Database) -> int:
    """Run the one-shot legacy operation-log migration.

    Called explicitly from ``Database.init_tables`` after the activity schema is
    created; it is idempotent because activity ids are deterministic.
    """
    store = ProjectActivityStore(db)
    rows = db.fetchall("SELECT project_id FROM projects")
    migrated = 0
    for row in rows:
        project_id = row.get("project_id")
        if isinstance(project_id, str) and project_id:
            migrated += store.migrate_operation_logs(project_id)
    if migrated:
        logger.info(
            "event=project_activity.operation_logs_migrated_total count=%s",
            migrated,
        )
    return migrated


def _build_keyword_filter(keyword: str | None) -> tuple[str, list[str]]:
    normalized = (keyword or "").strip().lower()
    if not normalized:
        return "", []
    escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    fields = (
        "category",
        "event_type",
        "status",
        "object_name",
        "paper_id",
        "file_path",
        "task_id",
        "error",
        "detail",
    )
    clauses = [f"LOWER(COALESCE({field}, '')) LIKE ? ESCAPE '\\'" for field in fields]
    return f"({' OR '.join(clauses)})", [pattern] * len(fields)


def _collect_trace_ids(state: "DataProcessTaskState") -> list[str]:
    collected: list[str] = []
    for group in (
        state.extraction_trace_ids,
        state.analysis_trace_ids,
        state.extraction_fact_check_trace_ids,
        state.analysis_fact_check_trace_ids,
    ):
        for trace_id in group or []:
            if trace_id and trace_id not in collected:
                collected.append(trace_id)
    return collected


@asynccontextmanager
async def pending_activity(
    store: ProjectActivityStore,
    *,
    project_id: str,
    category: ActivityCategory,
    event_type: str,
    object_name: str | None = None,
    paper_id: str | None = None,
    file_path: str | None = None,
    task_id: str | None = None,
    trace_ids: Sequence[str] | None = None,
    detail: dict[str, Any] | None = None,
) -> AsyncGenerator[str, None]:
    """Record a pending activity and settle it on exit.

    On success the activity is completed; on cancellation it is canceled; on any
    other failure it is failed and the original exception is re-raised.
    """
    activity_id = store.record_pending(
        project_id=project_id,
        category=category,
        event_type=event_type,
        object_name=object_name,
        paper_id=paper_id,
        file_path=file_path,
        task_id=task_id,
        trace_ids=trace_ids,
        detail=detail,
    )
    try:
        yield activity_id
    except asyncio.CancelledError:
        store.fail(activity_id, status="canceled", error="canceled")
        raise
    except Exception as exc:  # noqa: BLE001 - activity boundary re-raises
        store.fail(activity_id, error=str(exc))
        raise
    else:
        store.complete(activity_id)


__all__ = [
    "ActivityCategory",
    "ActivityRecord",
    "ActivityStatus",
    "ProjectActivityStore",
    "build_operation_log_activity_id",
    "build_task_activity_id",
    "map_operation_to_activity",
    "migrate_legacy_operation_logs",
    "parse_operation_logs",
    "pending_activity",
]
