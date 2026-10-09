"""Project overview aggregation tests."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.models import Project
from paper_plane_x_backend.services import Database
from paper_plane_x_backend.services.project.files import ProjectFileError
from paper_plane_x_backend.services.project.overview import ProjectOverviewService
from paper_plane_x_backend.services.project.repository import (
    ProjectRepository,
    ProjectRepositoryError,
)


def _create_project(
    db: Database, project_id: str, *, agent_summary: str | None = None
) -> None:
    now = datetime.now()
    ProjectRepository(db).create(
        Project(
            project_id=project_id,
            name=f"Project {project_id}",
            agent_summary=agent_summary,
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
    )


def _insert_paper(
    db: Database,
    paper_id: str,
    project_ids: list[str],
    *,
    updated_at: datetime | None = None,
    md_content: str | None = "parsed body",
    year: int | None = None,
    tags: list[str] | None = None,
    extraction_status: str = "COMPLETED",
    extraction_fact_check_status: str = "PASSED",
    analysis_fact_check_status: str = "PASSED",
    extraction_fact_check_result: str | None = None,
    analysis_fact_check_result: str | None = None,
) -> None:
    now = updated_at or datetime.now()
    quick_scan = (
        json.dumps({"tags": tags, "verdict": "v", "reason": "r"})
        if tags is not None
        else None
    )
    db.insert(
        "papers",
        {
            "paper_id": paper_id,
            "title": f"Paper {paper_id}",
            "authors": "[]",
            "year": year,
            "md_content": md_content,
            "quick_scan": quick_scan,
            "extraction_status": extraction_status,
            "extraction_fact_check_status": extraction_fact_check_status,
            "analysis_fact_check_status": analysis_fact_check_status,
            "extraction_fact_check_result": extraction_fact_check_result,
            "analysis_fact_check_result": analysis_fact_check_result,
            "created_at": now,
            "updated_at": now,
        },
    )
    for project_id in project_ids:
        db.execute(
            "INSERT INTO paper_projects (paper_id, project_id) VALUES (?, ?)",
            (paper_id, project_id),
        )


def _insert_task(
    db: Database,
    task_id: str,
    paper_id: str,
    status: str,
    *,
    created_at: datetime | None = None,
    error: str | None = None,
) -> None:
    db.insert(
        "data_process_tasks",
        {
            "task_id": task_id,
            "paper_id": paper_id,
            "payload": json.dumps({}),
            "status": status,
            "created_at": created_at or datetime.now(),
            "error": error,
        },
    )


def test_build_overview_aggregates_current_state(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _create_project(db, "p-overview", agent_summary="summary text")
    base = datetime(2026, 3, 1, 10, 0, 0)
    for index in range(6):
        _insert_paper(
            db,
            f"paper-{index}",
            ["p-overview"],
            updated_at=base + timedelta(minutes=index),
            year=2020 + index,
            tags=["nlp", "ml"] if index < 2 else ["nlp"],
        )
    _insert_paper(
        db,
        "paper-unparsed",
        ["p-overview"],
        updated_at=base,
        md_content=None,
        extraction_status="PROCESSING",
    )
    _insert_paper(
        db,
        "paper-failed",
        ["p-overview"],
        updated_at=base,
        extraction_status="PROCESSING",
    )

    _insert_task(db, "task-active", "paper-unparsed", "QUEUED", created_at=base)
    _insert_task(
        db, "task-failed", "paper-failed", "FAILED", created_at=base, error="parse boom"
    )

    sandbox = settings.data_dir / "projects" / "p-overview"
    sandbox.mkdir(parents=True)
    for index in range(6):
        file_path = sandbox / f"note-{index}.md"
        file_path.write_text(f"note {index}", encoding="utf-8")
        os.utime(file_path, (base.timestamp() + index, base.timestamp() + index))
    image_path = sandbox / "figure.png"
    image_path.write_bytes(b"png")
    os.utime(image_path, (base.timestamp() + 10, base.timestamp() + 10))
    (sandbox / "skip.bin").write_bytes(b"bin")
    link = sandbox / "link.md"
    try:
        link.symlink_to(sandbox / "note-0.md")
    except OSError:
        pass

    payload = ProjectOverviewService(db, top_tags_limit=8).build("p-overview")

    assert payload["project_id"] == "p-overview"
    assert payload["agent_summary"] == "summary text"
    assert payload["stats"] == {
        "paper_count": 8,
        "parsed_count": 7,
        "active_task_count": 1,
        "attention_count": 1,
    }
    attention = payload["attention_items"]
    assert len(attention) == 1
    assert attention[0]["paper_id"] == "paper-failed"
    assert attention[0]["stage"] == "task_failed"
    assert attention[0]["error"] == "parse boom"
    assert attention[0]["task_id"] == "task-failed"

    assert len(payload["recent_papers"]) == 5
    assert payload["recent_papers"][0]["paper_id"] == "paper-5"

    recent_files = payload["recent_files"]
    assert len(recent_files) == 5
    assert recent_files[0]["name"] == "figure.png"
    assert recent_files[0]["kind"] == "image"
    assert all(item["kind"] == "text" for item in recent_files[1:])
    assert all(item["name"] != "skip.bin" for item in recent_files)
    assert all(item["name"] != "link.md" for item in recent_files)

    assert payload["year_range"] == "2020-2025"
    assert payload["year_distribution"]["available_count"] == 6
    assert payload["top_tags"][0] == {"tag": "nlp", "count": 6}
    assert payload["top_tags"][1] == {"tag": "ml", "count": 2}
    assert payload["section_errors"] == {}


def test_attention_resolved_after_success(db: Database) -> None:
    _create_project(db, "p-resolved")
    _insert_paper(db, "paper-resolved", ["p-resolved"])
    base = datetime(2026, 4, 1, 10, 0, 0)
    _insert_task(
        db, "task-old", "paper-resolved", "FAILED", created_at=base, error="old"
    )
    _insert_task(
        db,
        "task-new",
        "paper-resolved",
        "COMPLETED",
        created_at=base + timedelta(minutes=5),
    )

    payload = ProjectOverviewService(db).build("p-resolved")

    assert payload["attention_items"] == []
    assert payload["stats"]["attention_count"] == 0


def test_attention_reports_fact_check_failure(db: Database) -> None:
    _create_project(db, "p-fc")
    _insert_paper(
        db,
        "paper-fc",
        ["p-fc"],
        extraction_fact_check_status="FAILED",
        extraction_fact_check_result=json.dumps({"error": "fc failed"}),
    )

    payload = ProjectOverviewService(db).build("p-fc")

    assert payload["stats"]["attention_count"] == 1
    item = payload["attention_items"][0]
    assert item["stage"] == "extraction_fact_check_failed"
    assert item["error"] == "fc failed"


def test_attention_items_capped_while_count_is_full(db: Database) -> None:
    _create_project(db, "p-many-attention")
    base = datetime(2026, 6, 1, 10, 0, 0)
    for index in range(12):
        paper_id = f"paper-attention-{index:02d}"
        _insert_paper(db, paper_id, ["p-many-attention"])
        _insert_task(
            db,
            f"task-attention-{index:02d}",
            paper_id,
            "FAILED",
            created_at=base + timedelta(minutes=index),
            error="failed",
        )

    payload = ProjectOverviewService(db).build("p-many-attention")

    assert payload["stats"]["attention_count"] == 12
    assert len(payload["attention_items"]) == 10


def test_recent_files_filesystem_error_is_section_error(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_project(db, "p-files-error")

    class _FailingManager:
        def sandbox_root(self, project_id: str) -> Path:
            raise ProjectFileError("boom", "sandbox unavailable")

    monkeypatch.setattr(
        "paper_plane_x_backend.services.project.overview.get_project_file_manager",
        lambda: _FailingManager(),
    )

    payload = ProjectOverviewService(db).build("p-files-error")

    assert payload["recent_files"] == []
    assert payload["section_errors"] == {"recent_files": "sandbox unavailable"}


def test_build_overview_requires_existing_project(db: Database) -> None:
    with pytest.raises(ProjectRepositoryError):
        ProjectOverviewService(db).build("missing-project")


def test_auxiliary_statistics_failure_keeps_core_counts(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    from paper_plane_x_backend.services.paper.repository import PaperRepositoryError
    from paper_plane_x_backend.services.project import overview as overview_module

    _create_project(db, "p-stats")
    _insert_paper(db, "paper-stats", ["p-stats"])

    def fail_statistics(**kwargs: object) -> None:
        raise PaperRepositoryError("Synthetic statistics failure")

    monkeypatch.setattr(overview_module, "global_finder_by_project", fail_statistics)
    payload = ProjectOverviewService(db).build("p-stats")
    assert payload["stats"]["paper_count"] == 1
    assert payload["stats"]["parsed_count"] == 1
    assert payload["recent_papers"][0]["paper_id"] == "paper-stats"
    assert payload["section_errors"] == {
        "top_tags": "Synthetic statistics failure",
        "year_distribution": "Synthetic statistics failure",
    }
