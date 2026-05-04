"""Conversation API schemas."""

from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreateRequest(BaseModel):
    """创建会话请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str = Field(..., description="项目 ID")
    title: str | None = Field(
        default=None, min_length=1, max_length=200, description="会话标题"
    )


class ConversationUpdateRequest(BaseModel):
    """更新会话请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    title: str = Field(..., min_length=1, max_length=200, description="会话标题")


class ConversationForkRequest(BaseModel):
    """Fork 会话请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    title: str | None = Field(
        default=None, min_length=1, max_length=200, description="新会话标题"
    )
    forked_at_message_id: str | None = Field(
        default=None,
        description="Fork 截断消息 ID",
    )


class ConversationResponse(BaseModel):
    """会话响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    conversation_id: str = Field(..., description="会话 ID")
    project_id: str = Field(..., description="项目 ID")
    title: str = Field(..., description="会话标题")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    forked_from_conversation_id: str | None = Field(
        default=None, description="Fork 来源会话 ID"
    )
    forked_at_message_id: str | None = Field(
        default=None, description="Fork 截断消息 ID"
    )


class ConversationListResponse(BaseModel):
    """会话列表响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[ConversationResponse] = Field(..., description="会话列表")
    total: int = Field(..., description="总数")


class ConversationMessageResponse(BaseModel):
    """会话消息响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    message_id: str = Field(..., description="消息 ID")
    conversation_id: str = Field(..., description="会话 ID")
    role: Literal["system", "user", "assistant", "tool"] = Field(
        ..., description="消息角色"
    )
    content: str | None = Field(default=None, description="消息内容")
    name: str | None = Field(default=None, description="工具名称或 Agent 名称")
    tool_calls: list[dict[str, Any]] | None = Field(
        default=None, description="工具调用列表"
    )
    tool_call_id: str | None = Field(default=None, description="工具调用 ID")
    sequence_no: int = Field(..., description="会话内顺序号")
    turn_id: str | None = Field(default=None, description="所属轮次 ID")
    parent_message_id: str | None = Field(default=None, description="前驱消息 ID")
    message_kind: str = Field(..., description="消息语义类型")
    trace_ids: list[str] | None = Field(
        default=None, description="关联的 trace ID 列表"
    )
    reasoning_content: str | None = Field(default=None, description="思考过程内容")
    images: list[str] | None = Field(default=None, description="消息中附带的图片列表")
    paper_ids: list[str] | None = Field(
        default=None, description="用户本次对话关注的文献 ID 列表"
    )
    created_at: datetime = Field(..., description="创建时间")


class ConversationTurnEventResponse(BaseModel):
    """对话轮次中的 assistant 事件."""

    model_config = ConfigDict(strict=True, extra="forbid")

    message_id: str = Field(..., description="消息 ID")
    role: Literal["assistant", "tool"] = Field(..., description="消息角色")
    message_kind: Literal[
        "assistant_reasoning",
        "assistant_tool_call",
        "tool_result",
        "assistant_final",
    ] = Field(..., description="事件类型")
    content: str | None = Field(default=None, description="消息内容")
    name: str | None = Field(default=None, description="工具名称或 Agent 名")
    tool_calls: list[dict[str, Any]] | None = Field(
        default=None,
        description="工具调用列表",
    )
    tool_call_id: str | None = Field(default=None, description="工具调用 ID")
    sequence_no: int = Field(..., description="顺序号")
    parent_message_id: str | None = Field(default=None, description="前驱消息 ID")
    created_at: datetime = Field(..., description="创建时间")


class ConversationTurnResponse(BaseModel):
    """按 turn 聚合的对话响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    turn_id: str = Field(..., description="轮次 ID")
    user_message: ConversationMessageResponse | None = Field(
        default=None,
        description="该轮用户消息",
    )
    assistant_events: list[ConversationTurnEventResponse] = Field(
        default_factory=lambda: cast(list[ConversationTurnEventResponse], []),
        description="Assistant 事件流",
    )
    trace_ids: list[str] = Field(
        default_factory=lambda: cast(list[str], []),
        description="轮次关联 trace IDs",
    )


class ConversationMessageCreateRequest(BaseModel):
    """创建消息请求（用于 system 注入等场景）."""

    model_config = ConfigDict(strict=True, extra="forbid")

    role: Literal["system", "user", "assistant", "tool"] = Field(
        ..., description="消息角色"
    )
    content: str = Field(..., description="消息内容")
    name: str | None = Field(default=None, description="名称")
    images: list[str] | None = Field(default=None, description="消息中附带的图片列表")
    paper_ids: list[str] | None = Field(
        default=None, description="用户本次对话关注的文献 ID 列表"
    )


class ConversationMessageUpdateRequest(BaseModel):
    """更新消息请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    content: str = Field(..., description="消息内容")
    images: list[str] | None = Field(default=None, description="消息中附带的图片列表")
    paper_ids: list[str] | None = Field(
        default=None, description="用户本次对话关注的文献 ID 列表"
    )
