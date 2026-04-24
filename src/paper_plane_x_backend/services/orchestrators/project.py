"""Project 编排服务（容器语义）。"""

import json
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import status

from paper_plane_x_backend.models import Paper, Project
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.paper.repository import PaperRepository

logger = logging.getLogger(__name__)


class ProjectDomainError(Exception):
    """Project 业务异常（由 Router 映射为 HTTP 错误）。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ProjectOrchestrator:
    """Project 容器与 Paper 关系管理入口。"""

    def __init__(
        self,
        db: Database,
    ) -> None:
        self.db = db
        self.paper_repo = PaperRepository(db)

    def _ensure_project_exists(self, project_id: str) -> None:
        row = self.db.fetchone(
            "SELECT 1 FROM projects WHERE project_id = ?",
            (project_id,),
        )
        if row is None:
            logger.warning("event=project.not_found project_id=%s", project_id)
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Project {project_id} not found",
            )

    def _load_operation_logs(self, project_id: str) -> list[dict[str, Any]]:
        row = self.db.fetchone(
            "SELECT operation_logs FROM projects WHERE project_id = ?",
            (project_id,),
        )
        if row is None:
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Project {project_id} not found",
            )

        raw = row.get("operation_logs")
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        elif isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]

        return []

    def _build_operation_logs_payload(
        self,
        *,
        project_id: str,
        operation: str,
        detail: Mapping[str, object] | None = None,
    ) -> str:
        logs = self._load_operation_logs(project_id)
        logs.append(
            {
                "operation": operation,
                "timestamp": datetime.now().isoformat(),
                "detail": dict(detail or {}),
            }
        )
        return json.dumps(logs, ensure_ascii=False)

    def create_project(self, *, name: str, description: str | None) -> Project:
        now = datetime.now()
        project = Project(
            project_id=str(uuid4()),
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
        self.db.insert("projects", project.to_db_dict())
        logger.info(
            "event=project.created project_id=%s name=%s",
            project.project_id,
            project.name,
        )
        return project

    def list_projects(
        self,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[Project], int]:
        count_result = self.db.fetchone("SELECT COUNT(*) as count FROM projects")
        total = count_result["count"] if count_result else 0
        rows = self.db.fetchall(
            """
            SELECT * FROM projects
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        items = [Project.from_db_row(row) for row in rows]
        logger.info(
            "event=project.listed offset=%s limit=%s returned=%s total=%s",
            offset,
            limit,
            len(items),
            total,
        )
        return items, total

    def get_project(self, project_id: str) -> Project:
        row = self.db.fetchone(
            "SELECT * FROM projects WHERE project_id = ?",
            (project_id,),
        )
        if row is None:
            logger.warning("event=project.not_found project_id=%s", project_id)
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Project {project_id} not found",
            )
        logger.debug("event=project.fetched project_id=%s", project_id)
        return Project.from_db_row(row)

    def update_project(
        self,
        *,
        project_id: str,
        name: str | None,
        description: str | None,
    ) -> Project:
        self._ensure_project_exists(project_id)

        changed_fields: list[str] = []
        update_data: dict[str, object] = {"updated_at": datetime.now()}
        if name is not None:
            update_data["name"] = name
            changed_fields.append("name")
        if description is not None:
            update_data["description"] = description
            changed_fields.append("description")

        update_data["operation_logs"] = self._build_operation_logs_payload(
            project_id=project_id,
            operation="update_project",
            detail={
                "changed_fields": changed_fields,
                "has_name_input": name is not None,
                "has_description_input": description is not None,
            },
        )
        self.db.update("projects", update_data, "project_id = ?", (project_id,))
        logger.info(
            "event=project.updated project_id=%s fields=%s",
            project_id,
            sorted(changed_fields),
        )

        row = self.db.fetchone(
            "SELECT * FROM projects WHERE project_id = ?",
            (project_id,),
        )
        if row is None:
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Project {project_id} not found",
            )
        return Project.from_db_row(row)

    def delete_project(self, project_id: str) -> None:
        self._ensure_project_exists(project_id)
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

    def list_papers(
        self,
        *,
        project_id: str,
        offset: int,
        limit: int,
    ) -> tuple[list[Paper], int]:
        self._ensure_project_exists(project_id)
        count_result = self.db.fetchone(
            "SELECT COUNT(*) as count FROM paper_projects WHERE project_id = ?",
            (project_id,),
        )
        total = count_result["count"] if count_result else 0
        rows = self.db.fetchall(
            """
            SELECT p.*
            FROM papers p
            JOIN paper_projects pp ON pp.paper_id = p.paper_id
            WHERE pp.project_id = ?
            ORDER BY p.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (project_id, limit, offset),
        )
        papers = [Paper.from_db_row(row) for row in rows]
        logger.info(
            "event=paper.listed project_id=%s offset=%s limit=%s returned=%s total=%s",
            project_id,
            offset,
            limit,
            len(papers),
            total,
        )
        return papers, total

    def link_paper(self, *, project_id: str, paper_id: str) -> None:
        self._ensure_project_exists(project_id)
        paper = self.paper_repo.get(paper_id)
        if paper is None:
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Paper {paper_id} not found",
            )
        self.paper_repo.link_to_project(paper_id=paper_id, project_id=project_id)
        self.db.update(
            "projects",
            {
                "updated_at": datetime.now(),
                "operation_logs": self._build_operation_logs_payload(
                    project_id=project_id,
                    operation="link_paper",
                    detail={"paper_id": paper_id},
                ),
            },
            "project_id = ?",
            (project_id,),
        )

    def unlink_paper(self, *, project_id: str, paper_id: str) -> None:
        self._ensure_project_exists(project_id)
        if not self.paper_repo.is_linked(paper_id=paper_id, project_id=project_id):
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Paper {paper_id} not found in project {project_id}",
            )
        self.paper_repo.unlink_from_project(paper_id=paper_id, project_id=project_id)
        self.db.update(
            "projects",
            {
                "updated_at": datetime.now(),
                "operation_logs": self._build_operation_logs_payload(
                    project_id=project_id,
                    operation="unlink_paper",
                    detail={"paper_id": paper_id},
                ),
            },
            "project_id = ?",
            (project_id,),
        )

    def list_paper_project_ids(self, paper_id: str) -> list[str]:
        return self.paper_repo.list_project_ids(paper_id)
