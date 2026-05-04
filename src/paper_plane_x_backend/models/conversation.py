"""Conversation 模型.

定义 Conversation（会话）和 ConversationMessage（消息）的数据结构。
"""

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Conversation(BaseModel):
    """会话模型.

    归属于某个 Project，包含多条对话消息。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    conversation_id: str = Field(..., description="唯一标识")
    project_id: str = Field(..., description="所属项目 ID")
    title: str = Field(default="New Conversation", description="会话标题")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    forked_from_conversation_id: str | None = Field(
        default=None, description="Fork 来源 conversation ID"
    )
    forked_at_message_id: str | None = Field(
        default=None, description="Fork 时截断的消息 ID"
    )

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "Conversation":
        """从数据库行创建实例."""
        return cls.model_validate(dict(row))

    def to_db_dict(self) -> dict[str, Any]:
        """转换为数据库插入格式."""
        return self.model_dump()


ConversationRole = Literal["system", "user", "assistant", "tool"]
ConversationMessageKind = Literal[
    "system",
    "user_input",
    "assistant_reasoning",
    "assistant_tool_call",
    "tool_result",
    "assistant_final",
]


class ConversationMessage(BaseModel):
    """会话消息模型.

    单条消息，支持 user/assistant/system/tool 四种角色。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    message_id: str = Field(..., description="唯一标识")
    conversation_id: str = Field(..., description="所属会话 ID")
    role: ConversationRole = Field(..., description="消息角色")
    content: str | None = Field(default=None, description="消息内容")
    name: str | None = Field(default=None, description="工具名或 Agent 名")
    tool_calls: list[dict[str, Any]] | None = Field(
        default=None, description="assistant 发起的工具调用"
    )
    tool_call_id: str | None = Field(
        default=None, description="tool 角色消息对应的调用 ID"
    )
    sequence_no: int = Field(default=0, description="会话内全局单调递增顺序号")
    turn_id: str | None = Field(default=None, description="所属对话轮次 ID")
    parent_message_id: str | None = Field(default=None, description="链式前驱消息 ID")
    message_kind: ConversationMessageKind = Field(
        default="assistant_final",
        description="消息语义类型",
    )
    trace_ids: list[str] | None = Field(
        default=None, description="关联的 Agent trace ID 列表"
    )
    reasoning_content: str | None = Field(default=None, description="思考过程内容")
    tools: list[dict[str, Any]] | None = Field(
        default=None, description="本次可用的工具注册表"
    )
    images: list[str] | None = Field(
        default=None, description="消息中附带的图片 URL/base64 列表"
    )
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "ConversationMessage":
        """从数据库行创建实例，自动解析 JSON 字段."""
        data = dict(row)

        for json_col in ["tool_calls", "trace_ids", "tools", "images"]:
            raw = data.get(json_col)
            if isinstance(raw, str) and raw:
                try:
                    parsed = json.loads(raw)
                    data[json_col] = parsed if isinstance(parsed, list) else None
                except json.JSONDecodeError:
                    data[json_col] = None
            elif not isinstance(raw, list):
                data[json_col] = None

        if not data.get("message_kind"):
            role = data.get("role")
            if role == "user":
                data["message_kind"] = "user_input"
            elif role == "tool":
                data["message_kind"] = "tool_result"
            elif data.get("tool_calls"):
                data["message_kind"] = "assistant_tool_call"
            elif data.get("reasoning_content"):
                data["message_kind"] = "assistant_reasoning"
            else:
                data["message_kind"] = "assistant_final"

        if data.get("sequence_no") is None:
            data["sequence_no"] = 0

        return cls.model_validate(data)

    def to_db_dict(self) -> dict[str, Any]:
        """转换为数据库插入格式，自动序列化 JSON 字段."""
        data = self.model_dump()
        for json_col in ["tool_calls", "trace_ids", "tools", "images"]:
            value = data.get(json_col)
            if value is not None:
                data[json_col] = json.dumps(value, ensure_ascii=False)
        return data
