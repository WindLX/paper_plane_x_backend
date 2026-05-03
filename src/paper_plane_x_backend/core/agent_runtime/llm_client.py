"""LLM 客户端封装.

基于 LiteLLM 的统一接口，按能力封装模型调用。
"""

import logging
from collections.abc import AsyncIterator
from typing import Any, Literal, TypeVar, cast

from litellm import acompletion  # pyright: ignore[reportUnknownVariableType]
from pydantic import BaseModel, Field

from paper_plane_x_backend.models.app_settings import LLMConfig
from paper_plane_x_backend.schemas.agent_io.base import (
    ToolCallFunction,
    ToolCallMessage,
)
from paper_plane_x_backend.services.app_settings import get_app_settings_repo

logger = logging.getLogger(__name__)

OutputType = TypeVar("OutputType", bound=BaseModel)


class LLMResponse(BaseModel):
    """LLM 响应包装类."""

    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[ToolCallMessage] = Field(
        default_factory=lambda: cast(list[ToolCallMessage], [])
    )
    model: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


class LLMStreamChunk(BaseModel):
    """LLM 流式响应块."""

    content_delta: str | None = None
    reasoning_content_delta: str | None = None
    tool_calls: list[ToolCallMessage] = Field(
        default_factory=lambda: cast(list[ToolCallMessage], [])
    )
    model: str | None = None
    is_finished: bool = False


