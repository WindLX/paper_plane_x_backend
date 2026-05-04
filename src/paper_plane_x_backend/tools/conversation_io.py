"""Conversation I/O 工具集合.

提供项目文件沙箱的读写能力，供 ResearcherAgent 管理笔记和草稿。
"""

import logging
from pathlib import Path
from typing import Any

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.core.agent_runtime.tooling import tool

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 1024 * 1024  # 1MB
_ALLOWED_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".yaml", ".yml"}


def _build_project_file_shared_guides() -> dict[str, str]:
    return {
        "Project File Editing Guide": "\n".join(
            [
                "优先选择最小修改范围的工具，避免不必要的整文件覆盖。",
                "开始编辑前，先用 list_project_files 了解目录，再用 read_project_file 或 read_project_file_lines 读取上下文。",
                "当你只需要定位标题、变量名、段落锚点或旧文本时，优先使用 find_in_project_file。",
                "当修改目标已经明确到行号范围时，优先使用 replace_project_file_lines。",
                "当旧文本块稳定且你希望校验唯一性时，优先使用 replace_project_file_text。",
                "当你围绕一个锚点文本插入、删除或替换内容时，优先使用 patch_project_file。",
                "只有在你准备重写整个文件，或者内容本来就需要整体生成时，才使用 write_project_file。",
                "replace_project_file_text 和 patch_project_file 默认都要求精确出现次数匹配；如果命中数量不对，应先重新查找定位，而不是盲改。",
                "按行工具的行号是 1-based，end_line 为包含端点。",
                f"文件必须位于项目沙箱内，扩展名仅允许：{', '.join(sorted(_ALLOWED_EXTENSIONS))}。",
                f"单文件大小上限为 {MAX_FILE_SIZE} bytes；超大文件不适合直接读写。",
            ]
        )
    }


def resolve_sandbox_path(project_id: str, file_path: str) -> Path:
    """解析并验证文件路径，确保不逃逸沙箱.

    Args:
        project_id: 项目 ID
        file_path: 相对路径（以 / 开头表示项目根目录）

    Returns:
        Path: 绝对路径

    Raises:
        ValueError: 路径非法或试图逃逸沙箱
    """
    if not project_id:
        raise ValueError("project_id is required")

    # 规范化路径，去除开头的 /
    clean_path = file_path.lstrip("/")
    if not clean_path:
        raise ValueError("file_path cannot be empty")

    # 检查路径遍历
    if ".." in clean_path.split("/"):
        raise ValueError(f"Path traversal not allowed: {file_path}")

    sandbox_root = settings.data_dir / "projects" / project_id
    target = (sandbox_root / clean_path).resolve()
    resolved_root = sandbox_root.resolve()

    if not str(target).startswith(str(resolved_root)):
        raise ValueError(f"Path escapes sandbox: {file_path}")

    # 检查扩展名
    if target.suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File extension '{target.suffix}' not allowed. Allowed: {', '.join(_ALLOWED_EXTENSIONS)}"
        )

    return target


def _read_project_text_file(project_id: str, file_path: str) -> tuple[Path, str]:
    target = resolve_sandbox_path(project_id, file_path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if target.is_dir():
        raise IsADirectoryError(f"Path is a directory: {file_path}")
    if target.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"File too large (>{MAX_FILE_SIZE} bytes): {file_path}")
    return target, target.read_text(encoding="utf-8")


def _write_project_text_file(target: Path, content: str) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    return target.write_text(content, encoding="utf-8")


