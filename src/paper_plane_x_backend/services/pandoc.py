"""Pandoc 文档转换服务.

调用系统 pandoc 命令将 markdown 转换为其他格式（docx, pdf, html）。
同时提供导出前的 markdown 图片引用解析，用于定位并重写项目沙箱内的资源路径。
"""

import logging
import os
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Literal, Mapping
from urllib.parse import quote, unquote

from markdown_it import MarkdownIt
from markdown_it.token import Token

logger = logging.getLogger(__name__)

_MARKDOWN = MarkdownIt("commonmark")

# 括号与空格会被百分号编码，避免在 markdown 目标或 HTML 属性里截断 URL。
_URL_QUOTE_SAFE = "/-._~#?&=:@!$'*+,;"

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
    return str(configured.absolute())


def _anchor_relative_path(value: str) -> str:
    """把相对文件路径固定到当前进程工作目录.

    pandoc 转换会切换到暂存目录执行，配置里的相对路径需要先锚定，否则解析基准会漂移。
    模板名（如 ``default``）与 URL 原样返回。
    """
    if value.startswith(("http://", "https://")):
        return value
    if "/" not in value and "\\" not in value:
        return value
    path = Path(value)
    if path.is_absolute():
        return value
    return str(path.absolute())


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
    *,
    workdir: Path | None = None,
    input_relative_path: str = "input.md",
    embed_resources: bool = False,
) -> bytes:
    """将 markdown 内容转换为指定格式.

    Args:
        content: markdown 内容
        output_format: 目标格式
        title: 文档标题（用于 pdf 元数据）
        workdir: 转换工作目录，调用方可在其中暂存 markdown 引用的资源；为空时新建临时目录
        input_relative_path: markdown 在 workdir 中的相对路径，决定相对资源的解析基准
        embed_resources: html 导出时是否把资源内联为 data URI

    Returns:
        bytes: 转换后的文件内容

    Raises:
        RuntimeError: pandoc 不可用或转换失败
    """
    if workdir is None:
        with tempfile.TemporaryDirectory() as tmpdir:
            return _convert_markdown_in_workdir(
                content,
                output_format,
                title,
                Path(tmpdir),
                input_relative_path,
                embed_resources,
            )
    return _convert_markdown_in_workdir(
        content,
        output_format,
        title,
        workdir,
        input_relative_path,
        embed_resources,
    )


def _convert_markdown_in_workdir(
    content: str,
    output_format: ExportFormat,
    title: str | None,
    workdir: Path,
    input_relative_path: str,
    embed_resources: bool,
) -> bytes:
    pandoc_path = _ensure_pandoc()
    target_format = _PANDOC_FORMAT_MAP[output_format]
    from paper_plane_x_backend.services.app_settings import get_app_settings_repo

    pandoc_config = get_app_settings_repo().get().pandoc

    input_file = workdir / input_relative_path
    output_file = workdir / f"output.{_EXTENSION_MAP[output_format]}"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    input_file.write_text(content, encoding="utf-8")

    # pandoc 的相对资源路径以工作目录为基准；切到 markdown 所在目录，
    # 暂存资源就能按 markdown 里的相对写法被找到。
    working_directory = input_file.parent

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
        "--resource-path",
        str(working_directory),
    ]

    if embed_resources:
        cmd.append("--embed-resources")

    execution_env: dict[str, str] | None = None
    if output_format == "pdf":
        pdf_engine = _ensure_pdf_engine()
        if not pdf_engine:
            raise RuntimeError(
                "No PDF engine available. Please install typst, weasyprint, "
                "wkhtmltopdf, xelatex, pdflatex, lualatex, or configure "
                "pandoc.pdf_engine in settings."
            )
        # Pandoc selects its PDF pipeline by command name. An absolute Typst
        # path takes the generic pipeline, which emits unusable media paths.
        # Prepend the configured binary directory so the recognized name still
        # executes that exact binary, without widening Typst's filesystem root.
        engine_path = Path(pdf_engine)
        if engine_path.is_absolute():
            execution_env = os.environ.copy()
            execution_env["PATH"] = (
                str(engine_path.parent) + os.pathsep + execution_env.get("PATH", "")
            )
        cmd.extend(["--pdf-engine", engine_path.name])
        if title:
            cmd.extend(["--metadata", f"title={title}"])

    if output_format == "html" and pandoc_config.html_template:
        cmd.extend(["--template", _anchor_relative_path(pandoc_config.html_template)])

    if title and output_format in ("docx", "html"):
        cmd.extend(["--metadata", f"title={title}"])

    try:
        _result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
            cwd=working_directory,
            env=execution_env,
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


