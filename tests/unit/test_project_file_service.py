from pathlib import Path

import pytest

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services.project.files import (
    MAX_FILE_SIZE,
    ProjectFileError,
    ProjectFileManager,
)


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjectFileManager:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return ProjectFileManager()


def test_ensure_project_sandbox_creates_directory(manager: ProjectFileManager) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")

    assert sandbox == settings.data_dir / "projects" / "proj-1"
    assert sandbox.is_dir()


def test_delete_project_sandbox_removes_nested_directory(
    manager: ProjectFileManager,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    nested = sandbox / "notes" / "draft.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("hello", encoding="utf-8")

    assert manager.delete_project_sandbox("proj-1") is True
    assert not sandbox.exists()
    assert manager.delete_project_sandbox("proj-1") is False


def test_resolve_paths_reject_traversal_and_allow_root(
    manager: ProjectFileManager,
) -> None:
    manager.ensure_project_sandbox("proj-1")

    root = manager.resolve_dir_path("proj-1", "/")
    assert root == settings.data_dir / "projects" / "proj-1"

    with pytest.raises(ProjectFileError, match="Path traversal not allowed"):
        manager.resolve_file_path("proj-1", "/../escape.md")

    with pytest.raises(ProjectFileError, match="Path traversal not allowed"):
        manager.resolve_dir_path("proj-1", "/../proj-10")


def test_resolve_path_uses_relative_to_not_prefix_startswith(
    manager: ProjectFileManager,
) -> None:
    manager.ensure_project_sandbox("proj")
    sibling = settings.data_dir / "projects" / "proj-evolved"
    sibling.mkdir(parents=True)
    outside = sibling / "note.md"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ProjectFileError):
        manager.resolve_file_path("proj", "/../proj-evolved/note.md")


def test_rejects_disallowed_extension(manager: ProjectFileManager) -> None:
    manager.ensure_project_sandbox("proj-1")

    with pytest.raises(ProjectFileError, match="not allowed"):
        manager.write_file("proj-1", "/script.py", "print('x')")


def test_read_write_list_remove_round_trip(manager: ProjectFileManager) -> None:
    manager.ensure_project_sandbox("proj-1")

    write_payload = manager.write_file("proj-1", "/notes/draft.md", "hello\n")
    assert write_payload == {
        "file_path": "/notes/draft.md",
        "bytes_written": 6,
        "is_dir": False,
    }

    root_payload = manager.list_files("proj-1", "/")
    assert root_payload == {"items": [{"name": "notes", "is_dir": True, "size": None}]}

    read_payload = manager.read_file("proj-1", "/notes/draft.md")
    assert read_payload == {"file_path": "/notes/draft.md", "content": "hello\n"}

    remove_payload = manager.remove_path("proj-1", "/notes/draft.md")
    assert remove_payload == {"removed": "/notes/draft.md"}


def test_non_empty_directory_delete_returns_controlled_error(
    manager: ProjectFileManager,
) -> None:
    manager.ensure_project_sandbox("proj-1")
    manager.write_file("proj-1", "/notes/draft.md", "hello")

    with pytest.raises(ProjectFileError) as exc_info:
        manager.remove_path("proj-1", "/notes")

    assert exc_info.value.code == "directory_not_empty"


