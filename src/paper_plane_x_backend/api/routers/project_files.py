"""Project sandbox file 路由.

前端对 ResearcherAgent 可控的项目沙箱目录下 agent 产生的文件进行增删查改。
"""

import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.schemas.api.project_files import (
    ProjectFileContentResponse,
    ProjectFileDeleteResponse,
    ProjectFileExportRequest,
    ProjectFileFindResponse,
    ProjectFileItem,
    ProjectFileListResponse,
    ProjectFilePatchRequest,
    ProjectFilePatchResponse,
    ProjectFileReadLinesResponse,
    ProjectFileReplaceLinesRequest,
    ProjectFileReplaceLinesResponse,
    ProjectFileReplaceTextRequest,
    ProjectFileReplaceTextResponse,
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
    find_in_project_file,
    patch_project_file,
    read_project_file_lines,
    replace_project_file_lines,
    replace_project_file_text,
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


def _raise_tool_error(payload: dict[str, object]) -> None:
    error = payload.get("error")
    if error is None:
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "project_file_tool_error", "message": str(error)},
    )


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


@router.get(
    "/lines",
    response_model=ProjectFileReadLinesResponse,
    summary="按行读取项目沙箱文件内容",
)
def read_project_sandbox_file_lines(
    db: DBDep,
    project_id: str,
    file_path: str = Query(..., description="相对文件路径，如 /notes/idea.md"),
    start_line: int = Query(..., ge=1, description="起始行号，1-based"),
    end_line: int | None = Query(default=None, ge=1, description="结束行号，含端点"),
) -> ProjectFileReadLinesResponse:
    _ensure_project_exists(db, project_id)
    assert read_project_file_lines.function is not None
    payload = read_project_file_lines.function(
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        project_id=project_id,
    )
    _raise_tool_error(payload)
    return ProjectFileReadLinesResponse.model_validate(payload)


@router.get(
    "/find",
    response_model=ProjectFileFindResponse,
    summary="在项目沙箱文件内查找文本",
)
def find_project_sandbox_file_text(
    db: DBDep,
    project_id: str,
    file_path: str = Query(..., description="相对文件路径，如 /notes/idea.md"),
    query: str = Query(..., min_length=1, description="查找文本"),
    case_sensitive: bool = Query(default=False),
    max_matches: int = Query(default=20, ge=1, le=200),
) -> ProjectFileFindResponse:
    _ensure_project_exists(db, project_id)
    assert find_in_project_file.function is not None
    payload = find_in_project_file.function(
        file_path=file_path,
        query=query,
        case_sensitive=case_sensitive,
        max_matches=max_matches,
        project_id=project_id,
    )
    _raise_tool_error(payload)
    return ProjectFileFindResponse.model_validate(payload)


@router.put(
    "/content",
    response_model=ProjectFileWriteResponse,
    summary="写入项目沙箱文件或者创建目录",
)
def write_project_sandbox_file(
    db: DBDep,
    project_id: str,
    request: ProjectFileWriteRequest,
) -> ProjectFileWriteResponse:
    """写入或覆盖项目沙箱中的文件或者创建目录.

    Args:
        project_id: 项目 ID
        request: 写入请求
        db: 数据库实例

    Returns:
        ProjectFileWriteResponse: 写入结果
    """
    _ensure_project_exists(db, project_id)
    is_dir = request.is_dir or False
    try:
        target = resolve_sandbox_path(project_id, request.file_path, is_dir)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    target.parent.mkdir(parents=True, exist_ok=True)
    if is_dir:
        target.mkdir(exist_ok=True)
        bytes_written = 0
    else:
        bytes_written = target.write_text(request.content, encoding="utf-8")
    logger.info(
        "event=project_file.write project_id=%s file_path=%s bytes=%s is_dir=%s",
        project_id,
        request.file_path,
        bytes_written,
        is_dir,
    )
    return ProjectFileWriteResponse(
        file_path=request.file_path,
        bytes_written=bytes_written,
        is_dir=is_dir,
    )


@router.post(
    "/upload",
    response_model=ProjectFileWriteResponse,
    summary="上传本地文件到项目沙箱",
)
async def upload_project_sandbox_file(
    db: DBDep,
    project_id: str,
    file: UploadFile = File(..., description="要上传的文件"),
    file_path: str = Form(..., description="目标相对文件路径，如 /notes/idea.md"),
) -> ProjectFileWriteResponse:
    """上传文件到项目沙箱.

    Upload 复用项目文件沙箱的安全约束：路径不能逃逸项目目录、扩展名必须在白名单内、
    单文件大小不能超过 MAX_FILE_SIZE。
    """
    _ensure_project_exists(db, project_id)
    try:
        target = resolve_sandbox_path(project_id, file_path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if target.exists() and target.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is a directory: {file_path}",
        )

    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large (>{MAX_FILE_SIZE} bytes): {file_path}",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    logger.info(
        "event=project_file.upload project_id=%s file_path=%s bytes=%s filename=%s",
        project_id,
        file_path,
        len(content),
        file.filename,
    )
    return ProjectFileWriteResponse(
        file_path=file_path,
        bytes_written=len(content),
        is_dir=False,
    )


@router.patch(
    "/lines",
    response_model=ProjectFileReplaceLinesResponse,
    summary="按行号区间替换项目沙箱文件内容",
)
def replace_project_sandbox_file_lines(
    db: DBDep,
    project_id: str,
    request: ProjectFileReplaceLinesRequest,
) -> ProjectFileReplaceLinesResponse:
    _ensure_project_exists(db, project_id)
    assert replace_project_file_lines.function is not None
    payload = replace_project_file_lines.function(
        file_path=request.file_path,
        start_line=request.start_line,
        end_line=request.end_line,
        new_text=request.new_text,
        project_id=project_id,
    )
    _raise_tool_error(payload)
    return ProjectFileReplaceLinesResponse.model_validate(payload)


@router.patch(
    "/text",
    response_model=ProjectFileReplaceTextResponse,
    summary="按精确文本替换项目沙箱文件内容",
)
def replace_project_sandbox_file_text(
    db: DBDep,
    project_id: str,
    request: ProjectFileReplaceTextRequest,
) -> ProjectFileReplaceTextResponse:
    _ensure_project_exists(db, project_id)
    assert replace_project_file_text.function is not None
    payload = replace_project_file_text.function(
        file_path=request.file_path,
        old_text=request.old_text,
        new_text=request.new_text,
        replace_all=request.replace_all,
        expected_occurrences=request.expected_occurrences,
        project_id=project_id,
    )
    _raise_tool_error(payload)
    return ProjectFileReplaceTextResponse.model_validate(payload)


@router.patch(
    "/patch",
    response_model=ProjectFilePatchResponse,
    summary="基于锚点 patch 项目沙箱文件内容",
)
def patch_project_sandbox_file(
    db: DBDep,
    project_id: str,
    request: ProjectFilePatchRequest,
) -> ProjectFilePatchResponse:
    _ensure_project_exists(db, project_id)
    assert patch_project_file.function is not None
    payload = patch_project_file.function(
        file_path=request.file_path,
        action=request.action,
        anchor_text=request.anchor_text,
        content=request.content,
        expected_occurrences=request.expected_occurrences,
        project_id=project_id,
    )
    _raise_tool_error(payload)
    return ProjectFilePatchResponse.model_validate(payload)


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
