"""Project 数据仓库.

封装所有 projects 表的数据库访问，不包含任何业务编排或外部服务调用逻辑。
"""

import json
import logging
from datetime import datetime
from typing import Any, cast

from paper_plane_x_backend.models import Project, ProjectSortKey, SortOrder
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.project.activity import (
    ProjectActivityStore,
    build_operation_log_activity_id,
    map_operation_to_activity,
)

logger = logging.getLogger(__name__)


class ProjectRepositoryError(Exception):
    """ProjectRepository 异常."""

    def __init__(
        self,
        message: str,
        project_id: str | None = None,
        error_code: str = "bad_request",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.project_id = project_id
        self.error_code = error_code


class ProjectRepository:
    """Project 数据访问层."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, project_id: str) -> Project | None:
        """获取项目详情."""
        row = self.db.fetchone(
            "SELECT * FROM projects WHERE project_id = ?",
            (project_id,),
        )
        if not row:
            logger.debug("event=project.get_not_found project_id=%s", project_id)
            return None
        return Project.from_db_row(row)

    def ensure_exists(self, project_id: str) -> None:
        """确保项目存在，不存在则抛出异常."""
        row = self.db.fetchone(
            "SELECT 1 FROM projects WHERE project_id = ?",
            (project_id,),
        )
        if row is None:
            raise ProjectRepositoryError(
                f"Project {project_id} not found",
                project_id=project_id,
                error_code="not_found",
            )

    def get_agent_summary(self, project_id: str) -> str | None:
        """获取项目的 agent_summary."""
        self.ensure_exists(project_id)
        row = self.db.fetchone(
            "SELECT agent_summary FROM projects WHERE project_id = ?",
            (project_id,),
        )
        if row is None:
            return None
        return row.get("agent_summary")

    def set_agent_summary(self, project_id: str, content: str) -> None:
        """设置项目的 agent_summary."""
        self.ensure_exists(project_id)
        from datetime import datetime

        self.db.update(
            "projects",
            {"agent_summary": content, "updated_at": datetime.now()},
            "project_id = ?",
            (project_id,),
        )
        logger.info(
            "event=project.agent_summary_updated project_id=%s",
            project_id,
        )
        ProjectActivityStore(self.db).record(
            project_id=project_id,
            category="project",
            event_type="summary_updated" if content else "summary_cleared",
            status="completed",
            detail={},
        )

    def delete_agent_summary(self, project_id: str) -> None:
        """删除项目的 agent_summary（置为 NULL）."""
        self.set_agent_summary(project_id, "")

    def exists(self, project_id: str) -> bool:
        """检查项目是否存在."""
        row = self.db.fetchone(
            "SELECT 1 FROM projects WHERE project_id = ?",
            (project_id,),
        )
        return row is not None

    def create(self, project: Project) -> None:
        """插入项目."""
        self.db.insert("projects", project.to_db_dict())
        ProjectActivityStore(self.db).record(
            project_id=project.project_id,
            category="project",
            event_type="project_created",
            status="completed",
            object_name=project.name,
            created_at=project.created_at,
        )
        logger.info(
            "event=project.record_created project_id=%s name=%s",
            project.project_id,
            project.name,
        )

    def list_all(
        self,
        offset: int = 0,
        limit: int = 20,
        sort_by: ProjectSortKey = ProjectSortKey.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> list[Project]:
        """列出所有项目."""
        rows = self.db.fetchall(
            f"""
            SELECT * FROM projects
            ORDER BY {sort_by.value} {sort_order.upper()}
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [Project.from_db_row(row) for row in rows]

    def count_all(self) -> int:
        """项目总数."""
        count_result = self.db.fetchone("SELECT COUNT(*) as count FROM projects")
        return int(count_result["count"]) if count_result else 0

    def update(self, project_id: str, data: dict[str, object]) -> None:
        """通用更新接口."""
        self.db.update(
            "projects",
            data,
            "project_id = ?",
            (project_id,),
        )
        logger.debug(
            "event=project.updated project_id=%s keys=%s",
            project_id,
            sorted(data.keys()),
        )

    def delete(self, project_id: str) -> None:
        """删除项目（含清理 paper_projects 关联）."""
        self.ensure_exists(project_id)
        detached_count = self.db.delete(
            "paper_projects",
            "project_id = ?",
            (project_id,),
        )
        self.db.delete("projects", "project_id = ?", (project_id,))
        logger.info(
            "event=project.deleted project_id=%s detached_papers=%s",
            project_id,
            detached_count,
        )

    def get_operation_logs(self, project_id: str) -> list[dict[str, Any]]:
        """加载项目操作日志."""
        self.ensure_exists(project_id)
        row = self.db.fetchone(
            "SELECT operation_logs FROM projects WHERE project_id = ?",
            (project_id,),
        )
        if row is None:
            return []

        raw = row.get("operation_logs")
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                parsed_list = cast(list[Any], parsed)
                return [item for item in parsed_list if isinstance(item, dict)]
        elif isinstance(raw, list):
            raw_list = cast(list[Any], raw)
            return [item for item in raw_list if isinstance(item, dict)]
        return []

    def update_operation_logs(
        self,
        project_id: str,
        operation: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        """追加操作日志并更新时间."""
        self.ensure_exists(project_id)
        logs = self.get_operation_logs(project_id)
        now = datetime.now()
        entry: dict[str, object] = {
            "operation": operation,
            "timestamp": now.isoformat(),
            "detail": dict(detail or {}),
        }
        logs.append(entry)
        self.update(
            project_id,
            {
                "updated_at": now,
                "operation_logs": json.dumps(logs, ensure_ascii=False),
            },
        )
        self._record_operation_log_activity(
            project_id=project_id,
            index=len(logs) - 1,
            entry=entry,
            timestamp=now,
        )

    def _record_operation_log_activity(
        self,
        *,
        project_id: str,
        index: int,
        entry: dict[str, object],
        timestamp: datetime,
    ) -> None:
        """Mirror one operation-log entry into the durable activity table.

        The activity id is derived from the entry position so the one-shot legacy
        migration cannot double-record the same entry.
        """
        operation = entry.get("operation")
        if not isinstance(operation, str):
            return
        mapping = map_operation_to_activity(operation)
        if mapping is None:
            return
        category, event_type = mapping
        raw_timestamp = entry.get("timestamp")
        raw_detail = entry.get("detail")
        detail_payload: dict[str, Any] = (
            {str(key): value for key, value in cast(dict[Any, Any], raw_detail).items()}
            if isinstance(raw_detail, dict)
            else {}
        )
        paper_id = detail_payload.get("paper_id")
        ProjectActivityStore(self.db).record(
            activity_id=build_operation_log_activity_id(
                project_id,
                index,
                operation,
                raw_timestamp if isinstance(raw_timestamp, str) else "",
            ),
            project_id=project_id,
            category=category,
            event_type=event_type,
            status="info",
            paper_id=paper_id if isinstance(paper_id, str) else None,
            created_at=timestamp,
            updated_at=timestamp,
            detail={"operation": operation, "detail": detail_payload},
        )
