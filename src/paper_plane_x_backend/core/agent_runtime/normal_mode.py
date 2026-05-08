"""BaseAgent normal 模式执行器.

将 normal / stream 模式下的执行循环从 BaseAgent 主文件中拆出，
方便单独调试工具调用与流式输出链路。
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any, Protocol

from paper_plane_x_backend.core.agent_runtime.exceptions import AgentExecutionError
from paper_plane_x_backend.core.agent_runtime.llm_client import LLMClient, LLMResponse
from paper_plane_x_backend.core.agent_runtime.memory import MemoryManager
from paper_plane_x_backend.core.agent_runtime.stream_types import AgentStreamChunk
from paper_plane_x_backend.core.agent_runtime.tooling import ToolRegistry
from paper_plane_x_backend.schemas.agent_io.base import ToolCallMessage

logger = logging.getLogger(__name__)


class SupportsNormalAgentRuntime(Protocol):
    agent_name: str
    max_steps: int
    save_trace: bool
    trace_ids: list[str]
    tool_context: dict[str, Any]
    llm: LLMClient
    memory: MemoryManager
    tool_registry: ToolRegistry

    def build_messages_with_tool_guide(self) -> list[dict[str, Any]]: ...

    def save_trace_snapshot(
        self,
        messages: list[dict[str, Any]],
        *,
        llm_model: str | None = None,
        usage: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> None: ...

    def ensure_not_cancelled(self) -> None: ...

    def save_partial_trace_snapshot(
        self,
        messages: list[dict[str, Any]],
        *,
        llm_model: str | None = None,
        usage: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        assistant_content: str | None = None,
        assistant_reasoning_content: str | None = None,
        assistant_tool_calls: list[ToolCallMessage] | None = None,
        step: int | None = None,
        cancel_reason: str = "cancelled",
    ) -> None: ...


class NormalAgentRunner:
    """承载 BaseAgent normal 模式执行循环的辅助对象."""

    def __init__(self, agent: SupportsNormalAgentRuntime) -> None:
        self.agent = agent

    async def run(self) -> str:
        logger.info(
            "event=agent.run_started agent=%s mode=normal",
            self.agent.agent_name,
        )
        if not self.agent.memory.has_role_message("user"):
            raise AgentExecutionError(
                message="No user message in memory. Append user input before run().",
                agent_name=self.agent.agent_name,
            )

        if len(self.agent.tool_registry) == 0:
            content = ""
            reasoning_content = None
            llm_model: str | None = None
            usage: dict[str, Any] | None = None
            try:
                response = await self.agent.llm.generate(
                    self.agent.build_messages_with_tool_guide()
                )
                content = response.content or ""
                reasoning_content = response.reasoning_content
                llm_model = response.model
                usage = response.usage

                self.agent.memory.append_assistant_message(
                    content=content,
                    name=self.agent.agent_name,
                    reasoning_content=reasoning_content,
                )

                if self.agent.save_trace:
                    self.agent.save_trace_snapshot(
                        messages=self.agent.build_messages_with_tool_guide(),
                        llm_model=response.model,
                        usage=response.usage,
                        tools=self.agent.tool_registry.to_openai_format(),
                    )

                logger.info(
                    "event=agent.run_completed agent=%s mode=normal step=1",
                    self.agent.agent_name,
                )
                return content
            except asyncio.CancelledError:
                if self.agent.save_trace:
                    self.agent.save_partial_trace_snapshot(
                        messages=self.agent.build_messages_with_tool_guide(),
                        llm_model=llm_model,
                        usage=usage,
                        tools=self.agent.tool_registry.to_openai_format(),
                        assistant_content=content or None,
                        assistant_reasoning_content=reasoning_content,
                        step=1,
                    )
                logger.info(
                    "event=agent.run_canceled agent=%s mode=normal step=1",
                    self.agent.agent_name,
                )
                raise

        for step in range(self.agent.max_steps):
            logger.debug(
                "event=agent.step_started agent=%s mode=normal step=%s max_steps=%s",
                self.agent.agent_name,
                step + 1,
                self.agent.max_steps,
            )
            assistant_appended = False
            messages: list[dict[str, Any]] = []
            response: LLMResponse | None = None
            try:
                messages = self.agent.build_messages_with_tool_guide()
                tools = self.agent.tool_registry.to_openai_format()
                if tools:
                    response = await self.agent.llm.generate_with_tools(messages, tools)
                else:
                    response = await self.agent.llm.generate(messages)

                self.agent.memory.append_assistant_message(
                    content=None if response.tool_calls else response.content,
                    name=self.agent.agent_name,
                    tool_calls=response.tool_calls or None,
                    reasoning_content=response.reasoning_content,
                )
                assistant_appended = True

                if self.agent.save_trace:
                    self.agent.save_trace_snapshot(
                        messages=self.agent.build_messages_with_tool_guide(),
                        llm_model=response.model,
                        usage=response.usage,
                        tools=self.agent.tool_registry.to_openai_format(),
                    )

                if response.tool_calls:
                    logger.debug(
                        "event=agent.tool_calls_received agent=%s step=%s tool_call_count=%s",
                        self.agent.agent_name,
                        step + 1,
                        len(response.tool_calls),
                    )
                    tool_ctx = {
                        **self.agent.tool_context,
                        "_caller_agent_name": self.agent.agent_name,
                        "_caller_trace_id": (
                            self.agent.trace_ids[-1] if self.agent.trace_ids else None
                        ),
                    }
                    for tool_call in response.tool_calls:
                        tool_msg = await self.agent.tool_registry.execute_tool_call(
                            tool_call,
                            context=tool_ctx,
                        )
                        self.agent.memory.append_tool_message(tool_msg)
                    continue

                final_content = response.content or ""
                logger.info(
                    "event=agent.run_completed agent=%s mode=normal step=%s",
                    self.agent.agent_name,
                    step + 1,
                )
                return final_content
            except asyncio.CancelledError:
                if self.agent.save_trace:
                    self.agent.save_partial_trace_snapshot(
                        messages=(
                            self.agent.build_messages_with_tool_guide()
                            if assistant_appended
                            else messages
                        ),
                        llm_model=(response.model if response is not None else None),
                        usage=(response.usage if response is not None else None),
                        tools=self.agent.tool_registry.to_openai_format(),
                        assistant_content=(
                            None
                            if assistant_appended
                            else (response.content if response is not None else None)
                        ),
                        assistant_reasoning_content=(
                            None
                            if assistant_appended
                            else (
                                response.reasoning_content
                                if response is not None
                                else None
                            )
                        ),
                        assistant_tool_calls=(
                            None
                            if assistant_appended
                            else (response.tool_calls if response is not None else None)
                        ),
                        step=step + 1,
                    )
                logger.info(
                    "event=agent.run_canceled agent=%s mode=normal step=%s",
                    self.agent.agent_name,
                    step + 1,
                )
                raise
            except Exception as exc:
                logger.exception(
                    "event=agent.run_failed agent=%s mode=normal step=%s max_steps=%s",
                    self.agent.agent_name,
                    step + 1,
                    self.agent.max_steps,
                )
                raise AgentExecutionError(
                    message=f"Step execution failed: {exc}",
                    agent_name=self.agent.agent_name,
                    step_count=step + 1,
                ) from exc

        raise AgentExecutionError(
            message=f"Exceeded maximum steps ({self.agent.max_steps})",
            agent_name=self.agent.agent_name,
            step_count=self.agent.max_steps,
        )

    async def run_stream(self) -> AsyncGenerator[AgentStreamChunk, None]:
        logger.info(
            "event=agent.run_stream_started agent=%s mode=normal",
            self.agent.agent_name,
        )
        if not self.agent.memory.has_role_message("user"):
            raise AgentExecutionError(
                message="No user message in memory. Append user input before run_stream().",
                agent_name=self.agent.agent_name,
            )

        if len(self.agent.tool_registry) == 0:
            async for chunk in self._run_stream_without_tools():
                yield chunk
            return

        for step in range(self.agent.max_steps):
            logger.debug(
                "event=agent.stream_step_started agent=%s step=%s max_steps=%s",
                self.agent.agent_name,
                step + 1,
                self.agent.max_steps,
            )
            try:
                async for chunk in self._run_stream_step(step + 1):
                    yield chunk
                    if chunk.is_complete:
                        return
            except asyncio.CancelledError:
                logger.info(
                    "event=agent.run_stream_canceled agent=%s step=%s",
                    self.agent.agent_name,
                    step + 1,
                )
                raise
            except Exception as exc:
                logger.exception(
                    "event=agent.run_stream_failed agent=%s step=%s max_steps=%s",
                    self.agent.agent_name,
                    step + 1,
                    self.agent.max_steps,
                )
                raise AgentExecutionError(
                    message=f"Stream step execution failed: {exc}",
                    agent_name=self.agent.agent_name,
                    step_count=step + 1,
                ) from exc

        raise AgentExecutionError(
            message=f"Exceeded maximum steps ({self.agent.max_steps})",
            agent_name=self.agent.agent_name,
            step_count=self.agent.max_steps,
        )

    async def _run_stream_without_tools(self) -> AsyncGenerator[AgentStreamChunk, None]:
        full_content = ""
        full_reasoning = ""
        last_model: str | None = None
        last_usage: dict[str, Any] | None = None
        assistant_appended = False

        messages = self.agent.build_messages_with_tool_guide()
        try:
            async for chunk in self.agent.llm.chat_stream(messages):
                self.agent.ensure_not_cancelled()
                if chunk.content_delta:
                    full_content += chunk.content_delta
                if chunk.reasoning_content_delta:
                    full_reasoning += chunk.reasoning_content_delta
                last_model = chunk.model or last_model
                if chunk.usage:
                    last_usage = chunk.usage
                yield AgentStreamChunk(
                    delta=chunk.content_delta or "",
                    reasoning_delta=chunk.reasoning_content_delta or "",
                )

            self.agent.ensure_not_cancelled()
            self.agent.memory.append_assistant_message(
                content=full_content,
                name=self.agent.agent_name,
                reasoning_content=full_reasoning or None,
            )
            assistant_appended = True
            if self.agent.save_trace:
                self.agent.save_trace_snapshot(
                    messages=self.agent.build_messages_with_tool_guide(),
                    llm_model=last_model,
                    usage=last_usage,
                    tools=self.agent.tool_registry.to_openai_format(),
                )
            yield AgentStreamChunk(
                delta="",
                is_complete=True,
                content=full_content,
            )
            logger.info(
                "event=agent.run_stream_completed agent=%s mode=normal step=1",
                self.agent.agent_name,
            )
        except asyncio.CancelledError:
            if self.agent.save_trace:
                self.agent.save_partial_trace_snapshot(
                    messages=(
                        self.agent.build_messages_with_tool_guide()
                        if assistant_appended
                        else messages
                    ),
                    llm_model=last_model,
                    usage=last_usage,
                    tools=self.agent.tool_registry.to_openai_format(),
                    assistant_content=(
                        None if assistant_appended else full_content or None
                    ),
                    assistant_reasoning_content=(
                        None if assistant_appended else full_reasoning or None
                    ),
                    step=1,
                )
            raise

    async def _run_stream_step(
        self,
        step: int,
    ) -> AsyncGenerator[AgentStreamChunk, None]:
        messages = self.agent.build_messages_with_tool_guide()
        tools = self.agent.tool_registry.to_openai_format()
        stream = self.agent.llm.chat_stream(messages, tools=tools)

        full_content = ""
        full_reasoning = ""
        final_tool_calls: list[ToolCallMessage] = []
        last_model: str | None = None
        last_usage: dict[str, Any] | None = None
        assistant_appended = False

        try:
            async for chunk in stream:
                self.agent.ensure_not_cancelled()
                if chunk.content_delta:
                    full_content += chunk.content_delta
                if chunk.reasoning_content_delta:
                    full_reasoning += chunk.reasoning_content_delta
                last_model = chunk.model or last_model
                if chunk.is_finished and chunk.tool_calls:
                    final_tool_calls = chunk.tool_calls
                if chunk.usage:
                    last_usage = chunk.usage
                yield AgentStreamChunk(
                    delta=chunk.content_delta or "",
                    reasoning_delta=chunk.reasoning_content_delta or "",
                    step=step,
                )

            self.agent.ensure_not_cancelled()
            self.agent.memory.append_assistant_message(
                content=None if final_tool_calls else full_content,
                name=self.agent.agent_name,
                tool_calls=final_tool_calls or None,
                reasoning_content=full_reasoning or None,
            )
            assistant_appended = True

            if self.agent.save_trace:
                self.agent.save_trace_snapshot(
                    messages=self.agent.build_messages_with_tool_guide(),
                    llm_model=last_model,
                    usage=last_usage,
                    tools=self.agent.tool_registry.to_openai_format(),
                )

            if final_tool_calls:
                async for chunk in self._execute_stream_tools(final_tool_calls, step):
                    yield chunk
                return

            logger.info(
                "event=agent.run_stream_completed agent=%s mode=normal step=%s",
                self.agent.agent_name,
                step,
            )
            yield AgentStreamChunk(
                delta="",
                is_complete=True,
                content=full_content,
                step=step,
            )
        except asyncio.CancelledError:
            if self.agent.save_trace:
                self.agent.save_partial_trace_snapshot(
                    messages=(
                        self.agent.build_messages_with_tool_guide()
                        if assistant_appended
                        else messages
                    ),
                    llm_model=last_model,
                    usage=last_usage,
                    tools=self.agent.tool_registry.to_openai_format(),
                    assistant_content=(
                        None if assistant_appended else full_content or None
                    ),
                    assistant_reasoning_content=(
                        None if assistant_appended else full_reasoning or None
                    ),
                    assistant_tool_calls=(
                        None if assistant_appended else final_tool_calls
                    ),
                    step=step,
                )
            raise

    async def _execute_stream_tools(
        self,
        final_tool_calls: list[ToolCallMessage],
        step: int,
    ) -> AsyncGenerator[AgentStreamChunk, None]:
        self.agent.ensure_not_cancelled()
        logger.debug(
            "event=agent.stream_tool_calls_received agent=%s step=%s tool_call_count=%s",
            self.agent.agent_name,
            step,
            len(final_tool_calls),
        )
        tool_ctx = {
            **self.agent.tool_context,
            "_caller_agent_name": self.agent.agent_name,
            "_caller_trace_id": (
                self.agent.trace_ids[-1] if self.agent.trace_ids else None
            ),
        }
        for tool_call in final_tool_calls:
            self.agent.ensure_not_cancelled()
            tool_msg = await self.agent.tool_registry.execute_tool_call(
                tool_call,
                context=tool_ctx,
            )
            self.agent.memory.append_tool_message(tool_msg)
            yield AgentStreamChunk(
                delta="",
                tool_call_name=tool_call.function.name,
                tool_call=tool_call.model_dump(mode="json"),
                tool_result={
                    "tool_call_id": tool_msg.tool_call_id,
                    "name": tool_msg.name,
                    "content": tool_msg.content,
                },
                step=step,
            )
