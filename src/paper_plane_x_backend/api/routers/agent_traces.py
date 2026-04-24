"""Agent trace 路由。"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, status

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.schemas import (
    AgentTraceQueryRequest,
    AgentTraceQueryResponse,
    AgentTraceResponse,
    MessageResponse,
)

router = APIRouter(prefix="/agent-traces", tags=["agent-traces"])


def _parse_messages(value: object) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            result: list[dict[str, Any]] = []
            for item in parsed:
                if isinstance(item, dict):
                    result.append({k: v for k, v in item.items() if isinstance(k, str)})
            return result
        return []

    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                result.append({k: v for k, v in item.items() if isinstance(k, str)})
        return result

    return []


def _parse_usage_payload(value: object) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return {k: v for k, v in parsed.items() if isinstance(k, str)}
        return None

    if isinstance(value, dict):
        return {k: v for k, v in value.items() if isinstance(k, str)}

    return None


def _row_to_trace(row: dict[str, Any]) -> AgentTraceResponse:
    return AgentTraceResponse(
        trace_id=row["trace_id"],
        agent_name=row["agent_name"],
        messages=_parse_messages(row.get("messages")),
        llm_model=row.get("llm_model"),
        prompt_tokens=row.get("prompt_tokens"),
        completion_tokens=row.get("completion_tokens"),
        total_tokens=row.get("total_tokens"),
        usage_payload=_parse_usage_payload(row.get("usage_payload")),
        created_at=row["created_at"],
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

    placeholders = ", ".join(["?"] * len(trace_ids))
    rows = db.fetchall(
        f"""
        SELECT
            trace_id, agent_name, messages, llm_model,
            prompt_tokens, completion_tokens, total_tokens, usage_payload, created_at
        FROM agent_traces
        WHERE trace_id IN ({placeholders})
        """,
        tuple(trace_ids),
    )

    trace_map = {row["trace_id"]: _row_to_trace(row) for row in rows}
    items: list[AgentTraceResponse] = []
    seen: set[str] = set()
    for trace_id in trace_ids:
        if trace_id in seen:
            continue
        trace = trace_map.get(trace_id)
        if trace is not None:
            items.append(trace)
            seen.add(trace_id)

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
    row = db.fetchone("SELECT 1 FROM agent_traces WHERE trace_id = ?", (trace_id,))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace {trace_id} not found",
        )

    db.delete("agent_traces", "trace_id = ?", (trace_id,))
    return MessageResponse(message=f"Trace {trace_id} deleted")
