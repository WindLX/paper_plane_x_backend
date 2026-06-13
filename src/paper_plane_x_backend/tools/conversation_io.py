"""Conversation I/O 工具集合.

提供项目文件沙箱的读写能力，供 ResearcherAgent 管理笔记和草稿。
"""

import logging
from typing import Any, Callable

from paper_plane_x_backend.core.agent_runtime.tooling import tool
from paper_plane_x_backend.services.project.files import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    ProjectFileError,
    get_project_file_manager,
)

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = ALLOWED_EXTENSIONS


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


def _tool_error(exc: ProjectFileError) -> dict[str, Any]:
    return {"error": exc.message}


def _run_project_file_operation(
    operation: Callable[[], dict[str, object]],
    *,
    event: str,
    failure_prefix: str,
    file_path: str | None = None,
) -> dict[str, Any]:
    try:
        return dict(operation())
    except ProjectFileError as exc:
        return _tool_error(exc)
    except Exception as exc:
        if file_path is None:
            logger.exception("event=%s.error", event)
        else:
            logger.exception("event=%s.error file_path=%s", event, file_path)
        return {"error": f"{failure_prefix}: {exc}"}


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

    def _operation() -> dict[str, object]:
        payload = get_project_file_manager().read_file(project_id or "", file_path)
        return {"content": payload["content"]}

    return _run_project_file_operation(
        _operation,
        event="read_project_file",
        failure_prefix="Read failed",
        file_path=file_path,
    )


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

    def _operation() -> dict[str, object]:
        payload = get_project_file_manager().write_file(
            project_id or "",
            file_path,
            content,
        )
        logger.info(
            "event=write_project_file.ok project_id=%s file_path=%s bytes=%s",
            project_id,
            file_path,
            payload["bytes_written"],
        )
        return {
            "file_path": payload["file_path"],
            "bytes_written": payload["bytes_written"],
        }

    return _run_project_file_operation(
        _operation,
        event="write_project_file",
        failure_prefix="Write failed",
        file_path=file_path,
    )


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
    return _run_project_file_operation(
        lambda: get_project_file_manager().read_file_lines(
            project_id or "",
            file_path,
            start_line,
            end_line,
        ),
        event="read_project_file_lines",
        failure_prefix="Read lines failed",
        file_path=file_path,
    )


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
    return _run_project_file_operation(
        lambda: get_project_file_manager().find_in_file(
            project_id or "",
            file_path,
            query,
            case_sensitive=case_sensitive,
            max_matches=max_matches,
        ),
        event="find_in_project_file",
        failure_prefix="Find failed",
        file_path=file_path,
    )


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
    return _run_project_file_operation(
        lambda: get_project_file_manager().replace_file_lines(
            project_id or "",
            file_path,
            start_line,
            end_line,
            new_text,
        ),
        event="replace_project_file_lines",
        failure_prefix="Replace lines failed",
        file_path=file_path,
    )


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
    return _run_project_file_operation(
        lambda: get_project_file_manager().replace_file_text(
            project_id or "",
            file_path,
            old_text,
            new_text,
            replace_all=replace_all,
            expected_occurrences=expected_occurrences,
        ),
        event="replace_project_file_text",
        failure_prefix="Replace text failed",
        file_path=file_path,
    )


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
    return _run_project_file_operation(
        lambda: get_project_file_manager().patch_file(
            project_id or "",
            file_path,
            action,
            anchor_text,
            content,
            expected_occurrences=expected_occurrences,
        ),
        event="patch_project_file",
        failure_prefix="Patch failed",
        file_path=file_path,
    )


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
    return _run_project_file_operation(
        lambda: get_project_file_manager().list_files(project_id or "", dir_path),
        event="list_project_files",
        failure_prefix="List failed",
        file_path=dir_path,
    )


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
    return _run_project_file_operation(
        lambda: get_project_file_manager().remove_path(project_id or "", file_path),
        event="remove_project_file",
        failure_prefix="Remove failed",
        file_path=file_path,
    )
