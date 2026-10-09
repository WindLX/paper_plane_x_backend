import os
import subprocess
from pathlib import Path
from typing import Any

from paper_plane_x_backend.services import pandoc
from paper_plane_x_backend.services.app_settings import get_app_settings_repo
from paper_plane_x_backend.services.pandoc import (
    _ensure_pandoc,
    collect_image_references,
    convert_markdown,
    rewrite_image_references,
)


def test_ensure_pandoc_uses_configured_path(tmp_path: Path) -> None:
    pandoc = tmp_path / "pandoc"
    pandoc.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pandoc.chmod(0o755)

    repo = get_app_settings_repo()
    repo.update_pandoc({"pandoc_path": str(pandoc)})
    try:
        assert _ensure_pandoc() == str(pandoc)
    finally:
        repo.update_pandoc({"pandoc_path": None})


def test_convert_markdown_html_uses_pandoc_builtin_template(
    monkeypatch: Any,
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(
        cmd: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: int,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        output_file = Path(cmd[cmd.index("-o") + 1])
        output_file.write_text("<!DOCTYPE html><title>Note</title>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(pandoc, "_ensure_pandoc", lambda: "/usr/bin/pandoc")
    monkeypatch.setattr(pandoc.subprocess, "run", fake_run)

    result = convert_markdown("# Hello", "html", title="Note")

    cmd = captured["cmd"]
    assert result.startswith(b"<!DOCTYPE html>")
    assert "--standalone" in cmd
    assert cmd[cmd.index("-t") + 1] == "html"
    assert ["--metadata", "title=Note"] == cmd[-2:]
    assert "--template" not in cmd
    assert "--css" not in cmd


def test_convert_markdown_html_uses_configured_template(
    monkeypatch: Any,
) -> None:
    captured: dict[str, list[str]] = {}
    repo = get_app_settings_repo()
    repo.update_pandoc({"html_template": "/templates/article.html"})

    def fake_run(
        cmd: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: int,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        output_file = Path(cmd[cmd.index("-o") + 1])
        output_file.write_text("<!DOCTYPE html><title>Note</title>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(pandoc, "_ensure_pandoc", lambda: "/usr/bin/pandoc")
    monkeypatch.setattr(pandoc.subprocess, "run", fake_run)

    try:
        convert_markdown("# Hello", "html", title="Note")
    finally:
        repo.update_pandoc({"html_template": None})

    cmd = captured["cmd"]
    assert cmd[cmd.index("--template") + 1] == "/templates/article.html"


def test_convert_markdown_pdf_uses_configured_engine(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    pdf_engine = tmp_path / "pdf-engine"
    pdf_engine.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pdf_engine.chmod(0o755)
    repo = get_app_settings_repo()
    repo.update_pandoc({"pdf_engine": str(pdf_engine)})

    def fake_run(
        cmd: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: int,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        captured["engine_path"] = kwargs["env"]["PATH"].split(os.pathsep)[0]
        output_file = Path(cmd[cmd.index("-o") + 1])
        output_file.write_bytes(b"%PDF-1.7")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(pandoc, "_ensure_pandoc", lambda: "/usr/bin/pandoc")
    monkeypatch.setattr(pandoc.subprocess, "run", fake_run)

    try:
        result = convert_markdown("# Hello", "pdf", title="Note")
    finally:
        repo.update_pandoc({"pdf_engine": None})

    cmd = captured["cmd"]
    assert captured["engine_path"] == str(pdf_engine.parent)
    assert result.startswith(b"%PDF")
    assert cmd[cmd.index("--pdf-engine") + 1] == pdf_engine.name


_REFERENCE_MARKDOWN = (
    "![a](images/a.png)\n"
    "\n"
    '<img src="images/b.png" alt="b">\n'
    "\n"
    '<img alt="c" src="images/c.png"/>\n'
    "\n"
    "![d][ref]\n"
    "\n"
    "[ref]: ../shared/d.png\n"
    "\n"
    "```\n"
    "![code](images/code.png)\n"
    "```\n"
    "\n"
    "`![inline](images/inline.png)`\n"
)


def test_collect_image_references_covers_markdown_and_html() -> None:
    assert collect_image_references(_REFERENCE_MARKDOWN) == [
        "images/a.png",
        "images/b.png",
        "images/c.png",
        "../shared/d.png",
    ]


def test_rewrite_image_references_matches_decoded_paths() -> None:
    text = (
        "![a](<图片/图 一.png>)\n"
        "\n"
        '<img src="图片/图 一.png">\n'
        "\n"
        "```\n"
        "![a](图片/图 一.png)\n"
        "```\n"
    )

    rewritten = rewrite_image_references(text, {"图片/图 一.png": "assets/pic.png"})

    assert rewritten == (
        "![a](<assets/pic.png>)\n"
        "\n"
        '<img src="assets/pic.png">\n'
        "\n"
        "```\n"
        "![a](图片/图 一.png)\n"
        "```\n"
    )


def test_rewrite_image_references_returns_original_without_matches() -> None:
    assert rewrite_image_references(_REFERENCE_MARKDOWN, {}) == _REFERENCE_MARKDOWN
    assert rewrite_image_references(_REFERENCE_MARKDOWN, {"other.png": "x.png"}) == (
        _REFERENCE_MARKDOWN
    )


def test_rewrite_image_references_updates_link_definitions() -> None:
    text = "![d][ref]\n\n[ref]: /assets/d.png\n"

    rewritten = rewrite_image_references(text, {"/assets/d.png": "assets/d.png"})

    assert rewritten == "![d][ref]\n\n[ref]: assets/d.png\n"


def test_convert_markdown_stages_resources_in_workdir(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        cmd: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: int,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        captured["env"] = kwargs.get("env")
        output_file = Path(cmd[cmd.index("-o") + 1])
        output_file.write_text("<!DOCTYPE html>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(pandoc, "_ensure_pandoc", lambda: "/usr/bin/pandoc")
    monkeypatch.setattr(pandoc.subprocess, "run", fake_run)

    result = convert_markdown(
        "# Hi\n\n![a](assets/a.png)\n",
        "html",
        title="Note",
        workdir=tmp_path,
        input_relative_path="notes/draft.md",
        embed_resources=True,
    )

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert "--embed-resources" in cmd
    assert cmd[1] == str(tmp_path / "notes" / "draft.md")
    assert (tmp_path / "notes" / "draft.md").read_text(encoding="utf-8") == (
        "# Hi\n\n![a](assets/a.png)\n"
    )
    assert captured["cwd"] == tmp_path / "notes"
    assert captured["env"] is None  # Inherit the user's converter environment.
    assert cmd[cmd.index("--resource-path") + 1] == str(tmp_path / "notes")
    assert cmd[-2:] == ["--metadata", "title=Note"]
    assert result == b"<!DOCTYPE html>"
