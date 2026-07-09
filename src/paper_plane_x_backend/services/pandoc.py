"""Pandoc 文档转换服务.

调用系统 pandoc 命令将 markdown 转换为其他格式（docx, pdf, html）。
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

ExportFormat = Literal["markdown", "docx", "pdf", "html"]

_PANDOC_FORMAT_MAP: dict[ExportFormat, str] = {
    "markdown": "markdown",
    "docx": "docx",
    "pdf": "pdf",
    "html": "html",
}

_CONTENT_TYPE_MAP: dict[ExportFormat, str] = {
    "markdown": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html; charset=utf-8",
}

_EXTENSION_MAP: dict[ExportFormat, str] = {
    "markdown": "md",
    "docx": "docx",
    "pdf": "pdf",
    "html": "html",
}


def _resolve_command(command: str, label: str) -> str:
    """解析命令名或可执行文件路径."""
    command = command.strip()
    configured = Path(command).expanduser()
    if command == configured.name:
        resolved = shutil.which(command)
        if resolved:
            return resolved
        raise RuntimeError(f"configured {label} command not found: {command}")

    if not configured.is_file():
        raise RuntimeError(f"configured {label} path does not exist: {configured}")
    if not os.access(configured, os.X_OK):
        raise RuntimeError(f"configured {label} path is not executable: {configured}")
    return str(configured)


def _ensure_pandoc() -> str:
    """检查 pandoc 是否可用并返回路径."""
    from paper_plane_x_backend.services.app_settings import get_app_settings_repo

    configured_path = get_app_settings_repo().get().pandoc.pandoc_path
    if configured_path:
        return _resolve_command(configured_path, "pandoc")

    pandoc_path = shutil.which("pandoc")
    if not pandoc_path:
        raise RuntimeError("pandoc not found on system")
    return pandoc_path


def _ensure_pdf_engine() -> str | None:
    """检查可用的 PDF 引擎."""
    from paper_plane_x_backend.services.app_settings import get_app_settings_repo

    configured_engine = get_app_settings_repo().get().pandoc.pdf_engine
    if configured_engine:
        return _resolve_command(configured_engine, "PDF engine")

    for engine in (
        "typst",
        "weasyprint",
        "wkhtmltopdf",
        "pagedjs-cli",
        "prince",
        "xelatex",
        "pdflatex",
        "lualatex",
        "tectonic",
    ):
        path = shutil.which(engine)
        if path:
            return engine
    return None


def convert_markdown(
    content: str,
    output_format: ExportFormat,
    title: str | None = None,
) -> bytes:
    """将 markdown 内容转换为指定格式.

    Args:
        content: markdown 内容
        output_format: 目标格式
        title: 文档标题（用于 pdf 元数据）

    Returns:
        bytes: 转换后的文件内容

    Raises:
        RuntimeError: pandoc 不可用或转换失败
    """
    pandoc_path = _ensure_pandoc()
    target_format = _PANDOC_FORMAT_MAP[output_format]
    from paper_plane_x_backend.services.app_settings import get_app_settings_repo

    pandoc_config = get_app_settings_repo().get().pandoc

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_file = tmp_path / "input.md"
        output_file = tmp_path / f"output.{_EXTENSION_MAP[output_format]}"
        input_file.write_text(content, encoding="utf-8")

        cmd = [
            pandoc_path,
            str(input_file),
            "-f",
            "markdown",
            "-t",
            target_format,
            "-o",
            str(output_file),
            "--standalone",
        ]

        if output_format == "pdf":
            pdf_engine = _ensure_pdf_engine()
            if not pdf_engine:
                raise RuntimeError(
                    "No PDF engine available. Please install typst, weasyprint, "
                    "wkhtmltopdf, xelatex, pdflatex, lualatex, or configure "
                    "pandoc.pdf_engine in settings."
                )
            cmd.extend(["--pdf-engine", pdf_engine])
            if title:
                cmd.extend(["--metadata", f"title={title}"])

        if output_format == "html" and pandoc_config.html_template:
            cmd.extend(["--template", pandoc_config.html_template])

        if title and output_format in ("docx", "html"):
            cmd.extend(["--metadata", f"title={title}"])

        try:
            _result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as exc:
            logger.error(
                "pandoc conversion failed: cmd=%s stderr=%s",
                cmd,
                exc.stderr,
            )
            raise RuntimeError(
                f"Pandoc conversion failed: {exc.stderr or 'unknown error'}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            logger.error("pandoc conversion timeout")
            raise RuntimeError("Pandoc conversion timeout (60s)") from exc

        return output_file.read_bytes()


def get_content_type(output_format: ExportFormat) -> str:
    """获取导出格式的 Content-Type."""
    return _CONTENT_TYPE_MAP[output_format]


def get_extension(output_format: ExportFormat) -> str:
    """获取导出格式的文件扩展名."""
    return _EXTENSION_MAP[output_format]
