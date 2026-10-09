"""Project 路由."""

import logging
from pathlib import Path
from typing import NoReturn

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.api.routers.librarian import run_search_paper
from paper_plane_x_backend.models import (
    Project,
    ProjectSortKey,
    SortOrder,
)
from paper_plane_x_backend.schemas.api import (
    LibrarianUnifiedSearchRequest,
    LibrarianUnifiedSearchResponse,
    MessageResponse,
    PaperStatusCountResponse,
    ProjectCreateRequest,
    ProjectExportRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from paper_plane_x_backend.services.orchestrators.project import (
    ProjectDomainError,
    ProjectOrchestrator,
)

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)


def _build_orchestrator(db: DBDep) -> ProjectOrchestrator:
    return ProjectOrchestrator(db=db)


def _raise_as_http(exc: ProjectDomainError) -> NoReturn:
    logger.warning(
        "event=project.domain_error status=%s detail=%s",
        exc.status_code,
        exc.detail,
    )
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _project_to_response(project: Project) -> ProjectResponse:
    """将 Project 模型转换为响应模型."""
    return ProjectResponse(
        project_id=project.project_id,
        name=project.name,
        description=project.description,
        agent_summary=project.agent_summary,
        created_at=project.created_at,
        updated_at=project.updated_at,
        operation_logs=project.operation_logs,
    )


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建项目",
)
async def create_project(
    request: ProjectCreateRequest,
    db: DBDep,
) -> ProjectResponse:
    """创建新项目.

    Args:
        request: 创建项目请求
        db: 数据库实例

    Returns:
        ProjectResponse: 创建的项目
    """
    logger.info("event=project.create_request_received name=%s", request.name)
    orchestrator = _build_orchestrator(db)
    project = orchestrator.create_project(
        name=request.name,
        description=request.description,
        agent_summary=request.agent_summary,
    )
    return _project_to_response(project)


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="列出项目",
)
async def list_projects(
    db: DBDep,
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    sort_order: SortOrder = Query(SortOrder.DESC, description="按 sort_by 排序"),
    sort_by: ProjectSortKey = Query(
        ProjectSortKey.CREATED_AT,
        description="排序字段，支持 created_at、updated_at、name",
    ),
) -> ProjectListResponse:
    """获取项目列表.

    Args:
        db: 数据库实例
        offset: 分页偏移量
        limit: 每页数量

    Returns:
        ProjectListResponse: 项目列表响应
    """
    logger.debug(
        "event=project.list_request_received offset=%s limit=%s", offset, limit
    )
    orchestrator = _build_orchestrator(db)
    projects, total = orchestrator.list_projects(
        offset=offset, limit=limit, sort_order=sort_order, sort_by=sort_by
    )
    items = [_project_to_response(project) for project in projects]

    return ProjectListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="获取项目详情",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def get_project(
    project_id: str,
    db: DBDep,
) -> ProjectResponse:
    """获取单个项目详情.

    Args:
        project_id: 项目 ID
        db: 数据库实例

    Returns:
        ProjectResponse: 项目详情

    Raises:
        HTTPException: 项目不存在时抛出 404
    """
    logger.debug("event=project.get_request_received project_id=%s", project_id)
    orchestrator = _build_orchestrator(db)
    try:
        project = orchestrator.get_project(project_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    return _project_to_response(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="更新项目",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    db: DBDep,
) -> ProjectResponse:
    """更新项目信息.

    Args:
        project_id: 项目 ID
        request: 更新请求
        db: 数据库实例

    Returns:
        ProjectResponse: 更新后的项目

    Raises:
        HTTPException: 项目不存在时抛出 404
    """
    logger.info("event=project.update_request_received project_id=%s", project_id)
    orchestrator = _build_orchestrator(db)
    try:
        project = orchestrator.update_project(
            project_id=project_id,
            name=request.name,
            description=request.description,
            agent_summary=request.agent_summary,
        )
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    return _project_to_response(project)


@router.delete(
    "/{project_id}",
    response_model=MessageResponse,
    summary="删除项目",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def delete_project(
    project_id: str,
    db: DBDep,
) -> MessageResponse:
    """删除项目.

    Args:
        project_id: 项目 ID
        db: 数据库实例

    Returns:
        MessageResponse: 删除成功消息

    Raises:
        HTTPException: 项目不存在时抛出 404
    """
    logger.info("event=project.delete_request_received project_id=%s", project_id)
    orchestrator = _build_orchestrator(db)
    try:
        orchestrator.delete_project(project_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    return MessageResponse(message=f"Project {project_id} deleted successfully")


@router.put(
    "/{project_id}/agent-summary",
    response_model=ProjectResponse,
    summary="设置项目的 agent_summary",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def set_project_agent_summary(
    project_id: str,
    content: str,
    db: DBDep,
) -> ProjectResponse:
    """设置项目的 agent_summary（覆盖写入）。"""
    logger.info(
        "event=project.set_agent_summary_request_received project_id=%s",
        project_id,
    )
    orchestrator = _build_orchestrator(db)
    try:
        project = orchestrator.update_project(
            project_id=project_id,
            name=None,
            description=None,
            agent_summary=content,
        )
    except ProjectDomainError as exc:
        _raise_as_http(exc)
    return _project_to_response(project)


@router.delete(
    "/{project_id}/agent-summary",
    response_model=ProjectResponse,
    summary="删除项目的 agent_summary",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def delete_project_agent_summary(
    project_id: str,
    db: DBDep,
) -> ProjectResponse:
    """删除项目的 agent_summary（置为 null）。"""
    logger.info(
        "event=project.delete_agent_summary_request_received project_id=%s",
        project_id,
    )
    orchestrator = _build_orchestrator(db)
    try:
        orchestrator.project_repo.delete_agent_summary(project_id)
        project = orchestrator.get_project(project_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)
    return _project_to_response(project)


@router.post(
    "/{project_id}/export",
    summary="导出项目数据与文件",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def export_project(
    project_id: str,
    request: ProjectExportRequest,
    db: DBDep,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    logger.info(
        "event=project.export_request_received project_id=%s fields_count=%s",
        project_id,
        len(request.fields),
    )
    orchestrator = _build_orchestrator(db)
    try:
        zip_path, download_name = await run_in_threadpool(
            orchestrator.export_project_bundle,
            project_id=project_id,
            fields=request.fields,
            citations_mode=request.citations_mode,
            include_sandbox_files=request.include_sandbox_files,
        )
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    path_obj = Path(zip_path)

    def _cleanup_export_file(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("event=project.export_cleanup_failed path=%s", str(path))

    background_tasks.add_task(_cleanup_export_file, path_obj)
    return FileResponse(
        path=path_obj,
        media_type="application/zip",
        filename=download_name,
    )


@router.post(
    "/{project_id}/papers/{paper_id}",
    response_model=MessageResponse,
    summary="将论文关联到项目",
    responses={404: {"description": "项目或论文不存在"}},
)
async def link_paper(
    project_id: str,
    paper_id: str,
    db: DBDep,
) -> MessageResponse:
    logger.info(
        "event=project.link_paper_request_received project_id=%s paper_id=%s",
        project_id,
        paper_id,
    )
    orchestrator = _build_orchestrator(db)
    try:
        orchestrator.link_paper(project_id=project_id, paper_id=paper_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)
    return MessageResponse(message=f"Paper {paper_id} linked to project {project_id}")


@router.delete(
    "/{project_id}/papers/{paper_id}",
    response_model=MessageResponse,
    summary="从项目中移除论文关联",
    responses={
        404: {"description": "项目或论文不存在"},
    },
)
async def unlink_paper(
    project_id: str,
    paper_id: str,
    db: DBDep,
) -> MessageResponse:
    """从项目中移除论文关联，不删除论文实体。"""
    logger.info(
        "event=project.unlink_paper_request_received project_id=%s paper_id=%s",
        project_id,
        paper_id,
    )
    orchestrator = _build_orchestrator(db)
    try:
        orchestrator.unlink_paper(project_id=project_id, paper_id=paper_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    return MessageResponse(
        message=f"Paper {paper_id} unlinked from project {project_id}"
    )


@router.get(
    "/{project_id}/papers/status-counts",
    response_model=PaperStatusCountResponse,
    summary="获取项目下论文状态统计",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def get_project_paper_status_counts(
    project_id: str,
    db: DBDep,
) -> PaperStatusCountResponse:
    """获取指定项目下所有论文的状态统计。

    Args:
        project_id: 项目 ID
        db: 数据库实例

    Returns:
        PaperStatusCountResponse: 论文状态统计

    Raises:
        HTTPException: 项目不存在时抛出 404
    """
    logger.debug(
        "event=project.paper_status_counts_request_received project_id=%s",
        project_id,
    )
    orchestrator = _build_orchestrator(db)
    try:
        counts = orchestrator.count_project_paper_statuses(project_id=project_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)
    return PaperStatusCountResponse(**counts)


@router.post(
    "/{project_id}/search",
    response_model=LibrarianUnifiedSearchResponse,
    summary="Project 作用域统一搜索",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def search_project(
    project_id: str,
    request: LibrarianUnifiedSearchRequest,
    db: DBDep,
) -> LibrarianUnifiedSearchResponse:
    logger.debug(
        "event=project.search_request_received project_id=%s query_expr=%s",
        project_id,
        request.query_expr,
    )
    orchestrator = _build_orchestrator(db)
    try:
        orchestrator.get_project(project_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    scoped_request = request.model_copy(update={"project_id": project_id})
    return run_search_paper(request=scoped_request, db=db)
