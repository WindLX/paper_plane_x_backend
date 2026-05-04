"""Paper orchestrator tests."""

from datetime import datetime

import pytest
from fastapi import status

from paper_plane_x_backend.models import (
    ExtractionStatus,
    FactCheckStatus,
    Paper,
    PaperSortKey,
    SortOrder,
)
from paper_plane_x_backend.services.data_process_tasks.task_manager import (
    DataProcessTaskManager,
)
from paper_plane_x_backend.services.orchestrators.paper import (
    PaperDomainError,
    PaperOrchestrator,
)


@pytest.fixture
def orchestrator(db):
    manager = DataProcessTaskManager(worker_count=1)
    return PaperOrchestrator(db=db, task_manager=manager)


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
        extraction_status=ExtractionStatus.COMPLETED,
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


class TestPaperOrchestrator:
    def test_list_papers(self, orchestrator, db):
        _insert_paper(db, "pap-test-1")
        _insert_paper(db, "pap-test-2")
        papers, total = orchestrator.list_papers(
            offset=0,
            limit=10,
            sort_order=SortOrder.DESC,
            sort_by=PaperSortKey.CREATED_AT,
        )
        assert total == 2
        assert len(papers) == 2

    def test_get_paper(self, orchestrator, db):
        _insert_paper(db, "pap-test-1")
        paper = orchestrator.get_paper(paper_id="pap-test-1")
        assert paper.paper_id == "pap-test-1"

    def test_get_paper_not_found(self, orchestrator):
        with pytest.raises(PaperDomainError) as exc_info:
            orchestrator.get_paper(paper_id="no")
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_batch_get_papers(self, orchestrator, db):
        _insert_paper(db, "pap-test-1")
        _insert_paper(db, "pap-test-2")
        papers, total = orchestrator.batch_get_papers(
            paper_ids=["pap-test-1", "pap-test-2", "no"],
            offset=0,
            limit=10,
            sort_order=SortOrder.DESC,
            sort_by=PaperSortKey.CREATED_AT,
        )
        assert total == 2
        assert len(papers) == 2
        assert {p.paper_id for p in papers} == {"pap-test-1", "pap-test-2"}

    def test_count_paper_statuses(self, orchestrator, db):
        _insert_paper(db, "pap-test-1")
        _insert_paper(db, "pap-test-2")
        counts = orchestrator.count_paper_statuses()
        assert counts["extraction_completed"] == 2
        assert counts["total"] == 2

    def test_update_paper(self, orchestrator, db):
        _insert_paper(db, "pap-test-1")
        updated = orchestrator.update_paper(
            paper_id="pap-test-1",
            title="new title",
            authors=["Alice"],
            year=2025,
            publication="pub",
            doi="10.1/1",
            custom_meta=None,
            extraction_status=None,
            quick_scan=None,
            synthesis_data=None,
            analysis_report=None,
            extraction_fact_check_status=None,
            extraction_fact_check_result=None,
            analysis_fact_check_status=None,
            analysis_fact_check_result=None,
        )
        assert updated.title == "new title"
        assert updated.authors == ["Alice"]
        assert updated.year == 2025

    def test_update_paper_not_found(self, orchestrator):
        with pytest.raises(PaperDomainError) as exc_info:
            orchestrator.update_paper(
                paper_id="no",
                title="t",
                authors=None,
                year=None,
                publication=None,
                doi=None,
                custom_meta=None,
                extraction_status=None,
                quick_scan=None,
                synthesis_data=None,
                analysis_report=None,
                extraction_fact_check_status=None,
                extraction_fact_check_result=None,
                analysis_fact_check_status=None,
                analysis_fact_check_result=None,
            )
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_update_paper_invalid_custom_meta(self, orchestrator, db):
        _insert_paper(db, "pap-test-1")
        with pytest.raises(PaperDomainError) as exc_info:
            orchestrator.update_paper(
                paper_id="pap-test-1",
                title=None,
                authors=None,
                year=None,
                publication=None,
                doi=None,
                custom_meta="not-json",
                extraction_status=None,
                quick_scan=None,
                synthesis_data=None,
                analysis_report=None,
                extraction_fact_check_status=None,
                extraction_fact_check_result=None,
                analysis_fact_check_status=None,
                analysis_fact_check_result=None,
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_update_paper_custom_meta_not_object(self, orchestrator, db):
        _insert_paper(db, "pap-test-1")
        with pytest.raises(PaperDomainError) as exc_info:
            orchestrator.update_paper(
                paper_id="pap-test-1",
                title=None,
                authors=None,
                year=None,
                publication=None,
                doi=None,
                custom_meta='"string"',
                extraction_status=None,
                quick_scan=None,
                synthesis_data=None,
                analysis_report=None,
                extraction_fact_check_status=None,
                extraction_fact_check_result=None,
                analysis_fact_check_status=None,
                analysis_fact_check_result=None,
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_delete_paper(self, orchestrator, db):
        _insert_paper(db, "pap-test-1")
        orchestrator.delete_paper(paper_id="pap-test-1")
        assert (
            db.fetchall("SELECT 1 FROM papers WHERE paper_id=?", ("pap-test-1",)) == []
        )

    def test_delete_paper_not_found(self, orchestrator):
        with pytest.raises(PaperDomainError) as exc_info:
            orchestrator.delete_paper(paper_id="no")
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_paper_processing_blocked(self, orchestrator, db):
        now = datetime.now()
        paper = Paper(
            paper_id="pap-test-1",
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
        with pytest.raises(PaperDomainError) as exc_info:
            orchestrator.delete_paper(paper_id="pap-test-1")
        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
