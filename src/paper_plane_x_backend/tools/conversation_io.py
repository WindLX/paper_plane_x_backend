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


@tool(
    name="read_project_file",
    description=(
        "读取项目文件沙箱中的文件内容。"
        "适用场景：查看已保存的笔记、草稿或项目数据文件。"
        "\n输入：file_path（相对路径，如 /notes/idea.md）。"
        "\n输出：成功时返回 {content}；失败时返回 {error}。"
    ),
    context_params={"project_id": "project_id"},
)
def read_project_file(
    file_path: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """读取项目文件."""
    try:
        target = resolve_sandbox_path(project_id or "", file_path)
        if not target.exists():
            return {"error": f"File not found: {file_path}"}
        if target.is_dir():
            return {"error": f"Path is a directory: {file_path}"}
        if target.stat().st_size > MAX_FILE_SIZE:
            return {"error": f"File too large (>{MAX_FILE_SIZE} bytes): {file_path}"}
        content = target.read_text(encoding="utf-8")
        return {"content": content}
    except ValueError as exc:
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
)
def write_project_file(
    file_path: str,
    content: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """写入项目文件."""
    try:
        target = resolve_sandbox_path(project_id or "", file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = target.write_text(content, encoding="utf-8")
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
    name="list_project_files",
    description=(
        "列出项目文件沙箱中的文件和目录。"
        "适用场景：浏览项目文件结构，查找已有笔记或草稿。"
        "\n输入：dir_path（相对目录路径，默认为 /）。"
        "\n输出：成功时返回 {items: [{name, is_dir, size}]}；失败时返回 {error}。"
    ),
    context_params={"project_id": "project_id"},
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
