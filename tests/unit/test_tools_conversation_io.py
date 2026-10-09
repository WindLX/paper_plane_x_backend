from datetime import datetime
from pathlib import Path

import pytest

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.models import Project
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.project.repository import ProjectRepository
from paper_plane_x_backend.tools import conversation_io


@pytest.fixture
def project_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db: Database
) -> Path:
    ProjectRepository(db).create(
        Project(
            project_id="proj-1",
            name="Synthetic",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
    )
    monkeypatch.setattr(conversation_io, "get_db", lambda: db)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    sandbox = tmp_path / "projects" / "proj-1"
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


def test_read_project_file_lines(project_sandbox: Path) -> None:
    target = project_sandbox / "notes.md"
    target.write_text("a\nb\nc\n", encoding="utf-8")

    assert conversation_io.read_project_file_lines.function is not None
    payload = conversation_io.read_project_file_lines.function(
        file_path="/notes.md",
        start_line=2,
        end_line=3,
        project_id="proj-1",
    )

    assert payload["total_lines"] == 3
    assert payload["lines"] == [
        {"line_no": 2, "text": "b"},
        {"line_no": 3, "text": "c"},
    ]


def test_find_in_project_file(project_sandbox: Path) -> None:
    target = project_sandbox / "notes.md"
    target.write_text("alpha\nbeta alpha\nAlpha\n", encoding="utf-8")

    assert conversation_io.find_in_project_file.function is not None
    payload = conversation_io.find_in_project_file.function(
        file_path="/notes.md",
        query="alpha",
        project_id="proj-1",
    )

    assert payload["total_matches"] == 3
    assert payload["matches"][0]["line_no"] == 1
    assert payload["matches"][1]["line_no"] == 2
    assert payload["matches"][2]["line_no"] == 3


def test_replace_project_file_lines(project_sandbox: Path) -> None:
    target = project_sandbox / "draft.md"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert conversation_io.replace_project_file_lines.function is not None
    payload = conversation_io.replace_project_file_lines.function(
        file_path="/draft.md",
        start_line=2,
        end_line=3,
        new_text="middle\nend",
        project_id="proj-1",
    )

    assert payload["lines_replaced"] == 2
    assert target.read_text(encoding="utf-8") == "one\nmiddle\nend\n"


def test_patch_project_file_insert_after(project_sandbox: Path) -> None:
    target = project_sandbox / "draft.md"
    target.write_text("head\nbody\ntail\n", encoding="utf-8")

    assert conversation_io.patch_project_file.function is not None
    payload = conversation_io.patch_project_file.function(
        file_path="/draft.md",
        action="insert_after",
        anchor_text="body\n",
        content="extra\n",
        project_id="proj-1",
    )

    assert payload["occurrences"] == 1
    assert target.read_text(encoding="utf-8") == "head\nbody\nextra\ntail\n"


def test_replace_project_file_text_reports_occurrence_mismatch(
    project_sandbox: Path,
) -> None:
    target = project_sandbox / "draft.md"
    target.write_text("x\nx\n", encoding="utf-8")

    assert conversation_io.replace_project_file_text.function is not None
    payload = conversation_io.replace_project_file_text.function(
        file_path="/draft.md",
        old_text="x",
        new_text="y",
        project_id="proj-1",
    )

    assert "Expected 1 occurrence" in payload["error"]


def test_project_file_tools_share_editing_guide() -> None:
    guide = conversation_io.read_project_file.shared_guides[
        "Project File Editing Guide"
    ]

    assert conversation_io.write_project_file.shared_guides == (
        conversation_io.read_project_file.shared_guides
    )
    assert "replace_project_file_lines" in guide
    assert "patch_project_file" in guide
    assert "write_project_file" in guide


def test_project_file_editing_guide_mentions_limits() -> None:
    guide = conversation_io.patch_project_file.shared_guides[
        "Project File Editing Guide"
    ]

    assert ".md" in guide
    assert str(conversation_io.MAX_FILE_SIZE) in guide


def test_project_file_tool_errors_preserve_error_payload(
    project_sandbox: Path,
) -> None:
    assert conversation_io.read_project_file.function is not None
    payload = conversation_io.read_project_file.function(
        file_path="/missing.md",
        project_id="proj-1",
    )

    assert payload == {"error": "File not found: /missing.md"}