def test_oversized_write_and_read_return_controlled_errors(
    manager: ProjectFileManager,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")

    with pytest.raises(ProjectFileError) as write_exc:
        manager.write_file("proj-1", "/huge.md", "x" * (MAX_FILE_SIZE + 1))
    assert write_exc.value.status_code == 413

    huge = sandbox / "huge.md"
    huge.write_bytes(b"x" * (MAX_FILE_SIZE + 1))
    with pytest.raises(ProjectFileError) as read_exc:
        manager.read_file("proj-1", "/huge.md")
    assert read_exc.value.status_code == 413


def test_line_find_replace_and_patch_behaviors(manager: ProjectFileManager) -> None:
    manager.ensure_project_sandbox("proj-1")
    manager.write_file("proj-1", "/draft.md", "head\nbody\ntail\n")

    lines_payload = manager.read_file_lines("proj-1", "/draft.md", 2, 3)
    assert lines_payload["lines"] == [
        {"line_no": 2, "text": "body"},
        {"line_no": 3, "text": "tail"},
    ]

    find_payload = manager.find_in_file("proj-1", "/draft.md", "BODY")
    assert find_payload["total_matches"] == 1
    assert find_payload["matches"] == [
        {"line_no": 2, "start_col": 1, "end_col": 4, "text": "body"}
    ]

    replace_lines_payload = manager.replace_file_lines(
        "proj-1",
        "/draft.md",
        2,
        2,
        "middle",
    )
    assert replace_lines_payload["lines_replaced"] == 1

    replace_text_payload = manager.replace_file_text(
        "proj-1",
        "/draft.md",
        "middle",
        "body",
    )
    assert replace_text_payload["replacements"] == 1

    patch_payload = manager.patch_file(
        "proj-1",
        "/draft.md",
        "insert_after",
        "body\n",
        "extra\n",
    )
    assert patch_payload["occurrences"] == 1
    assert manager.read_file("proj-1", "/draft.md")["content"] == (
        "head\nbody\nextra\ntail\n"
    )


def test_collect_sandbox_files_skips_symlinks(manager: ProjectFileManager) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    manager.write_file("proj-1", "/notes/draft.md", "hello")
    outside = settings.data_dir / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (sandbox / "outside.md").symlink_to(outside)

    files = manager.collect_sandbox_files("proj-1")

    assert files == [(sandbox / "notes" / "draft.md", "notes/draft.md")]


def test_download_file_returns_raw_bytes_without_decoding(
    manager: ProjectFileManager,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    payload = b"\x00\xff\xfe\r\nraw bytes\r\n"
    target = sandbox / "notes" / "raw.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)

    result = manager.download_file("proj-1", "/notes/raw.txt")

    assert result.content == payload
    assert result.content_type == "text/plain"
    assert result.download_name == "raw.txt"


def test_download_file_keeps_non_ascii_download_name(
    manager: ProjectFileManager,
) -> None:
    manager.ensure_project_sandbox("proj-1")
    manager.write_file("proj-1", "/中文/报告.md", "# 报告\n")

    result = manager.download_file("proj-1", "/中文/报告.md")

    assert result.content == "# 报告\n".encode()
    assert result.content_type == "text/markdown"
    assert result.download_name == "报告.md"


def test_download_file_reuses_missing_directory_and_extension_errors(
    manager: ProjectFileManager,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    (sandbox / "empty").mkdir()

    with pytest.raises(ProjectFileError) as missing_exc:
        manager.download_file("proj-1", "/missing.md")
    assert missing_exc.value.code == "not_found"

    with pytest.raises(ProjectFileError) as directory_exc:
        manager.download_file("proj-1", "/empty")
    assert directory_exc.value.code == "path_is_directory"

    with pytest.raises(ProjectFileError) as extension_exc:
        manager.download_file("proj-1", "/script.py")
    assert extension_exc.value.code == "invalid_extension"

    with pytest.raises(ProjectFileError) as traversal_exc:
        manager.download_file("proj-1", "/../escape.md")
    assert traversal_exc.value.code == "path_traversal"


def test_download_file_rejects_symlink_escape(manager: ProjectFileManager) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    outside = settings.data_dir / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (sandbox / "escape.md").symlink_to(outside)

    with pytest.raises(ProjectFileError) as exc_info:
        manager.download_file("proj-1", "/escape.md")

    assert exc_info.value.code == "path_escapes_sandbox"


def test_download_file_rejects_oversized_file(manager: ProjectFileManager) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    huge = sandbox / "huge.md"
    huge.write_bytes(b"x" * (MAX_FILE_SIZE + 1))

    with pytest.raises(ProjectFileError) as exc_info:
        manager.download_file("proj-1", "/huge.md")

    assert exc_info.value.code == "file_too_large"
    assert exc_info.value.status_code == 413