class ExportResourceMarkupError(Exception):
    """A document requests resources other than its validated project images."""

    def __init__(self, reference: str) -> None:
        super().__init__(f"Unsupported external or active resource: {reference}")
        self.reference = reference


def get_content_type(output_format: ExportFormat) -> str:
    """获取导出格式的 Content-Type."""
    return _CONTENT_TYPE_MAP[output_format]


def get_extension(output_format: ExportFormat) -> str:
    """获取导出格式的文件扩展名."""
    return _EXTENSION_MAP[output_format]


class _HtmlImageSourceCollector(HTMLParser):
    """从 HTML 片段中收集 <img> 的 src 引用。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []
        self.in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        from paper_plane_x_backend.services.project.images import (
            ImageValidationError,
            validate_self_contained_css,
        )

        if tag.lower() in {
            "script",
            "iframe",
            "object",
            "embed",
            "link",
            "video",
            "audio",
            "source",
        }:
            raise ExportResourceMarkupError(f"<{tag}>")
        self.in_style = tag.lower() == "style"
        for name, value in attrs:
            if name.lower() == "srcset":
                raise ExportResourceMarkupError(f"srcset={value}")
            if name.lower() == "style" and value:
                try:
                    validate_self_contained_css(value)
                except ImageValidationError as exc:
                    raise ExportResourceMarkupError(value) from exc
        if tag.lower() != "img":
            return
        for name, value in attrs:
            if name.lower() == "src" and value:
                self.sources.append(value)
                return

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        from paper_plane_x_backend.services.project.images import (
            ImageValidationError,
            validate_self_contained_css,
        )

        if self.in_style:
            try:
                validate_self_contained_css(data)
            except ImageValidationError as exc:
                raise ExportResourceMarkupError(data) from exc


def _extract_html_image_sources(fragment: str) -> list[str]:
    collector = _HtmlImageSourceCollector()
    collector.feed(fragment)
    collector.close()
    return collector.sources


def collect_image_references(text: str) -> list[str]:
    """按出现顺序收集 markdown 与 HTML 中的图片引用.

    使用 markdown-it 解析 markdown 图片语法，因此代码块与行内代码中的 ``![]()`` 不会被误判；
    HTML ``<img>`` 通过 HTMLParser 解析。返回的是 markdown-it 规范化后的原始引用字符串。
    """
    references: list[str] = []
    seen: set[str] = set()

    def _add(source: str | None) -> None:
        if not source or source in seen:
            return
        seen.add(source)
        references.append(source)

    for token in _MARKDOWN.parse(text, {}):
        if token.type == "inline":
            for child in token.children or []:
                if child.type == "image":
                    source = child.attrGet("src")
                    if isinstance(source, str):
                        _add(source)
                elif child.type == "html_inline":
                    for source in _extract_html_image_sources(child.content):
                        _add(source)
        elif token.type == "html_block":
            for source in _extract_html_image_sources(token.content):
                _add(source)
    return references


def rewrite_image_references(text: str, replacements: Mapping[str, str]) -> str:
    """把命中替换表的图片引用改写为新的相对路径.

    替换表以解码后的引用为键，因此原始 markdown 中带百分号编码、中文或空格路径都能命中；
    代码块内的行不会被改写。
    """
    if not replacements:
        return text
    lookup = {unquote(key): value for key, value in replacements.items()}
    protected = _protected_line_numbers(_MARKDOWN.parse(text, {}))
    lines = text.splitlines(keepends=True)
    return "".join(
        line if index in protected else _rewrite_line(line, lookup)
        for index, line in enumerate(lines, start=1)
    )


def _protected_line_numbers(tokens: Iterable[Token]) -> set[int]:
    protected: set[int] = set()
    for token in tokens:
        if token.type in ("fence", "code_block") and token.map:
            start, end = token.map
            protected.update(range(start + 1, end + 1))
    return protected


def _rewrite_line(line: str, lookup: Mapping[str, str]) -> str:
    spans = _find_image_url_spans(line)
    if not spans:
        return line
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        replacement = lookup.get(unquote(line[start:end]))
        if replacement is None:
            continue
        pieces.append(line[cursor:start])
        pieces.append(quote(replacement, safe=_URL_QUOTE_SAFE))
        cursor = end
    if not pieces:
        return line
    pieces.append(line[cursor:])
    return "".join(pieces)


def _find_image_url_spans(line: str) -> list[tuple[int, int]]:
    spans = _markdown_destination_spans(line)
    spans.extend(_reference_definition_spans(line))
    spans.extend(_html_image_src_spans(line))
    spans.sort()
    return spans


def _reference_definition_spans(line: str) -> list[tuple[int, int]]:
    """匹配 ``[label]: url`` 形式的引用定义目标，覆盖引用式图片语法。"""
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > 3 or not stripped.startswith("["):
        return []
    label_end = stripped.find("]:")
    if label_end < 0:
        return []
    index = indent + label_end + 2
    while index < len(line) and line[index] in " \t":
        index += 1
    if index >= len(line):
        return []
    if line[index] == "<":
        end = line.find(">", index + 1)
        return [(index + 1, end)] if end > index else []
    end = index
    while end < len(line) and not line[end].isspace():
        end += 1
    return [(index, end)] if end > index else []


def _markdown_destination_spans(line: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    while True:
        start = line.find("![", cursor)
        if start < 0:
            return spans
        label_end = line.find("]", start + 2)
        if label_end < 0:
            return spans
        if label_end + 1 >= len(line) or line[label_end + 1] != "(":
            cursor = start + 2
            continue
        index = label_end + 2
        while index < len(line) and line[index] in " \t":
            index += 1
        if index < len(line) and line[index] == "<":
            end = line.find(">", index + 1)
            if end < 0:
                return spans
            spans.append((index + 1, end))
            cursor = end + 1
            continue
        end = index
        depth = 0
        while end < len(line):
            char = line[end]
            if char in " \t":
                break
            if char == "\\":
                end += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            end += 1
        if end > index:
            spans.append((index, end))
        cursor = end + 1


def _html_image_src_spans(line: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    lowered = line.lower()
    cursor = 0
    while True:
        start = lowered.find("<img", cursor)
        if start < 0:
            return spans
        tag_end = line.find(">", start + 4)
        if tag_end < 0:
            return spans
        span = _html_src_span(line, start, tag_end)
        if span is not None:
            spans.append(span)
        cursor = tag_end + 1


def _html_src_span(line: str, tag_start: int, tag_end: int) -> tuple[int, int] | None:
    region = line[tag_start:tag_end]
    lowered = region.lower()
    cursor = 4
    while True:
        index = lowered.find("src", cursor)
        if index < 0:
            return None
        before = lowered[index - 1]
        after = lowered[index + 3] if index + 3 < len(region) else ""
        if before.isspace() and after in ("=", " ", "\t"):
            equal = lowered.find("=", index + 3)
            if equal < 0:
                return None
            value_start = equal + 1
            while value_start < len(region) and region[value_start] in " \t":
                value_start += 1
            if value_start >= len(region):
                return None
            quote_char = region[value_start]
            if quote_char in ('"', "'"):
                value_end = line.find(quote_char, tag_start + value_start + 1, tag_end)
                if value_end < 0:
                    return None
                return (tag_start + value_start + 1, value_end)
            value_end = value_start
            while value_end < len(region) and not region[value_end].isspace():
                value_end += 1
            return (tag_start + value_start, tag_start + value_end)
        cursor = index + 3
