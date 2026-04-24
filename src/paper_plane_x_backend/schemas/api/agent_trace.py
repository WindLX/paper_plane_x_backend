"""Agent trace API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentTraceQueryRequest(BaseModel):
    """批量查询 Agent trace 请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    trace_ids: list[str] = Field(
        default_factory=list,
        description="待查询 trace_id 列表，按给定顺序返回",
    )


class AgentTraceResponse(BaseModel):
    """单条 Agent trace 响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    trace_id: str = Field(..., description="唯一标识 (UUID)")
    agent_name: str = Field(..., description="Agent 名称")
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
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


class AgentTraceQueryResponse(BaseModel):
    """批量查询 Agent trace 响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[AgentTraceResponse] = Field(
        default_factory=list,
        description="trace 列表",
    )
