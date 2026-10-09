"""Project sandbox file 路由.

前端对项目沙箱目录下 agent 或外部 CLI 产生的文件进行增删查改。
"""

import logging
from typing import NoReturn
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
from paper_plane_x_backend.schemas.api.project_files import (
    ProjectFileContentResponse,
    ProjectFileDeleteResponse,
    ProjectFileExportRequest,
    ProjectFileFindResponse,
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
from paper_plane_x_backend.services.project.files import (
    MAX_FILE_SIZE,
    ProjectFileError,
    get_project_file_manager,
)
from paper_plane_x_backend.services.project.repository import ProjectRepository

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


def _raise_project_file_error(exc: ProjectFileError) -> NoReturn:
    logger.warning(
        "event=project_file.error code=%s status=%s message=%s",
        exc.code,
        exc.status_code,
        exc.message,
    )
    detail: dict[str, object] = {"code": exc.code, "message": exc.message}
    if exc.details is not None:
        detail["details"] = exc.details
    raise HTTPException(
        status_code=exc.status_code,
        detail=detail,
    )


def _content_disposition(
    download_name: str,
    *,
    disposition: str = "attachment",
) -> str:
    """Build an RFC 5987-aware content disposition."""
    try:
        download_name.encode("latin-1")
        return f'{disposition}; filename="{download_name}"'
    except UnicodeEncodeError:
        encoded_name = quote(download_name, safe="")
        return f"{disposition}; filename*=UTF-8''{encoded_name}"


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
    """列出项目沙箱中的文件和目录."""
    _ensure_project_exists(db, project_id)
    try:
        payload = get_project_file_manager(db).list_files(project_id, dir_path)
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
    return ProjectFileListResponse.model_validate(payload)


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
    """读取项目沙箱中的文件内容."""
    _ensure_project_exists(db, project_id)
    try:
        payload = get_project_file_manager(db).read_file(project_id, file_path)
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
    return ProjectFileContentResponse.model_validate(payload)


@router.get(
    "/download",
    response_class=Response,
    summary="下载项目沙箱文件原始字节",
)
def download_project_sandbox_file(
    db: DBDep,
    project_id: str,
    file_path: str = Query(..., description="相对文件路径，如 /notes/idea.md"),
) -> Response:
    """以附件形式下载项目沙箱文件原始字节.

    与 /content 不同，下载不做 UTF-8 解码，返回磁盘上的原始字节；
    路径、扩展名、大小均复用项目文件沙箱的既有校验与错误语义。
    """
    _ensure_project_exists(db, project_id)
    try:
        result = get_project_file_manager(db).download_file(project_id, file_path)
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
    logger.debug(
        "event=project_file.download project_id=%s file_path=%s bytes=%s",
        project_id,
        file_path,
        len(result.content),
    )
    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={"Content-Disposition": _content_disposition(result.download_name)},
    )


@router.get(
    "/preview",
    response_class=Response,
    summary="内联预览项目沙箱图片",
)
def preview_project_sandbox_file(
    db: DBDep,
    project_id: str,
    file_path: str = Query(..., description="相对文件路径，如 /images/figure.png"),
) -> Response:
    """以内联方式返回项目沙箱中的图片字节.

    MIME 类型按校验后的真实内容返回；响应带 CSP ``sandbox``，即使直接打开 SVG 也无法执行脚本。
    预览只接受图片，文本文件继续走 /content 与 /download。
    """
    _ensure_project_exists(db, project_id)
    try:
        result = get_project_file_manager(db).preview_image(project_id, file_path)
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
    logger.debug(
        "event=project_file.preview project_id=%s file_path=%s bytes=%s content_type=%s",
        project_id,
        file_path,
        len(result.content),
        result.content_type,
    )
    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Content-Disposition": _content_disposition(
                result.download_name,
                disposition="inline",
            ),
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


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
    try:
        payload = get_project_file_manager(db).read_file_lines(
            project_id,
            file_path,
            start_line,
            end_line,
        )
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
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
    try:
        payload = get_project_file_manager(db).find_in_file(
            project_id,
            file_path,
            query,
            case_sensitive=case_sensitive,
            max_matches=max_matches,
        )
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
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
    """写入或覆盖项目沙箱中的文件或者创建目录."""
    _ensure_project_exists(db, project_id)
    is_dir = request.is_dir or False
    try:
        payload = get_project_file_manager(db).write_file(
            project_id,
            request.file_path,
            request.content,
            is_dir=is_dir,
        )
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
    return ProjectFileWriteResponse.model_validate(payload)


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
    单文件大小不能超过 MAX_FILE_SIZE。文本文件按原样保存；图片文件（PNG/JPEG/WebP/GIF/SVG）
    额外按真实内容校验，SVG 必须是静态自包含文档。
    """
    _ensure_project_exists(db, project_id)
    content = await file.read(MAX_FILE_SIZE + 1)
    try:
        payload = get_project_file_manager(db).write_bytes(
            project_id, file_path, content
        )
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
    logger.info(
        "event=project_file.upload project_id=%s file_path=%s bytes=%s filename=%s",
        project_id,
        file_path,
        len(content),
        file.filename,
    )
    return ProjectFileWriteResponse.model_validate(payload)


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
    try:
        payload = get_project_file_manager(db).replace_file_lines(
            project_id,
            request.file_path,
            request.start_line,
            request.end_line,
            request.new_text,
        )
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
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
    try:
        payload = get_project_file_manager(db).replace_file_text(
            project_id,
            request.file_path,
            request.old_text,
            request.new_text,
            replace_all=request.replace_all,
            expected_occurrences=request.expected_occurrences,
        )
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
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
    try:
        payload = get_project_file_manager(db).patch_file(
            project_id,
            request.file_path,
            request.action,
            request.anchor_text,
            request.content,
            expected_occurrences=request.expected_occurrences,
        )
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
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
    """删除项目沙箱中的文件或空目录."""
    _ensure_project_exists(db, project_id)
    try:
        payload = get_project_file_manager(db).remove_path(project_id, file_path)
    except ProjectFileError as exc:
        _raise_project_file_error(exc)
    return ProjectFileDeleteResponse.model_validate(payload)


@router.post(
    "/export",
    summary="导出项目沙箱文件",
)
def export_project_sandbox_file(
    db: DBDep,
    project_id: str,
    request: ProjectFileExportRequest,
) -> Response:
    """将项目沙箱中的 markdown 文件导出为指定格式."""
    _ensure_project_exists(db, project_id)
    try:
        result = get_project_file_manager(db).export_markdown_file(
            project_id,
            request.file_path,
            request.format,
        )
    except ProjectFileError as exc:
        _raise_project_file_error(exc)

    logger.info(
        "event=project_file.export project_id=%s file_path=%s format=%s bytes=%s",
        project_id,
        request.file_path,
        request.format,
        len(result.content),
    )
    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={"Content-Disposition": _content_disposition(result.download_name)},
    )
