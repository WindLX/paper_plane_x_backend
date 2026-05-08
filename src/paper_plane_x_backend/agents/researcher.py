"""Researcher Agent.

Project 层级下的对话型 Agent，支持自由文本输出和工具调用。
可读写项目文件沙箱，检索 Librarian 工具，与用户自然对话。
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.core.agent_runtime import AgentStreamChunk, BaseAgent
from paper_plane_x_backend.models.app_settings import LLMConfig
from paper_plane_x_backend.schemas.agent_io.base import ToolCallMessage, ToolMessage
from paper_plane_x_backend.services.app_settings import resolve_agent_llm_config
from paper_plane_x_backend.tools.conversation_io import (
    find_in_project_file,
    list_project_files,
    patch_project_file,
    read_project_file,
    read_project_file_lines,
    remove_project_file,
    replace_project_file_lines,
    replace_project_file_text,
    write_project_file,
)
from paper_plane_x_backend.tools.hitl import ask_human
from paper_plane_x_backend.tools.librarian import (
    deep_dive_tool,
    global_finder,
    matrix_compare,
    search_paper,
)
from paper_plane_x_backend.tools.paper import (
    delete_paper_agent_note,
    get_paper_agent_note,
    update_paper_agent_note,
    write_paper_agent_note,
)
from paper_plane_x_backend.tools.subagent import delegate_to_subagent

logger = logging.getLogger(__name__)

_RESEARCHER_TOOLS = [
    read_project_file,
    read_project_file_lines,
    find_in_project_file,
    write_project_file,
    replace_project_file_lines,
    replace_project_file_text,
    patch_project_file,
    list_project_files,
    remove_project_file,
    global_finder,
    matrix_compare,
    search_paper,
    deep_dive_tool,
    get_paper_agent_note,
    write_paper_agent_note,
    update_paper_agent_note,
    delete_paper_agent_note,
    delegate_to_subagent,
    ask_human,
]


class ResearcherAgent:
    """Researcher Agent.

    接收用户输入，通过 ReAct 循环与 LLM 交互，支持流式输出。
    工具集包含文件沙箱操作和 Librarian 文献检索工具。
    """

    agent_name: str = "ResearcherAgent"
    llm_config_name: str = "researcher"
    prompt_filename: str = "System.md"

    def __init__(
        self,
        project_id: str,
        llm_config: LLMConfig | None = None,
        caller: str | None = None,
        caller_id: str | None = None,
        conversation_id: str | None = None,
        max_steps: int = 15,
    ) -> None:
        self.project_id = project_id
        self.conversation_id = conversation_id
        self.llm_config = llm_config or resolve_agent_llm_config(self.llm_config_name)

        self._agent = BaseAgent(
            mode="normal",
            system_prompt=self._build_system_prompt(),
            tools=list(_RESEARCHER_TOOLS),
            max_steps=max_steps,
            save_trace=True,
            llm_config=self.llm_config,
            agent_name=self.agent_name,
            tool_context={
                "project_id": project_id,
                "conversation_id": conversation_id,
            },
            caller=caller,
            caller_id=caller_id,
        )

    def _build_system_prompt(self) -> str:
        return settings.load_prompt("researcher", self.prompt_filename)

    @property
    def runtime_name(self) -> str:
        return self._agent.agent_name

    @property
    def trace_ids(self) -> list[str]:
        return list(self._agent.trace_ids)

    @property
    def tool_registry(self):
        return self._agent.tool_registry

    def reset_memory(self) -> None:
        self._agent.memory.reset_memory()

    def set_memory(self, messages: list[dict[str, Any]]) -> None:
        """从已有消息列表恢复对话上下文.

        Args:
            messages: 每条消息至少包含 role 和 content 键
        """

        self._agent.memory.reset_memory()
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                self._agent.memory.set_system_prompt(content or "")
            elif role == "user":
                self._agent.memory.append_user_message({"content": content or ""})
            elif role == "assistant":
                tool_calls_raw = msg.get("tool_calls")
                tool_calls: list[ToolCallMessage] | None = None
                if tool_calls_raw:
                    tool_calls = [
                        ToolCallMessage.model_validate(tc) for tc in tool_calls_raw
                    ]
                self._agent.memory.append_assistant_message(
                    content=content,
                    name=msg.get("name"),
                    tool_calls=tool_calls,
                    reasoning_content=msg.get("reasoning_content"),
                )
            elif role == "tool":
                self._agent.memory.append_tool_message(
                    ToolMessage(
                        tool_call_id=msg.get("tool_call_id", ""),
                        name=msg.get("name", ""),
                        content=content or "",
                    )
                )

    def append_user_message(self, content: str) -> None:
        self._agent.memory.append_user_message({"content": content})

    def get_memory_messages(self) -> list[dict[str, Any]]:
        """获取当前 memory 中的所有交互消息（不含 system prompt）。"""
        return self._agent.get_memory_messages()

    def cancel(self) -> None:
        """请求取消当前 agent 的运行。"""
        self._agent.cancel()

    async def run(self) -> str:
        """非流式执行，返回完整文本."""
        result = await self._agent.run()
        return str(result)

    async def run_stream(self) -> AsyncGenerator[AgentStreamChunk, None]:
        """流式执行，逐块 yield 增量内容."""
        async for chunk in self._agent.run_stream():
            yield chunk
