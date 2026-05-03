"""Data Process 路由.

职责：
- 解析 HTTP 请求
- 参数校验
- 将业务编排委托给 Orchestrator
"""

import logging
from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query, status

from paper_plane_x_backend.api.dependencies import DBDep, TaskManagerDep
from paper_plane_x_backend.models import SortOrder, TaskSortKey
from paper_plane_x_backend.schemas.api import (
    DataProcessTaskListResponse,
    DataProcessTaskResponse,
    MessageResponse,
)
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessTaskState,
)
from paper_plane_x_backend.services.orchestrators.data_process import (
    DataProcessDomainError,
    DataProcessOrchestrator,
)

router = APIRouter(prefix="/data-process", tags=["data-process"])
logger = logging.getLogger(__name__)


def _build_orchestrator(
    db: DBDep,
    task_manager: TaskManagerDep,
) -> DataProcessOrchestrator:
    return DataProcessOrchestrator(
        db=db,
        task_manager=task_manager,
    )


def _raise_as_http(exc: DataProcessDomainError) -> NoReturn:
    logger.warning(
        "event=data_process.domain_error status=%s detail=%s",
        exc.status_code,
        exc.detail,
    )
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _to_task_response(state: DataProcessTaskState) -> DataProcessTaskResponse:
    return DataProcessTaskResponse(
        task_id=state.task_id,
        paper_id=state.paper_id,
        status=state.status,
        created_at=state.created_at,
        started_at=state.started_at,
        finished_at=state.finished_at,
        error=state.error,
        retry_of_task_id=state.retry_of_task_id,
        extraction_trace_ids=state.extraction_trace_ids,
        analysis_trace_ids=state.analysis_trace_ids,
        extraction_fact_check_trace_ids=state.extraction_fact_check_trace_ids,
        analysis_fact_check_trace_ids=state.analysis_fact_check_trace_ids,
    )


@router.get(
    "/tasks",
    response_model=DataProcessTaskListResponse,
    summary="查看 data-process 任务队列状态",
)
async def list_data_process_tasks(
    db: DBDep,
    task_manager: TaskManagerDep,
    offset: int = Query(0, ge=0, description="分页偏移量"),
    limit: int = Query(20, ge=1, le=200, description="每页数量"),
    sort_order: SortOrder = Query(SortOrder.DESC, description="按 sort_by 排序"),
    sort_by: TaskSortKey = Query(TaskSortKey.CREATED_AT, description="排序字段"),
) -> DataProcessTaskListResponse:
    logger.debug("event=data_process.tasks_list_request_received")
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        states, counts, total = orchestrator.list_tasks(
            offset=offset, limit=limit, sort_order=sort_order, sort_by=sort_by
        )
    except DataProcessDomainError as exc:
        _raise_as_http(exc)

    items = [_to_task_response(state) for state in states]

    return DataProcessTaskListResponse(
        queued=counts["queued"],
        running=counts["running"],
        completed=counts["completed"],
        failed=counts["failed"],
        canceled=counts["canceled"],
        total=total,
        offset=offset,
        limit=limit,
        items=items,
    )


@router.get(
    "/tasks/{task_id}",
    response_model=DataProcessTaskResponse,
    summary="查看单条 data-process 任务",
    responses={404: {"description": "任务不存在"}},
)
async def get_data_process_task(
    task_id: str,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> DataProcessTaskResponse:
    logger.debug("event=data_process.task_get_request_received task_id=%s", task_id)
    orchestrator = _build_orchestrator(db, task_manager)
    state = orchestrator.task_manager.get_task(task_id)
    if state is None:
        logger.warning("event=data_process.task_not_found task_id=%s", task_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    return _to_task_response(state)


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=DataProcessTaskResponse,
    summary="终止 data-process 任务",
    responses={
        404: {"description": "项目或任务不存在"},
        409: {"description": "任务已结束"},
    },
)
async def cancel_data_process_task(
    task_id: str,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> DataProcessTaskResponse:
    logger.info("event=data_process.cancel_request_received task_id=%s", task_id)
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        updated = orchestrator.cancel(task_id=task_id)
    except DataProcessDomainError as exc:
        _raise_as_http(exc)

    return _to_task_response(updated)


@router.post(
    "/tasks/{task_id}/retry",
    response_model=DataProcessTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="重试失败或已取消任务",
    responses={
        404: {"description": "项目或任务不存在"},
        409: {"description": "任务状态不允许重试"},
        400: {"description": "缺少可重试的原始 PDF"},
    },
)
async def retry_failed_task(
    task_id: str,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> DataProcessTaskResponse:
    logger.info("event=data_process.retry_task_request_received task_id=%s", task_id)
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        task_state, _ = await orchestrator.retry_failed_task(
            task_id=task_id,
        )
    except DataProcessDomainError as exc:
        _raise_as_http(exc)

    return _to_task_response(task_state)


@router.delete(
    "/tasks/{task_id}",
    response_model=MessageResponse,
    summary="删除 data-process 任务记录",
    responses={
        404: {"description": "任务不存在"},
        409: {"description": "任务仍在运行中，不可删除"},
    },
)
async def delete_data_process_task_record(
    task_id: str,
    db: DBDep,
    task_manager: TaskManagerDep,
) -> MessageResponse:
    logger.info("event=data_process.delete_record_request_received task_id=%s", task_id)
    orchestrator = _build_orchestrator(db, task_manager)
    try:
        orchestrator.delete_task_record(task_id=task_id)
    except DataProcessDomainError as exc:
        _raise_as_http(exc)

    return MessageResponse(message=f"Task record {task_id} deleted")
