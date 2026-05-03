"""Agent trace API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentTraceQueryRequest(BaseModel):
    """批量查询 Agent trace 请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    trace_ids: list[str] = Field(
        default_factory=list[str],
        description="待查询 trace_id 列表，按给定顺序返回",
    )


class AgentTraceResponse(BaseModel):
    """单条 Agent trace 响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    trace_id: str = Field(..., description="唯一标识 (UUID)")
    agent_name: str = Field(..., description="Agent 名称")
    messages: list[dict[str, Any]] = Field(
        default_factory=list[dict[str, Any]],
        description="完整消息历史",
    )
    llm_model: str | None = Field(default=None, description="模型标识")
    prompt_tokens: int | None = Field(default=None, description="输入 token 用量")
    completion_tokens: int | None = Field(default=None, description="输出 token 用量")
    total_tokens: int | None = Field(default=None, description="总 token 用量")
    usage_payload: dict[str, Any] | None = Field(
        default=None,
        description="原始 usage 信息",
    )
    created_at: datetime = Field(..., description="创建时间")
    caller: str | None = Field(default=None, description="调用方")
    caller_id: str | None = Field(default=None, description="调用方业务 ID")


class AgentTraceQueryResponse(BaseModel):
    """批量查询 Agent trace 响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[AgentTraceResponse] = Field(
        default_factory=list[AgentTraceResponse],
        description="trace 列表",
    )


class AgentTraceListRequest(BaseModel):
    """分页列式查询 Agent trace 请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    offset: int = Field(default=0, ge=0, description="偏移量")
    limit: int = Field(default=20, ge=1, le=100, description="每页数量")
    sort_by: str = Field(default="created_at", description="排序字段")
    sort_order: str = Field(default="desc", description="排序方向")
    agent_name: str | None = Field(default=None, description="按 Agent 名称过滤")
    caller: str | None = Field(default=None, description="按调用方过滤")
    caller_id: str | None = Field(default=None, description="按调用方业务 ID 过滤")
    llm_model: str | None = Field(default=None, description="按模型过滤")
    created_at_from: str | None = Field(
        default=None, description="创建时间起（ISO 格式）"
    )
    created_at_to: str | None = Field(
        default=None, description="创建时间止（ISO 格式）"
    )


class AgentTraceStats(BaseModel):
    """Agent trace 统计信息。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    agent_name_counts: dict[str, int] = Field(
        default_factory=dict,
        description="按 agent_name 分组计数",
    )


class AgentTraceListResponse(BaseModel):
    """分页列式查询 Agent trace 响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    offset: int = Field(..., description="偏移量")
    limit: int = Field(..., description="每页数量")
    total: int = Field(..., description="命中总数")
    items: list[AgentTraceResponse] = Field(
        default_factory=list[AgentTraceResponse],
        description="trace 列表",
    )
    stats: AgentTraceStats = Field(
        default_factory=AgentTraceStats,
        description="统计信息",
    )
