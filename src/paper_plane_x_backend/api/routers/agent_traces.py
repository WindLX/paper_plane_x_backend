"""Agent trace 路由。"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.schemas.api import (
    AgentTraceListRequest,
    AgentTraceListResponse,
    AgentTraceQueryRequest,
    AgentTraceQueryResponse,
    AgentTraceResponse,
    AgentTraceStats,
    MessageResponse,
)
from paper_plane_x_backend.services.agent_trace.repository import (
    AgentTraceRepository,
    AgentTraceRepositoryError,
)

router = APIRouter(prefix="/agent-traces", tags=["agent-traces"])
logger = logging.getLogger(__name__)


def _trace_dict_to_response(trace_dict: dict[str, Any]) -> AgentTraceResponse:
    return AgentTraceResponse(
        trace_id=str(trace_dict["trace_id"]),
        agent_name=str(trace_dict["agent_name"]),
        messages=(
            trace_dict["messages"]
            if isinstance(trace_dict.get("messages"), list)
            else []
        ),
        llm_model=(
            trace_dict["llm_model"]
            if isinstance(trace_dict.get("llm_model"), str)
            else None
        ),
        prompt_tokens=(
            trace_dict["prompt_tokens"]
            if isinstance(trace_dict.get("prompt_tokens"), int)
            else None
        ),
        completion_tokens=(
            trace_dict["completion_tokens"]
            if isinstance(trace_dict.get("completion_tokens"), int)
            else None
        ),
        total_tokens=(
            trace_dict["total_tokens"]
            if isinstance(trace_dict.get("total_tokens"), int)
            else None
        ),
        usage_payload=(
            trace_dict["usage_payload"]
            if isinstance(trace_dict.get("usage_payload"), dict)
            else None
        ),
        tools=(
            trace_dict["tools"] if isinstance(trace_dict.get("tools"), list) else None
        ),
        created_at=trace_dict["created_at"],
        caller=(
            trace_dict["caller"] if isinstance(trace_dict.get("caller"), str) else None
        ),
        caller_id=(
            trace_dict["caller_id"]
            if isinstance(trace_dict.get("caller_id"), str)
            else None
        ),
    )


@router.post(
    "/query",
    response_model=AgentTraceQueryResponse,
    summary="批量查询 Agent traces",
)
async def query_agent_traces(
    request: AgentTraceQueryRequest,
    db: DBDep,
) -> AgentTraceQueryResponse:
    trace_ids = [trace_id for trace_id in request.trace_ids if trace_id]
    if not trace_ids:
        return AgentTraceQueryResponse(items=[])

    logger.debug(
        "event=agent_trace.query_request_received trace_count=%s",
        len(trace_ids),
    )
    repo = AgentTraceRepository(db)
    trace_dicts = repo.batch_get(trace_ids)

    trace_map = {t["trace_id"]: _trace_dict_to_response(t) for t in trace_dicts}
    items: list[AgentTraceResponse] = []
    seen: set[str] = set()
    for trace_id in trace_ids:
        if trace_id in seen:
            continue
        trace = trace_map.get(trace_id)
        if trace is not None:
            items.append(trace)
            seen.add(trace_id)

    logger.info(
        "event=agent_trace.query_completed requested=%s found=%s",
        len(trace_ids),
        len(items),
    )
    return AgentTraceQueryResponse(items=items)


@router.delete(
    "/{trace_id}",
    response_model=MessageResponse,
    summary="删除单条 Agent trace 记录",
    responses={
        404: {"description": "trace 不存在"},
    },
)
async def delete_agent_trace(
    trace_id: str,
    db: DBDep,
) -> MessageResponse:
    logger.info("event=agent_trace.delete_request_received trace_id=%s", trace_id)
    repo = AgentTraceRepository(db)
    try:
        repo.delete(trace_id)
    except AgentTraceRepositoryError as exc:
        logger.warning(
            "event=agent_trace.delete_failed trace_id=%s error=%s",
            trace_id,
            exc.message,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc
    logger.info("event=agent_trace.deleted trace_id=%s", trace_id)
    return MessageResponse(message=f"Trace {trace_id} deleted")


@router.post(
    "/list",
    response_model=AgentTraceListResponse,
    summary="分页列式查询 Agent traces",
)
async def list_agent_traces(
    request: AgentTraceListRequest,
    db: DBDep,
) -> AgentTraceListResponse:
    logger.debug(
        "event=agent_trace.list_request_received offset=%s limit=%s",
        request.offset,
        request.limit,
    )
    repo = AgentTraceRepository(db)

    trace_dicts = repo.list(
        offset=request.offset,
        limit=request.limit,
        sort_by=request.sort_by,
        sort_order=request.sort_order,
        agent_name=request.agent_name,
        caller=request.caller,
        caller_id=request.caller_id,
        llm_model=request.llm_model,
        created_at_from=request.created_at_from,
        created_at_to=request.created_at_to,
    )
    total = repo.count(
        agent_name=request.agent_name,
        caller=request.caller,
        caller_id=request.caller_id,
        llm_model=request.llm_model,
        created_at_from=request.created_at_from,
        created_at_to=request.created_at_to,
    )
    agent_name_counts = repo.count_by_agent_name()

    items = [_trace_dict_to_response(t) for t in trace_dicts]

    logger.info(
        "event=agent_trace.list_completed offset=%s limit=%s returned=%s total=%s",
        request.offset,
        request.limit,
        len(items),
        total,
    )
    return AgentTraceListResponse(
        offset=request.offset,
        limit=request.limit,
        total=total,
        items=items,
        stats=AgentTraceStats(agent_name_counts=agent_name_counts),
    )
