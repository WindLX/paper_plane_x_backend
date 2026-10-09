from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services.project import files as project_files
from paper_plane_x_backend.services.project.files import (
    MAX_FILE_SIZE,
    ProjectFileError,
    ProjectFileManager,
)


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (200, 10, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


def _webp_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (10, 200, 10)).save(buffer, format="WEBP")
    return buffer.getvalue()


def _install_conversion_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_convert(
        content: str,
        output_format: str,
        title: str | None = None,
        *,
        workdir: Path | None = None,
        input_relative_path: str = "input.md",
        embed_resources: bool = False,
    ) -> bytes:
        assert workdir is not None
        files = sorted(
            path.relative_to(workdir).as_posix()
            for path in workdir.rglob("*")
            if path.is_file()
        )
        captured["content"] = content
        captured["output_format"] = output_format
        captured["title"] = title
        captured["input_relative_path"] = input_relative_path
        captured["embed_resources"] = embed_resources
        captured["files"] = files
        captured["contents"] = {name: (workdir / name).read_bytes() for name in files}
        return b"rendered-output"

    monkeypatch.setattr(project_files, "convert_markdown", fake_convert)
    return captured


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
    assert [item["name"] for item in root_payload["items"]] == ["notes"]
    root_item = root_payload["items"][0]
    assert root_item["is_dir"] is True
    assert root_item["size"] is None
    assert root_item["kind"] == "directory"
    assert root_item["content_type"] is None
    assert root_item["modified_at"] is not None

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


def test_list_reports_kind_and_content_type(manager: ProjectFileManager) -> None:
    manager.ensure_project_sandbox("proj-1")
    manager.write_file("proj-1", "/note.md", "# note\n")
    manager.write_bytes("proj-1", "/images/figure.png", _png_bytes())
    manager.write_file("proj-1", "/empty", "", is_dir=True)

    payload = manager.list_files("proj-1", "/")
    by_name = {item["name"]: item for item in payload["items"]}

    assert by_name["note.md"]["kind"] == "text"
    assert by_name["note.md"]["content_type"] == "text/markdown"
    assert by_name["images"]["kind"] == "directory"
    assert by_name["images"]["content_type"] is None
    assert by_name["empty"]["kind"] == "directory"

    image_payload = manager.list_files("proj-1", "/images")
    image_item = image_payload["items"][0]
    assert image_item["kind"] == "image"
    assert image_item["content_type"] == "image/png"
    assert image_item["size"] == len(_png_bytes())


def test_text_apis_reject_image_files(manager: ProjectFileManager) -> None:
    manager.ensure_project_sandbox("proj-1")
    manager.write_bytes("proj-1", "/images/figure.png", _png_bytes())

    for operation in (
        lambda: manager.read_file("proj-1", "/images/figure.png"),
        lambda: manager.read_file_lines("proj-1", "/images/figure.png", 1, 1),
        lambda: manager.find_in_file("proj-1", "/images/figure.png", "x"),
    ):
        with pytest.raises(ProjectFileError) as exc_info:
            operation()
        assert exc_info.value.code == "not_text_file"
        assert exc_info.value.status_code == 400

    with pytest.raises(ProjectFileError) as exc_info:
        manager.write_file("proj-1", "/images/figure.png", "text")
    assert exc_info.value.code == "invalid_extension"


