"""Project 编排服务（容器语义）。"""

import json
import logging
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from fastapi import status
from fastapi.encoders import jsonable_encoder

from paper_plane_x_backend.models import (
    Paper,
    PaperSortKey,
    Project,
    ProjectSortKey,
    SortOrder,
)
from paper_plane_x_backend.services.conversation.repository import (
    ConversationRepository,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.paper.repository import PaperRepository
from paper_plane_x_backend.services.project.files import (
    ProjectFileError,
    ProjectFileManager,
    get_project_file_manager,
)
from paper_plane_x_backend.services.project.repository import (
    ProjectRepository,
    ProjectRepositoryError,
)
from paper_plane_x_backend.utils.ids import generate_project_id
from paper_plane_x_backend.utils.schema_utils import strip_citations_recursively

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
        file_manager: ProjectFileManager | None = None,
    ) -> None:
        self.paper_repo = PaperRepository(db)
        self.project_repo = ProjectRepository(db)
        self.conversation_repo = ConversationRepository(db)
        self.file_manager = file_manager or get_project_file_manager()

    def _ensure_project_exists(self, project_id: str) -> None:
        try:
            self.project_repo.ensure_exists(project_id)
        except ProjectRepositoryError:
            logger.warning("event=project.not_found project_id=%s", project_id)
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Project {project_id} not found",
            )

    def create_project(
        self, *, name: str, description: str | None, agent_summary: str | None = None
    ) -> Project:
        now = datetime.now()
        project = Project(
            project_id=generate_project_id(),
            name=name,
            description=description,
            agent_summary=agent_summary,
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
        sandbox_created = False
        try:
            sandbox_root = self.file_manager.sandbox_root(project.project_id)
            sandbox_created = not sandbox_root.exists()
            self.file_manager.ensure_project_sandbox(project.project_id)
            self.project_repo.create(project)
        except ProjectFileError as exc:
            if sandbox_created:
                try:
                    self.file_manager.delete_project_sandbox(project.project_id)
                except ProjectFileError:
                    logger.warning(
                        "event=project.sandbox_cleanup_after_create_failed project_id=%s",
                        project.project_id,
                        exc_info=True,
                    )
            raise ProjectDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                exc.message,
            ) from exc
        except Exception:
            if sandbox_created:
                try:
                    self.file_manager.delete_project_sandbox(project.project_id)
                except ProjectFileError:
                    logger.warning(
                        "event=project.sandbox_cleanup_after_create_failed project_id=%s",
                        project.project_id,
                        exc_info=True,
                    )
            raise
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
        sort_order: SortOrder,
        sort_by: ProjectSortKey,
    ) -> tuple[list[Project], int, dict[str, int]]:
        total = self.project_repo.count_all()
        items = self.project_repo.list_all(
            offset=offset, limit=limit, sort_by=sort_by, sort_order=sort_order
        )
        conversation_counts = self._build_conversation_counts(
            [p.project_id for p in items]
        )
        logger.info(
            "event=project.listed offset=%s limit=%s returned=%s total=%s",
            offset,
            limit,
            len(items),
            total,
        )
        return items, total, conversation_counts

    def _build_conversation_counts(self, project_ids: list[str]) -> dict[str, int]:
        """批量获取项目的会话数量."""
        if not project_ids:
            return {}
        placeholders = ",".join(["?"] * len(project_ids))
        rows = self.conversation_repo.db.fetchall(
            f"""
            SELECT project_id, COUNT(*) as count
            FROM conversations
            WHERE project_id IN ({placeholders})
            GROUP BY project_id
            """,
            tuple(project_ids),
        )
        return {row["project_id"]: int(row["count"]) for row in rows}

    def get_project(self, project_id: str) -> Project:
        project = self.project_repo.get(project_id)
        if project is None:
            logger.warning("event=project.not_found project_id=%s", project_id)
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Project {project_id} not found",
            )
        logger.debug("event=project.fetched project_id=%s", project_id)
        return project

    def update_project(
        self,
        *,
        project_id: str,
        name: str | None,
        description: str | None,
        agent_summary: str | None = None,
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
        if agent_summary is not None:
            update_data["agent_summary"] = agent_summary
            changed_fields.append("agent_summary")

        self.project_repo.update(project_id, update_data)
        self.project_repo.update_operation_logs(
            project_id=project_id,
            operation="update_project",
            detail={
                "changed_fields": changed_fields,
                "has_name_input": name is not None,
                "has_description_input": description is not None,
                "has_agent_summary_input": agent_summary is not None,
            },
        )
        logger.info(
            "event=project.updated project_id=%s fields=%s",
            project_id,
            sorted(changed_fields),
        )

        project = self.project_repo.get(project_id)
        if project is None:
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Project {project_id} not found",
            )
        return project

    def delete_project(self, project_id: str) -> None:
        try:
            self.project_repo.delete(project_id)
        except ProjectRepositoryError as exc:
            if exc.error_code == "not_found":
                logger.warning("event=project.not_found project_id=%s", project_id)
                raise ProjectDomainError(
                    status.HTTP_404_NOT_FOUND,
                    exc.message,
                ) from exc
            raise
        try:
            self.file_manager.delete_project_sandbox(project_id)
        except ProjectFileError as exc:
            logger.error(
                "event=project.sandbox_delete_failed project_id=%s code=%s message=%s",
                project_id,
                exc.code,
                exc.message,
                exc_info=True,
            )
            raise ProjectDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                exc.message,
            ) from exc
        logger.info("event=project.deleted project_id=%s", project_id)

    def list_papers(
        self,
        *,
        project_id: str,
        offset: int,
        limit: int,
        sort_order: SortOrder,
        sort_by: PaperSortKey,
    ) -> tuple[list[Paper], int]:
        self._ensure_project_exists(project_id)
        total = self.paper_repo.count_by_project(project_id)
        papers = self.paper_repo.list_by_project(
            project_id=project_id,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        logger.info(
            "event=paper.listed project_id=%s offset=%s limit=%s returned=%s total=%s",
            project_id,
            offset,
            limit,
            len(papers),
            total,
        )
        return papers, total

    def count_project_paper_statuses(self, *, project_id: str) -> dict[str, int]:
        """统计项目下论文的状态分布。"""
        self._ensure_project_exists(project_id)
        return self.paper_repo.count_statuses_by_project(project_id)

    def link_paper(self, *, project_id: str, paper_id: str) -> None:
        self._ensure_project_exists(project_id)
        paper = self.paper_repo.get(paper_id)
        if paper is None:
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Paper {paper_id} not found",
            )
        self.paper_repo.link_to_project(paper_id=paper_id, project_id=project_id)
        self.project_repo.update_operation_logs(
            project_id=project_id,
            operation="link_paper",
            detail={"paper_id": paper_id},
        )

    def unlink_paper(self, *, project_id: str, paper_id: str) -> None:
        self._ensure_project_exists(project_id)
        if not self.paper_repo.is_linked(paper_id=paper_id, project_id=project_id):
            raise ProjectDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Paper {paper_id} not found in project {project_id}",
            )
        self.paper_repo.unlink_from_project(paper_id=paper_id, project_id=project_id)
        self.project_repo.update_operation_logs(
            project_id=project_id,
            operation="unlink_paper",
            detail={"paper_id": paper_id},
        )

    def list_paper_project_ids(self, paper_id: str) -> list[str]:
        return self.paper_repo.list_project_ids(paper_id)

    def list_all_papers(self, *, project_id: str) -> list[Paper]:
        self._ensure_project_exists(project_id)
        return self.paper_repo.list_all_by_project(project_id=project_id)

    def _paper_detail_payload(self, paper: Paper) -> dict[str, Any]:
        return {
            "paper_id": paper.paper_id,
            "project_ids": self.list_paper_project_ids(paper.paper_id),
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "publication": paper.publication,
            "doi": paper.doi,
            "custom_meta": paper.custom_meta,
            "raw_pdf_path": paper.raw_pdf_path,
            "raw_pdf_sha256": paper.raw_pdf_sha256,
            "images_paths": paper.images_paths,
            "extraction_status": paper.extraction_status,
            "extraction_fact_check_status": paper.extraction_fact_check_status,
            "analysis_fact_check_status": paper.analysis_fact_check_status,
            "extraction_retry_count": paper.extraction_retry_count,
            "analysis_retry_count": paper.analysis_retry_count,
            "created_at": paper.created_at,
            "updated_at": paper.updated_at,
            "quick_scan": paper.quick_scan,
            "synthesis_data": paper.synthesis_data,
            "analysis_report": paper.analysis_report,
            "extraction_fact_check_result": paper.extraction_fact_check_result,
            "analysis_fact_check_result": paper.analysis_fact_check_result,
        }

    def export_project_bundle(
        self,
        *,
        project_id: str,
        fields: Sequence[str],
        citations_mode: str,
        include_sandbox_files: bool = False,
    ) -> tuple[str, str]:
        project = self.get_project(project_id)
        papers = self.list_all_papers(project_id=project_id)
        try:
            sandbox_files = (
                self.file_manager.collect_sandbox_files(project_id)
                if include_sandbox_files
                else []
            )
        except ProjectFileError as exc:
            logger.error(
                "event=project.export_sandbox_collect_failed project_id=%s code=%s message=%s",
                project_id,
                exc.code,
                exc.message,
                exc_info=True,
            )
            raise ProjectDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                exc.message,
            ) from exc

        selected_fields = list(dict.fromkeys(fields))
        export_items: list[dict[str, Any]] = []
        file_entries: list[dict[str, Any]] = []

        for paper in papers:
            full_payload = self._paper_detail_payload(paper)
            item: dict[str, Any] = {}
            for field in selected_fields:
                if field not in full_payload:
                    continue
                value = full_payload[field]
                if citations_mode == "strip" and field in {
                    "quick_scan",
                    "synthesis_data",
                    "analysis_report",
                }:
                    value = strip_citations_recursively(value)
                item[field] = value
            export_items.append(jsonable_encoder(item))

            folder_path: str | None = None
            file_count = 0
            raw_pdf_path = paper.raw_pdf_path
            if raw_pdf_path:
                candidate_dir = Path(raw_pdf_path).expanduser().resolve().parent
                if candidate_dir.exists() and candidate_dir.is_dir():
                    folder_path = str(candidate_dir)
                    file_count = sum(
                        1
                        for p in candidate_dir.rglob("*")
                        if p.is_file() and not p.is_symlink()
                    )
            file_entries.append(
                {
                    "paper_id": paper.paper_id,
                    "folder_path": folder_path,
                    "file_count": file_count,
                }
            )

        export_payload = jsonable_encoder(
            {
                "project": {
                    "project_id": project.project_id,
                    "name": project.name,
                    "description": project.description,
                    "created_at": project.created_at,
                    "updated_at": project.updated_at,
                },
                "export_options": {
                    "fields": selected_fields,
                    "citations_mode": citations_mode,
                    "include_sandbox_files": include_sandbox_files,
                },
                "paper_count": len(export_items),
                "papers": export_items,
                "file_folders": file_entries,
                "sandbox_files": {
                    "included": include_sandbox_files,
                    "file_count": len(sandbox_files),
                    "archive_prefix": "project_files"
                    if include_sandbox_files
                    else None,
                },
                "exported_at": datetime.now(),
            }
        )

        safe_project_id = "".join(
            ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in project_id
        )
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"project_{safe_project_id}_export_{now_str}"
        tmp_file = tempfile.NamedTemporaryFile(
            suffix=".zip",
            prefix=f"{base_name}_",
            delete=False,
        )
        zip_path = Path(tmp_file.name)
        tmp_file.close()

        with zipfile.ZipFile(
            zip_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zf:
            zf.writestr(
                f"{base_name}/project_export.json",
                json.dumps(export_payload, ensure_ascii=False, indent=2),
            )

            for paper in papers:
                raw_pdf_path = paper.raw_pdf_path
                if not raw_pdf_path:
                    continue
                candidate_dir = Path(raw_pdf_path).expanduser().resolve().parent
                if not candidate_dir.exists() or not candidate_dir.is_dir():
                    continue
                for file_path in candidate_dir.rglob("*"):
                    if not file_path.is_file() or file_path.is_symlink():
                        continue
                    relative_path = file_path.relative_to(candidate_dir)
                    arcname = f"{base_name}/paper_files/{paper.paper_id}/{relative_path.as_posix()}"
                    zf.write(file_path, arcname=arcname)

            if include_sandbox_files:
                for file_path, relative_path in sandbox_files:
                    arcname = f"{base_name}/project_files/{relative_path}"
                    zf.write(file_path, arcname=arcname)

        logger.info(
            "event=project.exported project_id=%s papers=%s zip_path=%s",
            project_id,
            len(papers),
            str(zip_path),
        )
        return str(zip_path), f"{base_name}.zip"