@tool(
    name="read_project_file",
    description=(
        "读取项目文件沙箱中的文件内容。"
        "适用场景：查看已保存的笔记、草稿或项目数据文件。"
        "\n输入：file_path（相对路径，如 /notes/idea.md）。"
        "\n输出：成功时返回 {content}；失败时返回 {error}。"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_project_file_shared_guides(),
)
def read_project_file(
    file_path: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """读取项目文件."""
    try:
        _, content = _read_project_text_file(project_id or "", file_path)
        return {"content": content}
    except (ValueError, FileNotFoundError, IsADirectoryError) as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception("event=read_project_file.error file_path=%s", file_path)
        return {"error": f"Read failed: {exc}"}


@tool(
    name="write_project_file",
    description=(
        "向项目文件沙箱写入文件内容。若文件已存在则覆盖。"
        "适用场景：保存笔记、草稿、中间结果或项目配置。"
        "\n输入：file_path（相对路径，如 /notes/idea.md），content（文件内容）。"
        "\n输出：成功时返回 {file_path, bytes_written}；失败时返回 {error}。"
        "\n说明：支持扩展名: .md, .txt, .json, .csv, .yaml, .yml"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_project_file_shared_guides(),
)
def write_project_file(
    file_path: str,
    content: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """写入项目文件."""
    try:
        target = resolve_sandbox_path(project_id or "", file_path)
        bytes_written = _write_project_text_file(target, content)
        logger.info(
            "event=write_project_file.ok project_id=%s file_path=%s bytes=%s",
            project_id,
            file_path,
            bytes_written,
        )
        return {"file_path": file_path, "bytes_written": bytes_written}
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception("event=write_project_file.error file_path=%s", file_path)
        return {"error": f"Write failed: {exc}"}


@tool(
    name="read_project_file_lines",
    description=(
        "按行号读取项目文件的局部内容。"
        "适用场景：先查看目标段落，再决定是否编辑。"
        "\n输入：file_path，start_line（1-based），end_line（含，默认等于 start_line）。"
        "\n输出：成功时返回 {file_path, start_line, end_line, total_lines, lines}；失败时返回 {error}。"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_project_file_shared_guides(),
)
def read_project_file_lines(
    file_path: str,
    start_line: int,
    end_line: int | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    try:
        _, content = _read_project_text_file(project_id or "", file_path)
        lines = content.splitlines()
        total_lines = len(lines)
        resolved_end_line = end_line if end_line is not None else start_line
        if start_line < 1 or resolved_end_line < start_line:
            return {"error": "Invalid line range"}
        if start_line > total_lines:
            return {
                "error": f"start_line out of range: {start_line} > {total_lines}"
            }

        selected = []
        for index in range(start_line, min(resolved_end_line, total_lines) + 1):
            selected.append(
                {
                    "line_no": index,
                    "text": lines[index - 1],
                }
            )
        return {
            "file_path": file_path,
            "start_line": start_line,
            "end_line": min(resolved_end_line, total_lines),
            "total_lines": total_lines,
            "lines": selected,
        }
    except (ValueError, FileNotFoundError, IsADirectoryError) as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception("event=read_project_file_lines.error file_path=%s", file_path)
        return {"error": f"Read lines failed: {exc}"}


@tool(
    name="find_in_project_file",
    description=(
        "在项目文件中查找指定文本并返回命中行号。"
        "适用场景：定位某个标题、变量名、段落锚点或旧文本。"
        "\n输入：file_path，query，以及可选 case_sensitive、max_matches。"
        "\n输出：成功时返回 {file_path, query, total_matches, matches}；失败时返回 {error}。"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_project_file_shared_guides(),
)
def find_in_project_file(
    file_path: str,
    query: str,
    case_sensitive: bool = False,
    max_matches: int = 20,
    project_id: str | None = None,
) -> dict[str, Any]:
    try:
        if not query:
            return {"error": "query cannot be empty"}
        _, content = _read_project_text_file(project_id or "", file_path)
        haystack_lines = content.splitlines()
        needle = query if case_sensitive else query.lower()
        total_matches = 0
        matches: list[dict[str, Any]] = []

        for line_no, line in enumerate(haystack_lines, start=1):
            search_line = line if case_sensitive else line.lower()
            start = 0
            while True:
                index = search_line.find(needle, start)
                if index < 0:
                    break
                total_matches += 1
                if len(matches) < max_matches:
                    matches.append(
                        {
                            "line_no": line_no,
                            "start_col": index + 1,
                            "end_col": index + len(query),
                            "text": line,
                        }
                    )
                start = index + max(1, len(needle))

        return {
            "file_path": file_path,
            "query": query,
            "total_matches": total_matches,
            "matches": matches,
        }
    except (ValueError, FileNotFoundError, IsADirectoryError) as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception("event=find_in_project_file.error file_path=%s", file_path)
        return {"error": f"Find failed: {exc}"}


@tool(
    name="replace_project_file_lines",
    description=(
        "按行号区间替换项目文件中的文本。"
        "适用场景：已知要改的行范围时，进行小范围、可控的更新。"
        "\n输入：file_path，start_line，end_line（含），new_text。"
        "\n输出：成功时返回 {file_path, start_line, end_line, lines_replaced, bytes_written}；失败时返回 {error}。"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_project_file_shared_guides(),
)
def replace_project_file_lines(
    file_path: str,
    start_line: int,
    end_line: int,
    new_text: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    try:
        target, content = _read_project_text_file(project_id or "", file_path)
        lines = content.splitlines()
        total_lines = len(lines)
        if start_line < 1 or end_line < start_line:
            return {"error": "Invalid line range"}
        if end_line > total_lines:
            return {"error": f"end_line out of range: {end_line} > {total_lines}"}

        replacement_lines = new_text.splitlines()
        updated_lines = [
            *lines[: start_line - 1],
            *replacement_lines,
            *lines[end_line:],
        ]
        updated_content = "\n".join(updated_lines)
        if content.endswith("\n"):
            updated_content += "\n"

        bytes_written = _write_project_text_file(target, updated_content)
        return {
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "lines_replaced": end_line - start_line + 1,
            "bytes_written": bytes_written,
        }
    except (ValueError, FileNotFoundError, IsADirectoryError) as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception(
            "event=replace_project_file_lines.error file_path=%s", file_path
        )
        return {"error": f"Replace lines failed: {exc}"}


@tool(
    name="replace_project_file_text",
    description=(
        "按精确旧文本替换项目文件中的内容。"
        "适用场景：当旧文本稳定且希望避免按整文件覆盖时。"
        "\n输入：file_path，old_text，new_text，以及可选 replace_all、expected_occurrences。"
        "\n输出：成功时返回 {file_path, replacements, bytes_written}；失败时返回 {error}。"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_project_file_shared_guides(),
)
def replace_project_file_text(
    file_path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
    expected_occurrences: int = 1,
    project_id: str | None = None,
) -> dict[str, Any]:
    try:
        if not old_text:
            return {"error": "old_text cannot be empty"}
        target, content = _read_project_text_file(project_id or "", file_path)
        occurrences = content.count(old_text)
        if occurrences == 0:
            return {"error": "old_text not found"}
        if not replace_all and occurrences != expected_occurrences:
            return {
                "error": (
                    f"Expected {expected_occurrences} occurrence(s), found {occurrences}. "
                    "Set replace_all=true or adjust expected_occurrences."
                )
            }

        replacements = occurrences if replace_all else expected_occurrences
        updated_content = (
            content.replace(old_text, new_text)
            if replace_all
            else content.replace(old_text, new_text, expected_occurrences)
        )
        bytes_written = _write_project_text_file(target, updated_content)
        return {
            "file_path": file_path,
            "replacements": replacements,
            "bytes_written": bytes_written,
        }
    except (ValueError, FileNotFoundError, IsADirectoryError) as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception(
            "event=replace_project_file_text.error file_path=%s", file_path
        )
        return {"error": f"Replace text failed: {exc}"}


@tool(
    name="patch_project_file",
    description=(
        "基于锚点文本对项目文件做 patch 式更新。"
        "适用场景：围绕已知文本块执行 replace、insert_before、insert_after、delete。"
        "\n输入：file_path，action，anchor_text，content，以及可选 expected_occurrences。"
        "\n输出：成功时返回 {file_path, action, occurrences, bytes_written}；失败时返回 {error}。"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_project_file_shared_guides(),
)
def patch_project_file(
    file_path: str,
    action: str,
    anchor_text: str,
    content: str = "",
    expected_occurrences: int = 1,
    project_id: str | None = None,
) -> dict[str, Any]:
    try:
        if not anchor_text:
            return {"error": "anchor_text cannot be empty"}
        if action not in {"replace", "insert_before", "insert_after", "delete"}:
            return {
                "error": "action must be one of: replace, insert_before, insert_after, delete"
            }

        target, original = _read_project_text_file(project_id or "", file_path)
        occurrences = original.count(anchor_text)
        if occurrences != expected_occurrences:
            return {
                "error": (
                    f"Expected {expected_occurrences} occurrence(s) of anchor_text, "
                    f"found {occurrences}"
                )
            }

        if action == "replace":
            updated = original.replace(anchor_text, content, expected_occurrences)
        elif action == "insert_before":
            updated = original.replace(
                anchor_text,
                f"{content}{anchor_text}",
                expected_occurrences,
            )
        elif action == "insert_after":
            updated = original.replace(
                anchor_text,
                f"{anchor_text}{content}",
                expected_occurrences,
            )
        else:
            updated = original.replace(anchor_text, "", expected_occurrences)

        bytes_written = _write_project_text_file(target, updated)
        return {
            "file_path": file_path,
            "action": action,
            "occurrences": occurrences,
            "bytes_written": bytes_written,
        }
    except (ValueError, FileNotFoundError, IsADirectoryError) as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception("event=patch_project_file.error file_path=%s", file_path)
        return {"error": f"Patch failed: {exc}"}


@tool(
    name="list_project_files",
    description=(
        "列出项目文件沙箱中的文件和目录。"
        "适用场景：浏览项目文件结构，查找已有笔记或草稿。"
        "\n输入：dir_path（相对目录路径，默认为 /）。"
        "\n输出：成功时返回 {items: [{name, is_dir, size}]}；失败时返回 {error}。"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_project_file_shared_guides(),
)
def list_project_files(
    dir_path: str = "/",
    project_id: str | None = None,
) -> dict[str, Any]:
    """列出项目文件."""
    try:
        sandbox_root = settings.data_dir / "projects" / (project_id or "")
        target = (sandbox_root / dir_path.lstrip("/")).resolve()
        resolved_root = sandbox_root.resolve()

        if not str(target).startswith(str(resolved_root)):
            return {"error": f"Path escapes sandbox: {dir_path}"}

        if not target.exists():
            return {"error": f"Directory not found: {dir_path}"}
        if not target.is_dir():
            return {"error": f"Path is not a directory: {dir_path}"}

        items: list[dict[str, Any]] = []
        for child in sorted(target.iterdir()):
            try:
                size = child.stat().st_size if child.is_file() else None
            except OSError:
                size = None
            items.append(
                {
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": size,
                }
            )
        return {"items": items}
    except Exception as exc:
        logger.exception("event=list_project_files.error dir_path=%s", dir_path)
        return {"error": f"List failed: {exc}"}


@tool(
    name="remove_project_file",
    description=(
        "删除项目文件沙箱中的文件或空目录。"
        "适用场景：清理不再需要的草稿或临时文件。"
        "\n输入：file_path（相对路径）。"
        "\n输出：成功时返回 {removed}；失败时返回 {error}。"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_project_file_shared_guides(),
)
def remove_project_file(
    file_path: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """删除项目文件."""
    try:
        target = resolve_sandbox_path(project_id or "", file_path)
        if not target.exists():
            return {"error": f"File not found: {file_path}"}
        if target.is_dir():
            target.rmdir()  # 只允许删除空目录
        else:
            target.unlink()
        logger.info(
            "event=remove_project_file.ok project_id=%s file_path=%s",
            project_id,
            file_path,
        )
        return {"removed": file_path}
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception("event=remove_project_file.error file_path=%s", file_path)
        return {"error": f"Remove failed: {exc}"}
