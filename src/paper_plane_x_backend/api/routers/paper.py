"""Paper 顶层路由。"""

import logging
from typing import NoReturn
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from paper_plane_x_backend.api.dependencies import DBDep, TaskManagerDep
from paper_plane_x_backend.models import (
    DataProcessTaskStatus,
    Paper,
    PaperSortKey,
    SortOrder,
)
from paper_plane_x_backend.schemas.api import (
    DataProcessManualUpdateRequest,
    DataProcessSubmitResponse,
    MessageResponse,
    PaperAgentNoteRequest,
    PaperAgentNoteResponse,
    PaperDetailResponse,
    PaperListResponse,
    PaperResponse,
    PaperStatusCountResponse,
)
from paper_plane_x_backend.services.orchestrators.paper import (
    PaperDomainError,
    PaperOrchestrator,
)
from paper_plane_x_backend.services.paper.repository import PaperRepositoryError

router = APIRouter(prefix="/papers", tags=["papers"])
logger = logging.getLogger(__name__)


def _build_orchestrator(
    db: DBDep,
    task_manager: TaskManagerDep,
) -> PaperOrchestrator:
    return PaperOrchestrator(
        db=db,
        task_manager=task_manager,
    )


def _raise_as_http(exc: PaperDomainError) -> NoReturn:
    logger.warning(
        "event=paper.domain_error status=%s detail=%s",
        exc.status_code,
        exc.detail,
    )
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _raise_repo_as_http(exc: PaperRepositoryError) -> NoReturn:
    status_code = 404 if exc.error_code == "not_found" else 400
    raise HTTPException(
        status_code=status_code,
        detail={"code": exc.error_code, "message": exc.message},
    )


