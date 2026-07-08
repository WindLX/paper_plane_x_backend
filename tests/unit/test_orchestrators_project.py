"""Project orchestrator tests."""

import json
from datetime import datetime

import pytest
from fastapi import status

from paper_plane_x_backend.models import (
    ExtractionStatus,
    FactCheckStatus,
    Paper,
    PaperSortKey,
    Project,
    ProjectSortKey,
    SortOrder,
)
from paper_plane_x_backend.services.orchestrators.project import (
    ProjectDomainError,
    ProjectOrchestrator,
)


@pytest.fixture
def orchestrator(db):
    return ProjectOrchestrator(db=db)


def _insert_project(db, project_id: str = "prj-test-1") -> Project:
    now = datetime.now()
    project = Project(
        project_id=project_id,
        name="orchestrator-test",
        description=None,
        created_at=now,
        updated_at=now,
        operation_logs=[],
    )
    db.insert("projects", project.to_db_dict())
    return project


def _insert_paper(db, paper_id: str = "pap-test-1") -> Paper:
    now = datetime.now()
    paper = Paper(
        paper_id=paper_id,
        title="t",
        authors=[],
        year=2024,
        publication="p",
        doi=None,
        custom_meta=None,
        raw_pdf_path=None,
        raw_pdf_sha256=None,
        images_paths=[],
        extraction_status=ExtractionStatus.PROCESSING,
        extraction_fact_check_status=FactCheckStatus.PENDING,
        analysis_fact_check_status=FactCheckStatus.PENDING,
        extraction_retry_count=0,
        analysis_retry_count=0,
        created_at=now,
        updated_at=now,
        quick_scan=None,
        synthesis_data=None,
        analysis_report=None,
        extraction_fact_check_result=None,
        analysis_fact_check_result=None,
    )
    db.insert("papers", paper.to_db_dict())
    return paper


class TestProjectOrchestrator:
    def test_create_project(self, orchestrator):
        project = orchestrator.create_project(
            name="New Project", description="desc", agent_summary="summary"
        )
        assert project.name == "New Project"
        assert project.description == "desc"
        assert project.agent_summary == "summary"
        assert project.project_id is not None

    def test_list_projects(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        _insert_project(db, "prj-test-2")
        items, total = orchestrator.list_projects(
            offset=0,
            limit=10,
            sort_order=SortOrder.DESC,
            sort_by=ProjectSortKey.CREATED_AT,
        )
        assert total == 2
        assert len(items) == 2

    def test_get_project(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        project = orchestrator.get_project("prj-test-1")
        assert project.project_id == "prj-test-1"

    def test_get_project_not_found(self, orchestrator):
        with pytest.raises(ProjectDomainError) as exc_info:
            orchestrator.get_project("nonexistent")
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_update_project(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        updated = orchestrator.update_project(
            project_id="prj-test-1", name="Updated", description="new desc"
        )
        assert updated.name == "Updated"
        assert updated.description == "new desc"
        rows = db.fetchall("SELECT * FROM projects WHERE project_id=?", ("prj-test-1",))
        assert (
            json.loads(rows[0]["operation_logs"])[-1]["operation"] == "update_project"
        )

    def test_update_project_not_found(self, orchestrator):
        with pytest.raises(ProjectDomainError) as exc_info:
            orchestrator.update_project(project_id="no", name="x", description=None)
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_project(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        orchestrator.delete_project("prj-test-1")
        assert (
            db.fetchall("SELECT 1 FROM projects WHERE project_id=?", ("prj-test-1",))
            == []
        )

    def test_delete_project_not_found(self, orchestrator):
        with pytest.raises(ProjectDomainError) as exc_info:
            orchestrator.delete_project("no")
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_list_papers(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        _insert_paper(db, "pap-test-1")
        orchestrator.link_paper(project_id="prj-test-1", paper_id="pap-test-1")
        papers, total = orchestrator.list_papers(
            project_id="prj-test-1",
            offset=0,
            limit=10,
            sort_order=SortOrder.DESC,
            sort_by=PaperSortKey.CREATED_AT,
        )
        assert total == 1
        assert papers[0].paper_id == "pap-test-1"

    def test_list_papers_project_not_found(self, orchestrator):
        with pytest.raises(ProjectDomainError) as exc_info:
            orchestrator.list_papers(
                project_id="no",
                offset=0,
                limit=10,
                sort_order=SortOrder.DESC,
                sort_by=PaperSortKey.CREATED_AT,
            )
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_link_paper(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        _insert_paper(db, "pap-test-1")
        orchestrator.link_paper(project_id="prj-test-1", paper_id="pap-test-1")
        rows = db.fetchall(
            "SELECT * FROM paper_projects WHERE paper_id=? AND project_id=?",
            ("pap-test-1", "prj-test-1"),
        )
        assert len(rows) == 1

    def test_link_paper_paper_not_found(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        with pytest.raises(ProjectDomainError) as exc_info:
            orchestrator.link_paper(project_id="prj-test-1", paper_id="no")
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_unlink_paper(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        _insert_paper(db, "pap-test-1")
        orchestrator.link_paper(project_id="prj-test-1", paper_id="pap-test-1")
        orchestrator.unlink_paper(project_id="prj-test-1", paper_id="pap-test-1")
        rows = db.fetchall(
            "SELECT * FROM paper_projects WHERE paper_id=? AND project_id=?",
            ("pap-test-1", "prj-test-1"),
        )
        assert len(rows) == 0

    def test_unlink_paper_not_linked(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        with pytest.raises(ProjectDomainError) as exc_info:
            orchestrator.unlink_paper(project_id="prj-test-1", paper_id="no")
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_list_all_papers(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        _insert_paper(db, "pap-test-1")
        _insert_paper(db, "pap-test-2")
        orchestrator.link_paper(project_id="prj-test-1", paper_id="pap-test-1")
        orchestrator.link_paper(project_id="prj-test-1", paper_id="pap-test-2")
        papers = orchestrator.list_all_papers(project_id="prj-test-1")
        assert len(papers) == 2

    def test_count_project_paper_statuses(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        _insert_paper(db, "pap-test-1")
        _insert_paper(db, "pap-test-2")
        orchestrator.link_paper(project_id="prj-test-1", paper_id="pap-test-1")
        orchestrator.link_paper(project_id="prj-test-1", paper_id="pap-test-2")
        counts = orchestrator.count_project_paper_statuses(project_id="prj-test-1")
        assert counts["extraction_processing"] == 2
        assert counts["extraction_pending"] == 0
        assert counts["analysis_fact_check_pending"] == 2

    def test_paper_detail_payload(self, orchestrator, db):
        _insert_project(db, "prj-test-1")
        _insert_paper(db, "pap-test-1")
        orchestrator.link_paper(project_id="prj-test-1", paper_id="pap-test-1")
        paper = orchestrator.paper_repo.get("pap-test-1")
        payload = orchestrator._paper_detail_payload(paper)
        assert payload["paper_id"] == "pap-test-1"
        assert payload["project_ids"] == ["prj-test-1"]
