"""Project sandbox file 路由.

前端对 ResearcherAgent 可控的项目沙箱目录下 agent 产生的文件进行增删查改。
"""

import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response, status

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.schemas.api.project_files import (
    ProjectFileContentResponse,
    ProjectFileDeleteResponse,
    ProjectFileExportRequest,
    ProjectFileItem,
    ProjectFileListResponse,
    ProjectFileWriteRequest,
    ProjectFileWriteResponse,
)
from paper_plane_x_backend.services.pandoc import (
    ExportFormat,
    convert_markdown,
    get_content_type,
    get_extension,
)
from paper_plane_x_backend.services.project.repository import ProjectRepository
from paper_plane_x_backend.tools.conversation_io import (
    MAX_FILE_SIZE,
    resolve_sandbox_path,
)

router = APIRouter(prefix="/projects/{project_id}/files", tags=["project_files"])
logger = logging.getLogger(__name__)


def _ensure_project_exists(db: DBDep, project_id: str) -> None:
    """验证项目存在."""
    project = ProjectRepository(db).get(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )


def _resolve_dir_path(project_id: str, dir_path: str) -> Path:
    """解析并验证目录路径."""
    sandbox_root = settings.data_dir / "projects" / project_id
    target = (sandbox_root / dir_path.lstrip("/")).resolve()
    resolved_root = sandbox_root.resolve()
    if not str(target).startswith(str(resolved_root)):
        raise ValueError(f"Path escapes sandbox: {dir_path}")
    return target


@router.get(
    "",
    response_model=ProjectFileListResponse,
    summary="列出项目沙箱文件/目录",
)
def list_project_sandbox_files(
    db: DBDep,
    project_id: str,
    dir_path: str = Query(default="/", description="相对目录路径，默认为 /"),
) -> ProjectFileListResponse:
    """列出项目沙箱中的文件和目录.

    Args:
        project_id: 项目 ID
        dir_path: 相对目录路径
        db: 数据库实例

    Returns:
        ProjectFileListResponse: 文件/目录列表
    """
    _ensure_project_exists(db, project_id)
    try:
        target = _resolve_dir_path(project_id, dir_path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not target.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Directory not found: {dir_path}",
        )
    if not target.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a directory: {dir_path}",
        )

    items: list[ProjectFileItem] = []
    for child in sorted(target.iterdir()):
        try:
            size = child.stat().st_size if child.is_file() else None
        except OSError:
            size = None
        items.append(
            ProjectFileItem(
                name=child.name,
                is_dir=child.is_dir(),
                size=size,
            )
        )
    return ProjectFileListResponse(items=items)


@router.get(
    "/content",
    response_model=ProjectFileContentResponse,
    summary="读取项目沙箱文件内容",
)
def read_project_sandbox_file(
    db: DBDep,
    project_id: str,
    file_path: str = Query(..., description="相对文件路径，如 /notes/idea.md"),
) -> ProjectFileContentResponse:
    """读取项目沙箱中的文件内容.

    Args:
        project_id: 项目 ID
        file_path: 相对文件路径
        db: 数据库实例

    Returns:
        ProjectFileContentResponse: 文件内容
    """
    _ensure_project_exists(db, project_id)
    try:
        target = resolve_sandbox_path(project_id, file_path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not target.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {file_path}",
        )
    if target.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is a directory: {file_path}",
        )
    if target.stat().st_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large (>{MAX_FILE_SIZE} bytes): {file_path}",
        )

    content = target.read_text(encoding="utf-8")
    return ProjectFileContentResponse(file_path=file_path, content=content)


@router.put(
    "/content",
    response_model=ProjectFileWriteResponse,
    summary="写入项目沙箱文件",
)
def write_project_sandbox_file(
    db: DBDep,
    project_id: str,
    request: ProjectFileWriteRequest,
) -> ProjectFileWriteResponse:
    """写入或覆盖项目沙箱中的文件.

    Args:
        project_id: 项目 ID
        request: 写入请求
        db: 数据库实例

    Returns:
        ProjectFileWriteResponse: 写入结果
    """
    _ensure_project_exists(db, project_id)
    try:
        target = resolve_sandbox_path(project_id, request.file_path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    target.parent.mkdir(parents=True, exist_ok=True)
    bytes_written = target.write_text(request.content, encoding="utf-8")
    logger.info(
        "event=project_file.write project_id=%s file_path=%s bytes=%s",
        project_id,
        request.file_path,
        bytes_written,
    )
    return ProjectFileWriteResponse(
        file_path=request.file_path,
        bytes_written=bytes_written,
    )


@router.delete(
    "/content",
    response_model=ProjectFileDeleteResponse,
    summary="删除项目沙箱文件或空目录",
)
def delete_project_sandbox_file(
    db: DBDep,
    project_id: str,
    file_path: str = Query(..., description="相对文件路径"),
) -> ProjectFileDeleteResponse:
    """删除项目沙箱中的文件或空目录.

    Args:
        project_id: 项目 ID
        file_path: 相对文件路径
        db: 数据库实例

    Returns:
        ProjectFileDeleteResponse: 删除结果
    """
    _ensure_project_exists(db, project_id)
    try:
        target = resolve_sandbox_path(project_id, file_path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not target.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {file_path}",
        )

    if target.is_dir():
        target.rmdir()  # 只允许删除空目录
    else:
        target.unlink()

    logger.info(
        "event=project_file.delete project_id=%s file_path=%s",
        project_id,
        file_path,
    )
    return ProjectFileDeleteResponse(removed=file_path)


@router.post(
    "/export",
    summary="导出项目沙箱文件",
)
def export_project_sandbox_file(
    db: DBDep,
    project_id: str,
    request: ProjectFileExportRequest,
) -> Response:
    """将项目沙箱中的 markdown 文件导出为指定格式.

    Args:
        project_id: 项目 ID
        request: 导出请求，包含文件路径和目标格式
        db: 数据库实例

    Returns:
        Response: 导出后的文件内容（二进制流）
    """
    _ensure_project_exists(db, project_id)

    # 验证格式
    valid_formats: set[str] = {"markdown", "docx", "pdf", "html"}
    fmt = request.format.lower()
    if fmt not in valid_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format: {request.format}. Supported: {', '.join(valid_formats)}",
        )

    export_format: ExportFormat = fmt  # type: ignore[assignment]

    try:
        target = resolve_sandbox_path(project_id, request.file_path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not target.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {request.file_path}",
        )
    if target.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is a directory: {request.file_path}",
        )
    if target.stat().st_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large (>{MAX_FILE_SIZE} bytes): {request.file_path}",
        )

    content = target.read_text(encoding="utf-8")
    file_name = target.stem

    try:
        output_bytes = convert_markdown(
            content,
            export_format,
            title=file_name,
        )
    except RuntimeError as exc:
        logger.exception("event=project_file.export_error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    content_type = get_content_type(export_format)
    extension = get_extension(export_format)
    download_name = f"{file_name}.{extension}"

    logger.info(
        "event=project_file.export project_id=%s file_path=%s format=%s bytes=%s",
        project_id,
        request.file_path,
        export_format,
        len(output_bytes),
    )

    # RFC 5987 encoding for non-ASCII filenames in Content-Disposition
    try:
        download_name.encode("latin-1")
        content_disposition = f'attachment; filename="{download_name}"'
    except UnicodeEncodeError:
        encoded_name = quote(download_name, safe="")
        content_disposition = f"attachment; filename*=UTF-8''{encoded_name}"

    return Response(
        content=output_bytes,
        media_type=content_type,
        headers={
            "Content-Disposition": content_disposition,
        },
    )
