"""Agent 基类实现.

实现可复用的 BaseAgent 框架，支持结构化输出和 ReAct 循环。
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from paper_plane_x_backend.core.agent_runtime.exceptions import (
    AgentExecutionError,
    AgentValidationError,
)
from paper_plane_x_backend.core.agent_runtime.llm_client import LLMClient
from paper_plane_x_backend.core.agent_runtime.memory import MemoryManager
from paper_plane_x_backend.core.agent_runtime.normal_mode import NormalAgentRunner
from paper_plane_x_backend.core.agent_runtime.output_validation import (
    validate_output_content,
)
from paper_plane_x_backend.core.agent_runtime.stream_types import AgentStreamChunk
from paper_plane_x_backend.core.agent_runtime.tooling import Tool, ToolRegistry
from paper_plane_x_backend.models import AgentTrace
from paper_plane_x_backend.models.app_settings import LLMConfig
from paper_plane_x_backend.schemas.agent_io.base import (
    AssistantMessage,
    ToolCallMessage,
)
from paper_plane_x_backend.services import get_db
from paper_plane_x_backend.services.agent_trace.repository import (
    AgentTraceRepository,
)
from paper_plane_x_backend.utils.ids import generate_trace_id

logger = logging.getLogger(__name__)

AgentMode = Literal["api", "normal"]


class BaseAgent:
    """Agent 基类.

    支持两种模式：
    1) api 模式: 强制结构化输出（通过 LLM generate_structured）
    2) normal 模式: 自由文本输出，可进行工具调用循环
    """

    def __init__(
        self,
        output_schema: type[BaseModel] | None = None,
        mode: AgentMode = "api",
        system_prompt: str | None = None,
        tools: list[Tool] | None = None,
        max_steps: int = 10,
        save_trace: bool = True,
        short_memory_window: int = 50,
        llm_config: LLMConfig | None = None,
        agent_name: str | None = None,
        tool_context: dict[str, Any] | None = None,
        caller: str | None = None,
        caller_id: str | None = None,
    ):
        if mode == "api" and output_schema is None:
            raise ValueError("output_schema is required when mode='api'")

        self.output_schema = output_schema
        self.mode: AgentMode = mode
        self.max_steps = max_steps
        self.save_trace = save_trace
        self.agent_name = agent_name or self.__class__.__name__
        self.trace_ids: list[str] = []
        self.tool_context = tool_context or {}
        self.caller = caller
        self.caller_id = caller_id
        self._cancel_event = asyncio.Event()

        self.tool_registry = ToolRegistry()
        if tools:
            for tool in tools:
                self.tool_registry.register(tool)

        rendered_system_prompt = self.tool_registry.inject_shared_guide_into_system_prompt(
            system_prompt or ""
        )

        if llm_config is None:
            raise ValueError(
                "llm_config is required. "
                "Please configure the agent's LLM settings first."
            )
        self.llm = LLMClient.from_config(llm_config)
        self.memory = MemoryManager(
            system_prompt=rendered_system_prompt,
            short_memory_window=short_memory_window,
            is_vlm=llm_config.is_vlm,
        )

    def _get_output_schema(self) -> type[BaseModel]:
        if self.output_schema is None:
            raise AgentExecutionError(
                message="output_schema is not configured for this agent",
                agent_name=self.agent_name,
            )
        return self.output_schema

    def build_messages_with_tool_guide(self) -> list[dict[str, Any]]:
        """返回已渲染共享 guide 的消息列表."""
        return self.memory.get_messages()

    def _validate_output(self, content: str) -> BaseModel:
        return validate_output_content(
            content,
            output_schema=self._get_output_schema(),
            agent_name=self.agent_name,
        )

    def _save_trace(
        self,
        messages: list[dict[str, Any]],
        *,
        llm_model: str | None = None,
        usage: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        try:
            db = get_db()
            repo = AgentTraceRepository(db)
            usage = usage or {}
            prompt_tokens, completion_tokens, total_tokens = self._extract_token_counts(
                usage
            )
            trace_id = generate_trace_id()
            trace = AgentTrace(
                trace_id=trace_id,
                agent_name=self.agent_name,
                messages=messages,
                llm_model=llm_model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                usage_payload=usage or None,
                tools=tools,
                caller=self.caller,
                caller_id=self.caller_id,
                created_at=datetime.now(),
            )
            repo.create(trace)
            self.trace_ids.append(trace_id)
        except Exception as e:
            logger.warning(
                "event=agent.trace_save_failed agent=%s error=%s",
                self.agent_name,
                e,
            )

    @staticmethod
    def _extract_token_counts(
        usage: dict[str, Any],
    ) -> tuple[int | None, int | None, int | None]:
        def _as_int(value: Any) -> int | None:
            return value if isinstance(value, int) else None

        prompt_tokens = _as_int(usage.get("prompt_tokens"))
        if prompt_tokens is None:
            prompt_tokens = _as_int(usage.get("input_tokens"))

        completion_tokens = _as_int(usage.get("completion_tokens"))
        if completion_tokens is None:
            completion_tokens = _as_int(usage.get("output_tokens"))

        total_tokens = _as_int(usage.get("total_tokens"))
        if total_tokens is None:
            if prompt_tokens is not None and completion_tokens is not None:
                total_tokens = prompt_tokens + completion_tokens

        return prompt_tokens, completion_tokens, total_tokens

    def save_trace_snapshot(
        self,
        messages: list[dict[str, Any]],
        *,
        llm_model: str | None = None,
        usage: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        """为执行器提供 trace 持久化入口."""
        self._save_trace(
            messages,
            llm_model=llm_model,
            usage=usage,
            tools=tools,
        )

    def _build_partial_trace_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        assistant_content: str | None = None,
        assistant_reasoning_content: str | None = None,
        assistant_tool_calls: list[ToolCallMessage] | None = None,
    ) -> list[dict[str, Any]]:
        trace_messages = [dict(message) for message in messages]
        has_partial_assistant = (
            assistant_content is not None
            or assistant_reasoning_content is not None
            or bool(assistant_tool_calls)
        )
        if has_partial_assistant:
            trace_messages.append(
                AssistantMessage(
                    content=assistant_content,
                    reasoning_content=assistant_reasoning_content,
                    name=self.agent_name,
                    tool_calls=assistant_tool_calls,
                ).model_dump(exclude_none=True)
            )
        return trace_messages

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
    ) -> None:
        trace_messages = self._build_partial_trace_messages(
            messages,
            assistant_content=assistant_content,
            assistant_reasoning_content=assistant_reasoning_content,
            assistant_tool_calls=assistant_tool_calls,
        )
        trace_usage = dict(usage or {})
        trace_meta: dict[str, Any] = {
            "status": "cancelled",
            "partial": True,
            "reason": cancel_reason,
        }
        if step is not None:
            trace_meta["step"] = step
        existing_trace_meta = trace_usage.get("_trace")
        if isinstance(existing_trace_meta, dict):
            trace_meta = {
                **existing_trace_meta,
                **trace_meta,
            }
        trace_usage["_trace"] = trace_meta
        self._save_trace(
            trace_messages,
            llm_model=llm_model,
            usage=trace_usage,
            tools=tools,
        )

    async def _run_api(self) -> BaseModel:
        logger.info(
            "event=agent.run_started agent=%s mode=api",
            self.agent_name,
        )
        if not self.memory.has_role_message("user"):
            raise AgentExecutionError(
                message="No user message in memory. Append user input before run().",
                agent_name=self.agent_name,
            )
        output_schema = self._get_output_schema()
        last_validation_error: AgentValidationError | None = None
        validated_output = None

        for step in range(self.max_steps):
            content = ""
            reasoning_content = None
            try:
                logger.debug(
                    "event=agent.step_started agent=%s mode=api step=%s max_steps=%s",
                    self.agent_name,
                    step + 1,
                    self.max_steps,
                )
                response = await self.llm.generate_structured(
                    messages=self.build_messages_with_tool_guide(),
                    output_schema=output_schema,
                )
                content = response.content or ""
                reasoning_content = response.reasoning_content
                self.memory.append_assistant_message(
                    content=content,
                    name=self.agent_name,
                    reasoning_content=reasoning_content,
                )

                if self.save_trace:
                    self._save_trace(
                        messages=self.build_messages_with_tool_guide(),
                        llm_model=response.model,
                        usage=response.usage,
                        tools=self.tool_registry.to_openai_format(),
                    )

                validated_output = self._validate_output(content)

                logger.info(
                    "event=agent.run_completed agent=%s mode=api step=%s",
                    self.agent_name,
                    step + 1,
                )
                break
            except AgentValidationError as e:
                last_validation_error = e
                logger.warning(
                    "event=agent.validation_retry agent=%s step=%s max_steps=%s error=%s",
                    self.agent_name,
                    step + 1,
                    self.max_steps,
                    e.message,
                )

                error_detail = e.validation_errors if e.validation_errors else e.message
                self.memory.append_validation_feedback(error_detail)
            except asyncio.CancelledError:
                if self.save_trace:
                    self.save_partial_trace_snapshot(
                        messages=self.build_messages_with_tool_guide(),
                        usage=None,
                        tools=self.tool_registry.to_openai_format(),
                        assistant_content=content or None,
                        assistant_reasoning_content=reasoning_content,
                        step=step + 1,
                    )
                logger.info(
                    "event=agent.run_canceled agent=%s mode=api step=%s",
                    self.agent_name,
                    step + 1,
                )
                raise
            except Exception as e:
                logger.exception(
                    "event=agent.run_failed agent=%s mode=api step=%s max_steps=%s",
                    self.agent_name,
                    step + 1,
                    self.max_steps,
                )
                raise AgentExecutionError(
                    message=f"API mode execution failed: {e}",
                    agent_name=self.agent_name,
                ) from e

        if validated_output is not None:
            return validated_output

        if last_validation_error is not None:
            raise last_validation_error

        raise AgentExecutionError(
            message=f"Exceeded maximum steps ({self.max_steps})",
            agent_name=self.agent_name,
            step_count=self.max_steps,
        )

    async def _run_normal(self) -> str:
        return await NormalAgentRunner(self).run()

    async def run(self) -> BaseModel | str:
        self.trace_ids = []
        if self.mode == "api":
            return await self._run_api()
        return await self._run_normal()

    def get_memory_messages(self) -> list[dict[str, Any]]:
        """获取当前 memory 中的所有交互消息（不含 system prompt）。"""
        return self.memory.get_interaction_messages()

    def cancel(self) -> None:
        """请求取消当前 agent 的运行。"""
        self._cancel_event.set()

    def _check_cancelled(self) -> None:
        """检查是否已被请求取消，如果是则抛出 CancelledError。"""
        if self._cancel_event.is_set():
            raise asyncio.CancelledError("Agent execution cancelled by user")

    def ensure_not_cancelled(self) -> None:
        """为执行器提供取消检查入口."""
        self._check_cancelled()

    async def run_stream(self) -> AsyncGenerator[AgentStreamChunk, None]:
        """流式执行 agent（仅支持 normal 模式）.

        Yields:
            AgentStreamChunk: 每块增量内容；最终块 is_complete=True。
        """
        self.trace_ids = []
        self._cancel_event.clear()
        if self.mode == "api":
            raise AgentExecutionError(
                message="run_stream only supports normal mode",
                agent_name=self.agent_name,
            )
        async for chunk in self._run_normal_stream():
            self._check_cancelled()
            yield chunk

    async def _run_normal_stream(self) -> AsyncGenerator[AgentStreamChunk, None]:
        """normal 模式流式执行（内部 ReAct 循环，逐 token 透传）."""
        async for chunk in NormalAgentRunner(self).run_stream():
            yield chunk