class LLMClient:
    """LLM 客户端.

    封装 LiteLLM 调用，提供统一的异步接口。
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float = 600.0,
        custom_headers: dict[str, str] | None = None,
        thinking_enabled: bool = False,
        reasoning_effort: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ):
        app_llm = get_app_settings_repo().get().llm
        self.model = model or app_llm.model
        self.api_key = api_key or app_llm.api_key
        self.base_url = base_url or app_llm.base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.custom_headers = custom_headers or {}
        self.thinking_enabled = thinking_enabled
        self.reasoning_effort = reasoning_effort
        self.extra_body = extra_body or {}

    @classmethod
    def from_config(cls, config: LLMConfig) -> "LLMClient":
        return cls(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
            custom_headers=config.custom_headers,
            thinking_enabled=config.thinking_enabled,
            reasoning_effort=config.reasoning_effort,
            extra_body=config.extra_body,
        )

    def _parse_response(self, response: Any) -> LLMResponse:
        message = response.choices[0].message
        raw_tool_calls: Any = getattr(message, "tool_calls", None)

        tool_calls: list[ToolCallMessage] = []
        if isinstance(raw_tool_calls, list):
            for tc in cast(list[Any], raw_tool_calls):
                tc_id = getattr(tc, "id", None)
                function = getattr(tc, "function", None)
                fn_name = getattr(function, "name", None)
                fn_arguments = getattr(function, "arguments", None)

                if not isinstance(tc_id, str):
                    continue
                if not isinstance(fn_name, str):
                    continue

                normalized_arguments: str | dict[str, Any]
                if isinstance(fn_arguments, str):
                    normalized_arguments = fn_arguments
                elif isinstance(fn_arguments, dict):
                    normalized_arguments = {
                        key: value
                        for key, value in cast(dict[Any, Any], fn_arguments).items()
                        if isinstance(key, str)
                    }
                else:
                    continue

                tool_calls.append(
                    ToolCallMessage(
                        id=tc_id,
                        type="function",
                        function=ToolCallFunction(
                            name=fn_name,
                            arguments=normalized_arguments,
                        ),
                    )
                )

        usage = dict(response.usage) if getattr(response, "usage", None) else {}
        reasoning_content = getattr(message, "reasoning_content", None)
        return LLMResponse(
            content=message.content,
            reasoning_content=(
                reasoning_content if isinstance(reasoning_content, str) else None
            ),
            tool_calls=tool_calls,
            model=getattr(response, "model", None),
            usage=usage,
        )

    def _resolve_model_provider(self) -> tuple[str, str | None]:
        """推断 LiteLLM provider.

        LiteLLM 需要可识别的 provider。对于自建/代理的 OpenAI 兼容网关，
        常见配置是裸模型名（如 deepseek-chat）+ base_url，此时需要显式指定
        custom_llm_provider=openai。
        """
        if "/" in self.model:
            return self.model, None

        if self.base_url:
            return self.model, "openai"

        return self.model, None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        output_schema: type[OutputType] | None = None,
        tool_choice: Literal["auto"] = "auto",
        **kwargs: Any,
    ) -> LLMResponse:
        resolved_model, custom_provider = self._resolve_model_provider()
        logger.debug(
            "event=llm.request model=%s provider=%s message_count=%s tool_count=%s structured=%s reasoning_effort=%s",
            resolved_model,
            custom_provider,
            len(messages),
            0 if tools is None else len(tools),
            output_schema is not None,
            self.reasoning_effort if self.thinking_enabled else "disabled",
        )
        request: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": kwargs.pop("temperature", self.temperature),
            "max_tokens": kwargs.pop("max_tokens", self.max_tokens),
            "timeout": kwargs.pop("timeout", self.timeout),
            "headers": self.custom_headers or None,
        }

        if custom_provider is not None:
            request["custom_llm_provider"] = custom_provider

        if tools is not None:
            request["tools"] = tools
            request["tool_choice"] = tool_choice

        if output_schema is not None:
            request["response_format"] = {
                "type": "json_object",
                "schema": output_schema.model_json_schema(),
            }

        request_extra_body = dict(self.extra_body)
        if self.thinking_enabled:
            request_extra_body.setdefault("thinking", {"type": "enabled"})

        kwargs_extra_body = kwargs.pop("extra_body", None)
        if isinstance(kwargs_extra_body, dict):
            request_extra_body.update(cast(dict[str, Any], kwargs_extra_body))

        if request_extra_body:
            request["extra_body"] = request_extra_body

        reasoning_effort = kwargs.pop("reasoning_effort", self.reasoning_effort)
        if reasoning_effort is not None:
            request["reasoning_effort"] = reasoning_effort
            allowed_openai_params = kwargs.pop("allowed_openai_params", None)
            merged_allowed_openai_params: list[str] = []
            if isinstance(allowed_openai_params, list):
                merged_allowed_openai_params.extend(
                    item
                    for item in cast(list[Any], allowed_openai_params)
                    if isinstance(item, str)
                )
            if "reasoning_effort" not in merged_allowed_openai_params:
                merged_allowed_openai_params.append("reasoning_effort")
            request["allowed_openai_params"] = merged_allowed_openai_params

        request.update(kwargs)
        response = await acompletion(**request)
        parsed = self._parse_response(response)
        logger.debug(
            "event=llm.response model=%s reasoning_effort=%s has_content=%s tool_call_count=%s usage=%s ",
            parsed.model or self.model,
            self.reasoning_effort if self.thinking_enabled else "disabled",
            bool(parsed.content),
            len(parsed.tool_calls),
            parsed.usage,
        )
        return parsed

    async def generate(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        return await self.chat(messages, **kwargs)

    async def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        return await self.chat(messages, tools=tools, tool_choice="auto", **kwargs)

    async def generate_structured(
        self,
        messages: list[dict[str, Any]],
        output_schema: type[OutputType],
        **kwargs: Any,
    ) -> LLMResponse:
        return await self.chat(messages, output_schema=output_schema, **kwargs)

    def _build_request(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        output_schema: type[OutputType] | None = None,
        tool_choice: Literal["auto"] = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """构建 LiteLLM 请求参数（chat / chat_stream 共用）."""
        resolved_model, custom_provider = self._resolve_model_provider()
        request: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": kwargs.pop("temperature", self.temperature),
            "max_tokens": kwargs.pop("max_tokens", self.max_tokens),
            "timeout": kwargs.pop("timeout", self.timeout),
            "headers": self.custom_headers or None,
        }

        if custom_provider is not None:
            request["custom_llm_provider"] = custom_provider

        if tools is not None:
            request["tools"] = tools
            request["tool_choice"] = tool_choice

        if output_schema is not None:
            request["response_format"] = {
                "type": "json_object",
                "schema": output_schema.model_json_schema(),
            }

        request_extra_body = dict(self.extra_body)
        if self.thinking_enabled:
            request_extra_body.setdefault("thinking", {"type": "enabled"})

        kwargs_extra_body = kwargs.pop("extra_body", None)
        if isinstance(kwargs_extra_body, dict):
            request_extra_body.update(cast(dict[str, Any], kwargs_extra_body))

        if request_extra_body:
            request["extra_body"] = request_extra_body

        reasoning_effort = kwargs.pop("reasoning_effort", self.reasoning_effort)
        if reasoning_effort is not None:
            request["reasoning_effort"] = reasoning_effort
            allowed_openai_params = kwargs.pop("allowed_openai_params", None)
            merged_allowed_openai_params: list[str] = []
            if isinstance(allowed_openai_params, list):
                merged_allowed_openai_params.extend(
                    item
                    for item in cast(list[Any], allowed_openai_params)
                    if isinstance(item, str)
                )
            if "reasoning_effort" not in merged_allowed_openai_params:
                merged_allowed_openai_params.append("reasoning_effort")
            request["allowed_openai_params"] = merged_allowed_openai_params

        request.update(kwargs)
        return request

    @staticmethod
    def _parse_stream_tool_calls(
        raw_chunks: list[dict[str, Any]],
    ) -> list[ToolCallMessage]:
        """将流式累积的原始 tool_calls 解析为标准格式."""
        tool_calls: list[ToolCallMessage] = []
        for raw in raw_chunks:
            tc_id = raw.get("id")
            fn = raw.get("function", {})
            fn_name = fn.get("name")
            fn_args = fn.get("arguments")
            if not isinstance(tc_id, str) or not isinstance(fn_name, str):
                continue
            args: str | dict[str, Any]
            if isinstance(fn_args, str):
                args = fn_args
            elif isinstance(fn_args, dict):
                args = {k: v for k, v in fn_args.items() if isinstance(k, str)}
            else:
                continue
            tool_calls.append(
                ToolCallMessage(
                    id=tc_id,
                    type="function",
                    function=ToolCallFunction(name=fn_name, arguments=args),
                )
            )
        return tool_calls

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        """流式调用 LLM，逐块 yield 增量内容."""
        request = self._build_request(messages, tools=tools, **kwargs)
        request["stream"] = True

        logger.debug(
            "event=llm.stream_request model=%s tool_count=%s",
            request["model"],
            0 if tools is None else len(tools),
        )

        response = await acompletion(**request)
        last_model: str | None = None

        # 流式 tool_calls 需要按 index 累积
        indexed_tool_calls: dict[int, dict[str, Any]] = {}
        content_buffer = ""
        reasoning_buffer = ""

        # acompletion(stream=True) 返回可异步迭代的 CustomStreamWrapper，
        # 但 LiteLLM 类型签名标注为 ModelResponse，需忽略类型检查。
        async for chunk in response:  # type: ignore[var-annotated]
            choice = chunk.choices[0]
            delta = choice.delta
            last_model = getattr(chunk, "model", None) or last_model

            content_delta = getattr(delta, "content", None)
            if isinstance(content_delta, str):
                content_buffer += content_delta

            reasoning_delta = getattr(delta, "reasoning_content", None)
            if isinstance(reasoning_delta, str):
                reasoning_buffer += reasoning_delta

            # 累积流式 tool_calls
            raw_tcs = getattr(delta, "tool_calls", None)
            if isinstance(raw_tcs, list):
                for tc in raw_tcs:
                    idx = getattr(tc, "index", None)
                    if isinstance(idx, int):
                        entry = indexed_tool_calls.setdefault(idx, {})
                        if not entry:
                            entry["id"] = getattr(tc, "id", None) or ""
                            entry["type"] = "function"
                            entry["function"] = {"name": "", "arguments": ""}
                        func_delta = getattr(tc, "function", None)
                        if func_delta:
                            name_part = getattr(func_delta, "name", None)
                            if isinstance(name_part, str):
                                entry["function"]["name"] += name_part
                            args_part = getattr(func_delta, "arguments", None)
                            if isinstance(args_part, str):
                                entry["function"]["arguments"] += args_part

            is_finished = choice.finish_reason is not None

            if is_finished and indexed_tool_calls:
                sorted_tcs = [
                    indexed_tool_calls[i] for i in sorted(indexed_tool_calls.keys())
                ]
                yield LLMStreamChunk(
                    content_delta=content_delta,
                    reasoning_content_delta=reasoning_delta,
                    tool_calls=self._parse_stream_tool_calls(sorted_tcs),
                    model=last_model,
                    is_finished=True,
                )
            else:
                yield LLMStreamChunk(
                    content_delta=content_delta,
                    reasoning_content_delta=reasoning_delta,
                    model=last_model,
                    is_finished=is_finished,
                )
