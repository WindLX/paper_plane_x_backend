"""LLM 客户端封装.

基于 LiteLLM 的统一接口，按能力封装模型调用。
"""

import logging
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any, Literal, Protocol, TypeVar, cast

from litellm import acompletion  # pyright: ignore[reportUnknownVariableType]
from pydantic import BaseModel, Field

from paper_plane_x_backend.models.app_settings import LLMConfig
from paper_plane_x_backend.schemas.agent_io.base import (
    ToolCallFunction,
    ToolCallMessage,
)

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
    usage: dict[str, Any] = Field(default_factory=dict)


class LLMClient:
    """LLM 客户端.

    封装 LiteLLM 调用，提供统一的异步接口。
    """

    def __init__(
        self,
        model: str,
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
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
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

    def _extract_usage(self, response: Any) -> dict[str, Any]:
        """从 LLM 响应中安全提取 usage 信息.

        LiteLLM 不同 provider 返回的 usage 对象类型不一：
        - Pydantic v1 BaseModel（OpenAI 等）
        - Pydantic v2 BaseModel
        - dict
        - None
        """
        raw_usage = getattr(response, "usage", None)
        return self._normalize_usage(raw_usage)

    @staticmethod
    def _normalize_usage(raw_usage: Any) -> dict[str, Any]:
        """将不同形态的 usage 统一转成 dict."""
        if raw_usage is None:
            return {}

        # Pydantic v2
        if hasattr(raw_usage, "model_dump") and callable(raw_usage.model_dump):
            try:
                dumped = raw_usage.model_dump()
                if isinstance(dumped, dict):
                    return cast(dict[str, Any], dumped)
            except Exception:
                pass

        # Pydantic v1 / 一般对象的 dict() 方法
        if hasattr(raw_usage, "dict") and callable(raw_usage.dict):
            try:
                dumped = raw_usage.dict()
                if isinstance(dumped, dict):
                    return cast(dict[str, Any], dumped)
            except Exception:
                pass

        # 普通 dict
        if isinstance(raw_usage, dict):
            return cast(dict[str, Any], raw_usage)

        # 最后回退到属性探测，兼容 LiteLLM/Provider 自定义 usage 对象
        known_fields = [
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        ]
        extracted: dict[str, Any] = {}
        for field in known_fields:
            value = getattr(raw_usage, field, None)
            if value is not None:
                extracted[field] = value
        return extracted

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

        usage = self._extract_usage(response)
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
                args = {
                    k: v
                    for k, v in cast(dict[Any, Any], fn_args).items()
                    if isinstance(k, str)
                }
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
        request["stream_options"] = {"include_usage": True}

        logger.debug(
            "event=llm.stream_request model=%s provider=%s base_url=%s message_count=%s tool_count=%s timeout=%s",
            request["model"],
            request.get("custom_llm_provider"),
            request.get("base_url"),
            len(messages),
            0 if tools is None else len(tools),
            request.get("timeout"),
        )

        request_started_at = perf_counter()
        try:
            response = await acompletion(**request)
        except Exception:
            logger.exception(
                "event=llm.stream_request_failed model=%s provider=%s base_url=%s message_count=%s tool_count=%s elapsed_ms=%.1f",
                request["model"],
                request.get("custom_llm_provider"),
                request.get("base_url"),
                len(messages),
                0 if tools is None else len(tools),
                (perf_counter() - request_started_at) * 1000,
            )
            raise

        request_ready_elapsed_ms = (perf_counter() - request_started_at) * 1000
        logger.debug(
            "event=llm.stream_response_ready model=%s provider=%s elapsed_ms=%.1f",
            request["model"],
            request.get("custom_llm_provider"),
            request_ready_elapsed_ms,
        )
        last_model: str | None = None
        last_usage: dict[str, Any] = {}
        first_chunk_elapsed_ms: float | None = None

        # 流式 tool_calls 需要按 index 累积
        indexed_tool_calls: dict[int, dict[str, Any]] = {}
        content_buffer = ""
        reasoning_buffer = ""
        chunk_index = 0

        # acompletion(stream=True) 返回可异步迭代的 CustomStreamWrapper，
        # 但 LiteLLM 类型签名标注为 ModelResponse，需忽略类型检查。
        class _DeltaLike(Protocol):
            content: object
            reasoning_content: object
            tool_calls: object

        class _ChoiceLike(Protocol):
            delta: _DeltaLike
            finish_reason: object

        class _ChunkLike(Protocol):
            choices: list[_ChoiceLike]
            model: object

        try:
            async for chunk in cast(AsyncIterator[_ChunkLike], response):
                chunk_index += 1
                if first_chunk_elapsed_ms is None:
                    first_chunk_elapsed_ms = (
                        perf_counter() - request_started_at
                    ) * 1000
                    logger.debug(
                        "event=llm.stream_first_chunk model=%s provider=%s elapsed_ms=%.1f",
                        request["model"],
                        request.get("custom_llm_provider"),
                        first_chunk_elapsed_ms,
                    )
                chunk_model = chunk.model
                last_model = chunk_model if isinstance(chunk_model, str) else last_model

                # 提取 usage（stream_options 开启后最后一个 chunk 会携带）
                raw_usage = getattr(chunk, "usage", None)
                chunk_usage = self._normalize_usage(raw_usage)
                if chunk_usage:
                    last_usage = chunk_usage

                choice_count = len(chunk.choices)
                finish_reason = None
                if chunk.choices:
                    finish_reason = getattr(chunk.choices[0], "finish_reason", None)
                usage_keys = sorted(chunk_usage.keys())

                if chunk_index % 10 == 0:
                    logger.debug(
                        "event=llm.stream_chunk_summary model=%s chunk_index=%s choices_len=%s finish_reason=%s has_usage=%s usage_type=%s usage_keys=%s",
                        last_model or request["model"],
                        chunk_index,
                        choice_count,
                        finish_reason,
                        bool(chunk_usage),
                        type(raw_usage).__name__ if raw_usage is not None else None,
                        usage_keys,
                    )

                if not chunk.choices:
                    if chunk_usage:
                        logger.debug(
                            "event=llm.stream_usage_chunk model=%s usage=%s",
                            last_model or request["model"],
                            chunk_usage,
                        )
                        yield LLMStreamChunk(
                            model=last_model,
                            usage=chunk_usage,
                        )
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                content_delta = getattr(delta, "content", None)
                if isinstance(content_delta, str):
                    content_buffer += content_delta

                reasoning_delta = getattr(delta, "reasoning_content", None)
                if isinstance(reasoning_delta, str):
                    reasoning_buffer += reasoning_delta

                # 累积流式 tool_calls
                raw_tcs = getattr(delta, "tool_calls", None)
                if isinstance(raw_tcs, list):
                    for tc in cast(list[Any], raw_tcs):
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
                        usage=last_usage,
                    )
                else:
                    yield LLMStreamChunk(
                        content_delta=content_delta,
                        reasoning_content_delta=reasoning_delta,
                        model=last_model,
                        is_finished=is_finished,
                        usage=chunk_usage or (last_usage if is_finished else {}),
                    )
        except Exception:
            logger.exception(
                "event=llm.stream_iteration_failed model=%s provider=%s chunk_index=%s first_chunk_elapsed_ms=%s total_elapsed_ms=%.1f",
                request["model"],
                request.get("custom_llm_provider"),
                chunk_index,
                None
                if first_chunk_elapsed_ms is None
                else round(first_chunk_elapsed_ms, 1),
                (perf_counter() - request_started_at) * 1000,
            )
            raise

        logger.debug(
            "event=llm.stream_completed model=%s provider=%s chunk_count=%s first_chunk_elapsed_ms=%s total_elapsed_ms=%.1f content_chars=%s reasoning_chars=%s tool_call_count=%s usage_keys=%s",
            last_model or request["model"],
            request.get("custom_llm_provider"),
            chunk_index,
            None
            if first_chunk_elapsed_ms is None
            else round(first_chunk_elapsed_ms, 1),
            (perf_counter() - request_started_at) * 1000,
            len(content_buffer),
            len(reasoning_buffer),
            len(indexed_tool_calls),
            sorted(last_usage.keys()),
        )
