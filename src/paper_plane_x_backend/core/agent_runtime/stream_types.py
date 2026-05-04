"""Agent 流式执行相关的共享类型."""

from dataclasses import dataclass
from typing import Any


@dataclass
class AgentStreamChunk:
    """Agent 流式执行输出块."""

    delta: str = ""
    reasoning_delta: str = ""
    tool_call_name: str | None = None
    tool_call: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    is_complete: bool = False
    content: str = ""
    step: int = 0
