import subprocess
from pathlib import Path
from typing import Any

from paper_plane_x_backend.services import pandoc
from paper_plane_x_backend.services.app_settings import get_app_settings_repo
from paper_plane_x_backend.services.pandoc import _ensure_pandoc, convert_markdown


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
    captured: dict[str, list[str]] = {}
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
    ) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
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
    assert result.startswith(b"%PDF")
    assert cmd[cmd.index("--pdf-engine") + 1] == str(pdf_engine)
