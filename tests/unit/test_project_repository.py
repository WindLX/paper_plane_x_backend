"""ProjectRepository tests."""

from datetime import datetime

import pytest

from paper_plane_x_backend.models import Project
from paper_plane_x_backend.models.sort import SortOrder
from paper_plane_x_backend.services.project.repository import (
    ProjectRepository,
    ProjectRepositoryError,
)


class TestProjectRepository:
    """ProjectRepository 测试类."""

    def test_create_and_get(self, db) -> None:
        """验证创建项目后可正确读取."""
        repo = ProjectRepository(db)
        now = datetime.now()
        project = Project(
            project_id="proj-1",
            name="Test Project",
            description="desc",
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
        repo.create(project)

        fetched = repo.get("proj-1")
        assert fetched is not None
        assert fetched.project_id == "proj-1"
        assert fetched.name == "Test Project"
        assert fetched.description == "desc"

    def test_get_returns_none_for_missing(self, db) -> None:
        """验证获取不存在的项目返回 None."""
        repo = ProjectRepository(db)
        assert repo.get("non-existent") is None

    def test_exists(self, db) -> None:
        """验证 exists 检查."""
        repo = ProjectRepository(db)
        now = datetime.now()
        project = Project(
            project_id="proj-exists",
            name="Exists",
            description=None,
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
        repo.create(project)
        assert repo.exists("proj-exists") is True
        assert repo.exists("not-exists") is False

    def test_ensure_exists_raises(self, db) -> None:
        """验证 ensure_exists 对不存在项目抛出异常."""
        repo = ProjectRepository(db)
        with pytest.raises(ProjectRepositoryError, match="not found") as exc_info:
            repo.ensure_exists("missing")
        assert exc_info.value.error_code == "not_found"
        assert exc_info.value.project_id == "missing"

    def test_list_all_with_pagination(self, db) -> None:
        """验证 list_all 分页和排序."""
        repo = ProjectRepository(db)
        for i in range(3):
            now = datetime.now()
            repo.create(
                Project(
                    project_id=f"proj-{i}",
                    name=f"Project {i}",
                    description=None,
                    created_at=now,
                    updated_at=now,
                    operation_logs=[],
                )
            )

        items = repo.list_all(offset=0, limit=2)
        assert len(items) == 2
        assert repo.count_all() == 3

        # 默认按 created_at DESC
        items_asc = repo.list_all(offset=0, limit=10, sort_order=SortOrder.ASC)
        assert len(items_asc) == 3

    def test_update(self, db) -> None:
        """验证通用 update 接口."""
        repo = ProjectRepository(db)
        now = datetime.now()
        repo.create(
            Project(
                project_id="proj-update",
                name="Before",
                description=None,
                created_at=now,
                updated_at=now,
                operation_logs=[],
            )
        )
        repo.update("proj-update", {"name": "After"})
        fetched = repo.get("proj-update")
        assert fetched is not None
        assert fetched.name == "After"

    def test_delete_cleans_up_paper_links(self, db) -> None:
        """验证删除项目时清理 paper_projects 关联."""
        from paper_plane_x_backend.models import ExtractionStatus
        from paper_plane_x_backend.services.paper.repository import PaperRepository

        paper_repo = PaperRepository(db)
        project_repo = ProjectRepository(db)

        now = datetime.now()
        project_repo.create(
            Project(
                project_id="proj-del",
                name="To Delete",
                description=None,
                created_at=now,
                updated_at=now,
                operation_logs=[],
            )
        )
        paper = paper_repo.create(extraction_status=ExtractionStatus.PENDING)
        paper_repo.link_to_project(paper.paper_id, "proj-del")

        assert paper_repo.is_linked(paper.paper_id, "proj-del") is True
        project_repo.delete("proj-del")

        assert project_repo.get("proj-del") is None
        assert paper_repo.is_linked(paper.paper_id, "proj-del") is False

    def test_delete_raises_for_missing(self, db) -> None:
        """验证删除不存在的项目抛出异常."""
        repo = ProjectRepository(db)
        with pytest.raises(ProjectRepositoryError, match="not found") as exc_info:
            repo.delete("missing")
        assert exc_info.value.error_code == "not_found"

    def test_agent_summary(self, db) -> None:
        """验证 agent_summary CRUD."""
        repo = ProjectRepository(db)
        now = datetime.now()
        repo.create(
            Project(
                project_id="proj-summary",
                name="Summary Test",
                description=None,
                created_at=now,
                updated_at=now,
                operation_logs=[],
            )
        )
        assert repo.get_agent_summary("proj-summary") is None

        repo.set_agent_summary("proj-summary", "summary content")
        assert repo.get_agent_summary("proj-summary") == "summary content"

        repo.delete_agent_summary("proj-summary")
        # 删除后置为空字符串
        assert repo.get_agent_summary("proj-summary") == ""

    def test_operation_logs(self, db) -> None:
        """验证操作日志的追加和读取."""
        repo = ProjectRepository(db)
        now = datetime.now()
        repo.create(
            Project(
                project_id="proj-logs",
                name="Logs Test",
                description=None,
                created_at=now,
                updated_at=now,
                operation_logs=[],
            )
        )
        logs = repo.get_operation_logs("proj-logs")
        assert logs == []

        repo.update_operation_logs("proj-logs", "create", {"detail": "x"})
        logs = repo.get_operation_logs("proj-logs")
        assert len(logs) == 1
        assert logs[0]["operation"] == "create"
        assert logs[0]["detail"] == {"detail": "x"}

        repo.update_operation_logs("proj-logs", "update", {"detail": "y"})
        logs = repo.get_operation_logs("proj-logs")
        assert len(logs) == 2
        assert logs[1]["operation"] == "update"
