"""Data process task state stores."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from typing import Any

from paper_plane_x_backend.models import (
    DataProcessTask,
    DataProcessTaskStatus,
    SortOrder,
    TaskSortKey,
)
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessTaskState,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.paper.repository import PaperRepository
from paper_plane_x_backend.services.project.activity import ProjectActivityStore


class DataProcessTaskStateStore:
    """SQLite 版任务状态存储实现。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    def clear(self) -> None:
        self._db.execute("DELETE FROM data_process_tasks")
        ProjectActivityStore(self._db).mark_all_tasks_missing()

    def upsert(self, state: DataProcessTaskState) -> None:
        task = DataProcessTask(
            task_id=state.task_id,
            paper_id=state.paper_id or "",
            payload=state.payload or {},
            status=state.status,
            created_at=state.created_at,
            started_at=state.started_at,
            finished_at=state.finished_at,
            error=state.error,
            retry_of_task_id=state.retry_of_task_id,
            extraction_trace_ids=state.extraction_trace_ids or None,
            analysis_trace_ids=state.analysis_trace_ids or None,
            extraction_fact_check_trace_ids=state.extraction_fact_check_trace_ids
            or None,
            analysis_fact_check_trace_ids=state.analysis_fact_check_trace_ids or None,
        )
        db_dict = task.to_db_dict()
        self._db.execute(
            """
            INSERT INTO data_process_tasks (
                task_id, paper_id, payload, status,
                created_at, started_at, finished_at, error, retry_of_task_id,
                extraction_trace_ids, analysis_trace_ids,
                extraction_fact_check_trace_ids, analysis_fact_check_trace_ids
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                paper_id=excluded.paper_id,
                payload=excluded.payload,
                status=excluded.status,
                created_at=excluded.created_at,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                error=excluded.error,
                retry_of_task_id=excluded.retry_of_task_id,
                extraction_trace_ids=excluded.extraction_trace_ids,
                analysis_trace_ids=excluded.analysis_trace_ids,
                extraction_fact_check_trace_ids=excluded.extraction_fact_check_trace_ids,
                analysis_fact_check_trace_ids=excluded.analysis_fact_check_trace_ids
            """,
            (
                db_dict["task_id"],
                db_dict["paper_id"],
                db_dict["payload"],
                db_dict["status"],
                db_dict["created_at"],
                db_dict["started_at"],
                db_dict["finished_at"],
                db_dict["error"],
                db_dict["retry_of_task_id"],
                db_dict["extraction_trace_ids"],
                db_dict["analysis_trace_ids"],
                db_dict["extraction_fact_check_trace_ids"],
                db_dict["analysis_fact_check_trace_ids"],
            ),
        )

        if state.status in {
            DataProcessTaskStatus.CANCELED,
            DataProcessTaskStatus.FAILED,
        }:
            PaperRepository(self._db).release_interrupted_processing(state.paper_id)

        self._record_activity(state)

    def get(self, task_id: str) -> DataProcessTaskState | None:
        row = self._db.fetchone(
            "SELECT * FROM data_process_tasks WHERE task_id = ?",
            (task_id,),
        )
        if row is None:
            return None
        return self._row_to_state(row)

    def delete(self, task_id: str) -> None:
        self._db.delete("data_process_tasks", "task_id = ?", (task_id,))
        ProjectActivityStore(self._db).mark_task_missing(task_id)

    def _record_activity(self, state: DataProcessTaskState) -> None:
        """Project the task onto every project currently linked to its paper.

        The store captures the associated project ids at observation time; the
        activity table keeps previously recorded joins alive on later updates.
        """
        project_ids: list[str] = []
        if state.paper_id:
            rows = self._db.fetchall(
                "SELECT project_id FROM paper_projects WHERE paper_id = ?",
                (state.paper_id,),
            )
            project_ids = [
                str(row["project_id"])
                for row in rows
                if isinstance(row.get("project_id"), str)
            ]
        ProjectActivityStore(self._db).record_task_state(
            state,
            project_ids=project_ids,
        )

    def list(
        self,
        paper_id: str | None = None,
        keyword: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        sort_order: SortOrder = SortOrder.DESC,
        sort_by: TaskSortKey = TaskSortKey.CREATED_AT,
    ) -> list[DataProcessTaskState]:
        params: list[Any] = []
        where_clauses: list[str] = []
        if paper_id is not None:
            where_clauses.append("paper_id = ?")
            params.append(paper_id)
        keyword_clause, keyword_params = self._build_keyword_filter(keyword)
        if keyword_clause:
            where_clauses.append(keyword_clause)
            params.extend(keyword_params)

        where_clause = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        rows = self._db.fetchall(
            f"""
            SELECT * FROM data_process_tasks
            {where_clause}
            ORDER BY {sort_by.value} {sort_order.upper()}
            {limit_clause}
            """,
            tuple(params),
        )
        return [self._row_to_state(row) for row in rows]

    def count_total(
        self,
        paper_id: str | None = None,
        keyword: str | None = None,
    ) -> int:
        where_clauses: list[str] = []
        params: list[Any] = []
        if paper_id is not None:
            where_clauses.append("paper_id = ?")
            params.append(paper_id)
        keyword_clause, keyword_params = self._build_keyword_filter(keyword)
        if keyword_clause:
            where_clauses.append(keyword_clause)
            params.extend(keyword_params)
        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        row = self._db.fetchone(
            f"SELECT COUNT(*) AS count FROM data_process_tasks{where_sql}",
            tuple(params),
        )
        return int(row["count"]) if row else 0

    @staticmethod
    def _build_keyword_filter(keyword: str | None) -> tuple[str, list[str]]:
        normalized = (keyword or "").strip().lower()
        if not normalized:
            return "", []

        escaped = (
            normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        fields = ("task_id", "paper_id", "status", "retry_of_task_id")
        clauses = [
            f"LOWER(COALESCE({field}, '')) LIKE ? ESCAPE '\\'" for field in fields
        ]
        return f"({' OR '.join(clauses)})", [pattern] * len(fields)

    def count_statuses(self) -> dict[str, int]:
        counts: dict[str, int] = {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "canceled": 0,
        }
        status_map = {
            DataProcessTaskStatus.QUEUED.value: "queued",
            DataProcessTaskStatus.RUNNING.value: "running",
            DataProcessTaskStatus.CANCELING.value: "running",
            DataProcessTaskStatus.COMPLETED.value: "completed",
            DataProcessTaskStatus.FAILED.value: "failed",
            DataProcessTaskStatus.CANCELED.value: "canceled",
        }
        rows = self._db.fetchall(
            """
            SELECT status, COUNT(*) AS count
            FROM data_process_tasks
            GROUP BY status
            """
        )
        for row in rows:
            status = row.get("status")
            if not isinstance(status, str):
                continue
            key = status_map.get(status)
            if key:
                counts[key] = int(row.get("count") or 0)
        return counts

    @staticmethod
    def _row_to_state(row: dict[str, Any]) -> DataProcessTaskState:
        task = DataProcessTask.from_db_row(row)

        paper_id = task.paper_id
        if not paper_id:
            payload_paper_id = task.payload.get("paper_id") if task.payload else None
            paper_id = payload_paper_id if isinstance(payload_paper_id, str) else ""

        return DataProcessTaskState(
            task_id=task.task_id,
            paper_id=paper_id,
            payload=task.payload or {},
            status=task.status,
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            error=task.error,
            retry_of_task_id=task.retry_of_task_id,
            extraction_trace_ids=task.extraction_trace_ids or [],
            analysis_trace_ids=task.analysis_trace_ids or [],
            extraction_fact_check_trace_ids=task.extraction_fact_check_trace_ids or [],
            analysis_fact_check_trace_ids=task.analysis_fact_check_trace_ids or [],
        )


class TaskStateStoreView(MutableMapping[str, DataProcessTaskState]):
    """面向测试的状态访问视图，兼容 task_states 字典访问。"""

    def __init__(self, store: DataProcessTaskStateStore) -> None:
        self._store = store

    def __getitem__(self, key: str) -> DataProcessTaskState:
        value = self._store.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: DataProcessTaskState) -> None:
        if key != value.task_id:
            raise KeyError("task_id key mismatch")
        self._store.upsert(value)

    def __delitem__(self, key: str) -> None:
        raise NotImplementedError("delete is not supported")

    def __iter__(self) -> Iterator[str]:
        for state in self._store.list():
            yield state.task_id

    def __len__(self) -> int:
        return self._store.count_total()