def _to_paper_response(orchestrator: PaperOrchestrator, paper: Paper) -> PaperResponse:
    return PaperResponse(
        paper_id=paper.paper_id,
        project_ids=orchestrator.list_paper_project_ids(paper.paper_id),
        title=paper.title,
        authors=paper.authors,
        year=paper.year,
        publication=paper.publication,
        doi=paper.doi,
        custom_meta=paper.custom_meta,
        raw_pdf_path=paper.raw_pdf_path,
        raw_pdf_sha256=paper.raw_pdf_sha256,
        images_paths=paper.images_paths,
        extraction_status=paper.extraction_status,
        extraction_fact_check_status=paper.extraction_fact_check_status,
        analysis_fact_check_status=paper.analysis_fact_check_status,
        extraction_retry_count=paper.extraction_retry_count,
        analysis_retry_count=paper.analysis_retry_count,
        agent_note=paper.agent_note,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


def _to_paper_detail_response(
    orchestrator: PaperOrchestrator,
    paper: Paper,
) -> PaperDetailResponse:
    base = _to_paper_response(orchestrator, paper)
    return PaperDetailResponse(
        **base.model_dump(),
        quick_scan=paper.quick_scan,
        synthesis_data=paper.synthesis_data,
        analysis_report=paper.analysis_report,
        extraction_fact_check_result=paper.extraction_fact_check_result,
        analysis_fact_check_result=paper.analysis_fact_check_result,
    )


@router.post(
    "",
    response_model=DataProcessSubmitResponse,
    status_code=202,
    summary="上传并处理论文",
)
async def create_paper(
    db: DBDep,
    task_manager: TaskManagerDep,
    pdf_file: UploadFile = File(..., description="上传的原始 PDF 文件"),
    title: str | None = Form(default=None, description="论文标题"),
    authors: str | None = Form(default=None, description="作者列表，逗号分隔"),
    year: int | None = Form(default=None, description="发表年份"),
    publication: str | None = Form(default=None, description="发表刊物/会议"),
    doi: str | None = Form(default=None, description="DOI"),
    custom_meta: str | None = Form(default=None, description="自定义 JSON 字符串"),
) -> DataProcessSubmitResponse:
    logger.info(
        "event=paper.create_request_received filename=%s title=%s",
        pdf_file.filename,
        title,
    )
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        task_state, paper_id = await orchestrator.create_paper_and_start_processing(
            upload_file=pdf_file,
            title=title,
            authors=authors,
            year=year,
            publication=publication,
            doi=doi,
            custom_meta=custom_meta,
        )
    except PaperDomainError as exc:
        _raise_as_http(exc)

    return DataProcessSubmitResponse(
        task_id=task_state.task_id,
        status=task_state.status,
        paper_id=paper_id,
        resource_type="paper",
        resource_id=paper_id,
        message=(
            "Data-process task queued"
            if task_state.status == DataProcessTaskStatus.QUEUED
            else "Paper already completed, skipped enqueue"
        ),
    )


@router.post("/batch-get", response_model=PaperListResponse, summary="批量获取论文详情")
async def batch_get_papers(
    paper_ids: list[str],
    db: DBDep,
    task_manager: TaskManagerDep,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    sort_order: SortOrder = Query(SortOrder.DESC, description="按 created_at 排序"),
    sort_by: PaperSortKey = Query(
        PaperSortKey.CREATED_AT,
        description="排序字段，支持 created_at、updated_at、name",
    ),
) -> PaperListResponse:
    logger.debug(
        "event=paper.batch_get_request_received ids_count=%s offset=%s limit=%s",
        len(paper_ids),
        offset,
        limit,
    )
    orchestrator = _build_orchestrator(db, task_manager)
    papers, total = orchestrator.batch_get_papers(
        paper_ids=paper_ids,
        offset=offset,
        limit=limit,
        sort_order=sort_order,
        sort_by=sort_by,
    )
    return PaperListResponse(
        items=[_to_paper_response(orchestrator, paper) for paper in papers],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/status-counts",
    response_model=PaperStatusCountResponse,
    summary="获取全部论文状态统计",
)
async def get_paper_status_counts(
    db: DBDep,
    task_manager: TaskManagerDep,
) -> PaperStatusCountResponse:
    logger.debug("event=paper.status_counts_request_received")
    orchestrator = _build_orchestrator(db, task_manager)
    counts = orchestrator.count_paper_statuses()
    return PaperStatusCountResponse(**counts)


@router.get("/{paper_id}", response_model=PaperDetailResponse, summary="获取论文详情")
async def get_paper(
    paper_id: str,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> PaperDetailResponse:
    logger.debug("event=paper.get_request_received paper_id=%s", paper_id)
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        paper = orchestrator.get_paper(paper_id=paper_id)
    except PaperDomainError as exc:
        _raise_as_http(exc)
    return _to_paper_detail_response(orchestrator, paper)


@router.get(
    "/{paper_id}/markdown",
    response_class=Response,
    summary="下载论文解析后的 Markdown",
)
async def download_paper_markdown(
    paper_id: str,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> Response:
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        markdown = orchestrator.get_markdown(paper_id=paper_id)
    except PaperDomainError as exc:
        _raise_as_http(exc)

    download_name = quote(f"{paper_id}.md", safe="")
    return Response(
        content=markdown,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{download_name}"
        },
    )


@router.get(
    "/{paper_id}/agent-note",
    response_model=PaperAgentNoteResponse,
    summary="获取论文 agent_note",
)
async def get_paper_agent_note(
    paper_id: str,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> PaperAgentNoteResponse:
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        note = orchestrator.repo.get_agent_note(paper_id)
    except PaperRepositoryError as exc:
        _raise_repo_as_http(exc)
    return PaperAgentNoteResponse(paper_id=paper_id, agent_note=note)


@router.put(
    "/{paper_id}/agent-note",
    response_model=PaperAgentNoteResponse,
    summary="写入论文 agent_note",
)
async def write_paper_agent_note(
    paper_id: str,
    request: PaperAgentNoteRequest,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> PaperAgentNoteResponse:
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        orchestrator.repo.set_agent_note(paper_id, request.content)
        note = orchestrator.repo.get_agent_note(paper_id)
    except PaperRepositoryError as exc:
        logger.warning("event=paper.agent_note_write_failed paper_id=%s", paper_id)
        _raise_repo_as_http(exc)
    return PaperAgentNoteResponse(paper_id=paper_id, agent_note=note)


@router.patch(
    "/{paper_id}/agent-note",
    response_model=PaperAgentNoteResponse,
    summary="更新论文 agent_note",
)
async def update_paper_agent_note(
    paper_id: str,
    request: PaperAgentNoteRequest,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> PaperAgentNoteResponse:
    return await write_paper_agent_note(
        paper_id=paper_id,
        request=request,
        db=db,
        task_manager=task_manager,
    )


@router.delete(
    "/{paper_id}/agent-note",
    response_model=PaperAgentNoteResponse,
    summary="删除论文 agent_note",
)
async def delete_paper_agent_note(
    paper_id: str,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> PaperAgentNoteResponse:
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        orchestrator.repo.delete_agent_note(paper_id)
        note = orchestrator.repo.get_agent_note(paper_id)
    except PaperRepositoryError as exc:
        logger.warning("event=paper.agent_note_delete_failed paper_id=%s", paper_id)
        _raise_repo_as_http(exc)
    return PaperAgentNoteResponse(paper_id=paper_id, agent_note=note)


@router.patch("/{paper_id}", response_model=PaperDetailResponse, summary="手动更新论文")
async def manual_update_paper(
    paper_id: str,
    request: DataProcessManualUpdateRequest,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> PaperDetailResponse:
    logger.info("event=paper.manual_update_request_received paper_id=%s", paper_id)
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        paper = orchestrator.update_paper(
            paper_id=paper_id,
            title=request.title,
            authors=request.authors,
            year=request.year,
            publication=request.publication,
            doi=request.doi,
            custom_meta=request.custom_meta,
            extraction_status=request.extraction_status,
            quick_scan=request.quick_scan,
            synthesis_data=request.synthesis_data,
            analysis_report=request.analysis_report,
            extraction_fact_check_status=request.extraction_fact_check_status,
            extraction_fact_check_result=request.extraction_fact_check_result,
            analysis_fact_check_status=request.analysis_fact_check_status,
            analysis_fact_check_result=request.analysis_fact_check_result,
            agent_note=request.agent_note,
        )
    except PaperDomainError as exc:
        _raise_as_http(exc)
    return _to_paper_detail_response(orchestrator, paper)


@router.post(
    "/{paper_id}/reprocess",
    response_model=DataProcessSubmitResponse,
    status_code=202,
    summary="重新运行论文 data-process",
)
async def reprocess_paper(
    paper_id: str,
    db: DBDep,
    task_manager: TaskManagerDep,
    pdf_file: UploadFile = File(..., description="重新上传的原始 PDF 文件"),
) -> DataProcessSubmitResponse:
    logger.info(
        "event=paper.reprocess_request_received paper_id=%s filename=%s",
        paper_id,
        pdf_file.filename,
    )
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        task_id = await orchestrator.reprocess_paper(
            paper_id=paper_id,
            upload_file=pdf_file,
        )
    except PaperDomainError as exc:
        _raise_as_http(exc)

    return DataProcessSubmitResponse(
        task_id=task_id,
        status=DataProcessTaskStatus.QUEUED,
        paper_id=paper_id,
        resource_type="paper",
        resource_id=paper_id,
        message="Data-process task queued",
    )


@router.delete("/{paper_id}", response_model=MessageResponse, summary="删除论文")
async def delete_paper(
    paper_id: str,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> MessageResponse:
    logger.info("event=paper.delete_request_received paper_id=%s", paper_id)
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        orchestrator.delete_paper(paper_id=paper_id)
    except PaperDomainError as exc:
        _raise_as_http(exc)
    return MessageResponse(message=f"Paper {paper_id} deleted successfully")