def test_write_bytes_validates_image_content_but_preserves_raw_bytes(
    manager: ProjectFileManager,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")

    with pytest.raises(ProjectFileError) as exc_info:
        manager.write_bytes("proj-1", "/fake.png", b"not a png")
    assert exc_info.value.code == "invalid_image_content"
    assert not (sandbox / "fake.png").exists()

    payload = _png_bytes()
    result = manager.write_bytes("proj-1", "/images/figure.png", payload)

    assert result["bytes_written"] == len(payload)
    assert (sandbox / "images" / "figure.png").read_bytes() == payload


def test_write_bytes_rejects_unsafe_svg(manager: ProjectFileManager) -> None:
    manager.ensure_project_sandbox("proj-1")
    unsafe = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

    with pytest.raises(ProjectFileError) as exc_info:
        manager.write_bytes("proj-1", "/unsafe.svg", unsafe)

    assert exc_info.value.code == "svg_forbidden_element"


def test_preview_and_download_images(manager: ProjectFileManager) -> None:
    manager.ensure_project_sandbox("proj-1")
    payload = _png_bytes()
    manager.write_bytes("proj-1", "/图片/图 一.png", payload)

    preview = manager.preview_image("proj-1", "/图片/图 一.png")
    assert preview.content == payload
    assert preview.content_type == "image/png"
    assert preview.download_name == "图 一.png"

    download = manager.download_file("proj-1", "/图片/图 一.png")
    assert download.content == payload
    assert download.content_type == "image/png"

    manager.write_file("proj-1", "/note.md", "note")
    with pytest.raises(ProjectFileError) as exc_info:
        manager.preview_image("proj-1", "/note.md")
    assert exc_info.value.code == "not_an_image"


def test_remove_path_accepts_images(manager: ProjectFileManager) -> None:
    manager.ensure_project_sandbox("proj-1")
    manager.write_bytes("proj-1", "/figure.png", _png_bytes())

    assert manager.remove_path("proj-1", "/figure.png") == {"removed": "/figure.png"}


def test_export_markdown_returns_original_bytes(manager: ProjectFileManager) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    raw = "# 标题\r\n\r\n内容\r\n".encode()
    (sandbox / "draft.md").write_bytes(raw)

    result = manager.export_markdown_file("proj-1", "/draft.md", "markdown")

    assert result.content == raw
    assert result.content_type == "text/markdown; charset=utf-8"
    assert result.download_name == "draft.md"


def test_export_markdown_skips_resource_preflight(manager: ProjectFileManager) -> None:
    manager.ensure_project_sandbox("proj-1")
    manager.write_file("proj-1", "/draft.md", "![x](missing.png)\n")

    result = manager.export_markdown_file("proj-1", "/draft.md", "markdown")

    assert result.content == b"![x](missing.png)\n"


def test_export_html_stages_only_referenced_resources(
    manager: ProjectFileManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    (sandbox / "images").mkdir()
    (sandbox / "images" / "used.png").write_bytes(_png_bytes())
    (sandbox / "images" / "unused.png").write_bytes(_png_bytes())
    manager.write_file("proj-1", "/notes/draft.md", "![used](../images/used.png)\n")
    captured = _install_conversion_capture(monkeypatch)

    result = manager.export_markdown_file("proj-1", "/notes/draft.md", "html")

    assert result.content == b"rendered-output"
    assert result.content_type == "text/html; charset=utf-8"
    assert captured["embed_resources"] is True
    assert captured["input_relative_path"] == "notes/draft.md"
    assert captured["content"] == "![used](../images/used.png)\n"
    assert captured["files"] == ["images/used.png"]


def test_export_rewrites_root_relative_references(
    manager: ProjectFileManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    (sandbox / "assets").mkdir()
    (sandbox / "assets" / "a.png").write_bytes(_png_bytes())
    manager.write_file(
        "proj-1",
        "/notes/draft.md",
        '![a](/assets/a.png)\n\n<img src="/assets/a.png" width="10">\n',
    )
    captured = _install_conversion_capture(monkeypatch)

    manager.export_markdown_file("proj-1", "/notes/draft.md", "html")

    assert captured["content"] == (
        '![a](../assets/a.png)\n\n<img src="../assets/a.png" width="10">\n'
    )
    assert captured["files"] == ["assets/a.png"]


def test_export_resolves_percent_encoded_chinese_and_space_paths(
    manager: ProjectFileManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    (sandbox / "图片").mkdir()
    (sandbox / "图片" / "图 一.png").write_bytes(_png_bytes())
    manager.write_file(
        "proj-1",
        "/draft.md",
        "![a](%E5%9B%BE%E7%89%87/%E5%9B%BE%20%E4%B8%80.png)\n",
    )
    captured = _install_conversion_capture(monkeypatch)

    manager.export_markdown_file("proj-1", "/draft.md", "html")

    assert captured["files"] == ["图片/图 一.png"]
    assert captured["content"] == "![a](%E5%9B%BE%E7%89%87/%E5%9B%BE%20%E4%B8%80.png)\n"


def test_export_ignores_references_inside_code_fences(
    manager: ProjectFileManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager.ensure_project_sandbox("proj-1")
    markdown = "```\n![x](missing.png)\n```\n\n`![y](missing.png)`\n"
    manager.write_file("proj-1", "/draft.md", markdown)
    captured = _install_conversion_capture(monkeypatch)

    manager.export_markdown_file("proj-1", "/draft.md", "html")

    assert captured["files"] == []
    assert captured["content"] == markdown


@pytest.mark.parametrize(
    ("markdown", "expected_reasons"),
    [
        (
            '![missing](images/missing.png)\n\n<img src="https://example.com/a.png">\n',
            {"missing", "external"},
        ),
        ("![escape](../outside.png)\n", {"path_escapes_sandbox"}),
        ("![unsupported](notes.txt)\n", {"unsupported_type"}),
    ],
)
def test_export_preflight_reports_invalid_references(
    manager: ProjectFileManager,
    markdown: str,
    expected_reasons: set[str],
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    (sandbox / "notes.txt").write_text("text", encoding="utf-8")
    manager.write_file("proj-1", "/draft.md", markdown)

    with pytest.raises(ProjectFileError) as exc_info:
        manager.export_markdown_file("proj-1", "/draft.md", "html")

    assert exc_info.value.code == "export_invalid_resources"
    assert exc_info.value.status_code == 400
    details = exc_info.value.details
    assert details is not None
    references = details["references"]
    assert isinstance(references, list)
    assert {entry["reason"] for entry in references} == expected_reasons


def test_export_preflight_rejects_symlinked_resources(
    manager: ProjectFileManager,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    outside = settings.data_dir / "outside.png"
    outside.write_bytes(_png_bytes())
    (sandbox / "link.png").symlink_to(outside)
    manager.write_file("proj-1", "/draft.md", "![b](link.png)\n")

    with pytest.raises(ProjectFileError) as exc_info:
        manager.export_markdown_file("proj-1", "/draft.md", "html")

    details = exc_info.value.details
    assert details is not None
    references = details["references"]
    assert isinstance(references, list)
    assert [entry["reason"] for entry in references] == ["symlink"]


def test_export_docx_converts_webp_to_png(
    manager: ProjectFileManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    (sandbox / "picture.webp").write_bytes(_webp_bytes())
    manager.write_file("proj-1", "/doc.md", "![w](picture.webp)\n")
    captured = _install_conversion_capture(monkeypatch)

    manager.export_markdown_file("proj-1", "/doc.md", "docx")

    assert captured["content"] == "![w](picture__ppx_webp_0.png)\n"
    assert captured["files"] == ["picture__ppx_webp_0.png"]
    contents = captured["contents"]
    assert isinstance(contents, dict)
    assert contents["picture__ppx_webp_0.png"].startswith(b"\x89PNG\r\n\x1a\n")


def test_export_html_keeps_image_formats_unchanged(
    manager: ProjectFileManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = manager.ensure_project_sandbox("proj-1")
    webp = _webp_bytes()
    (sandbox / "picture.webp").write_bytes(webp)
    manager.write_file("proj-1", "/doc.md", "![w](picture.webp)\n")
    captured = _install_conversion_capture(monkeypatch)

    manager.export_markdown_file("proj-1", "/doc.md", "html")

    assert captured["content"] == "![w](picture.webp)\n"
    contents = captured["contents"]
    assert isinstance(contents, dict)
    assert contents["picture.webp"] == webp
