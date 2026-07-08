"""Project 数据仓库.

封装所有 projects 表的数据库访问，不包含任何业务编排或外部服务调用逻辑。
"""

import json
import logging
from datetime import datetime
from typing import Any, cast

from paper_plane_x_backend.models import Project, ProjectSortKey, SortOrder
from paper_plane_x_backend.services.database import Database

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
        logs.append(
            {
                "operation": operation,
                "timestamp": datetime.now().isoformat(),
                "detail": dict(detail or {}),
            }
        )
        self.update(
            project_id,
            {
                "updated_at": datetime.now(),
                "operation_logs": json.dumps(logs, ensure_ascii=False),
            },
        )
