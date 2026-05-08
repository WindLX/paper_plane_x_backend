"""工具基类与注册机制.

提供 Agent 可调用的工具定义和注册机制。
"""

import inspect
import json
import logging
from types import UnionType
from typing import (
    Any,
    Callable,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel, ConfigDict, Field

from paper_plane_x_backend.schemas.agent_io.base import ToolCallMessage, ToolMessage

logger = logging.getLogger(__name__)

TOOLSET_SHARED_GUIDE_PLACEHOLDER = "{{TOOLSET_SHARED_GUIDE}}"


class Tool(BaseModel):
    """工具描述模型."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., description="工具唯一名称")
    description: str = Field(..., description="工具功能描述（LLM 使用）")
    parameters: dict[str, Any] = Field(..., description="参数 JSON Schema")
    function: Callable[..., Any] | None = Field(
        default=None,
        exclude=True,
        description="实际执行的函数",
    )
    bound_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        exclude=True,
        description="对 LLM 隐藏、在执行时自动注入的固定参数",
    )
    context_params: dict[str, str] = Field(
        default_factory=dict,
        exclude=True,
        description="参数名到上下文键名的映射，执行时从上下文自动注入",
    )
    shared_guides: dict[str, str] = Field(
        default_factory=dict,
        exclude=True,
        description="当前工具依赖的共享说明片段，由 registry 聚合为公共 guide",
    )

    def to_openai_format(self) -> dict[str, Any]:
        """转换为 OpenAI 描述格式."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(
        self,
        *,
        runtime_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        if self.function is None:
            raise RuntimeError(f"Tool '{self.name}' has no bound function")

        merged_kwargs = dict(kwargs)
        for key, value in self.bound_kwargs.items():
            merged_kwargs[key] = value

        for param_name, context_key in self.context_params.items():
            if runtime_context is None or context_key not in runtime_context:
                raise RuntimeError(
                    f"Tool '{self.name}' requires hidden context key '{context_key}'"
                )
            merged_kwargs[param_name] = runtime_context[context_key]

        if inspect.iscoroutinefunction(self.function):
            return await self.function(**merged_kwargs)
        return self.function(**merged_kwargs)


class ToolRegistry:
    """工具注册表."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._shared_guides: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            logger.warning(
                "event=tool.register_rejected_duplicate tool_name=%s", tool.name
            )
            raise ValueError(f"Tool '{tool.name}' already registered")

        for guide_name, guide_content in tool.shared_guides.items():
            existing = self._shared_guides.get(guide_name)
            if existing is not None and existing != guide_content:
                logger.warning(
                    "event=tool.register_conflicting_shared_guide tool_name=%s guide_name=%s",
                    tool.name,
                    guide_name,
                )
                raise ValueError(
                    f"Shared guide '{guide_name}' already exists with different content"
                )
            self._shared_guides[guide_name] = guide_content

        self._tools[tool.name] = tool
        logger.debug("event=tool.registered tool_name=%s", tool.name)

    def unregister(self, tool_name: str) -> None:
        if tool_name in self._tools:
            self._tools.pop(tool_name)
            logger.debug("event=tool.unregistered tool_name=%s", tool_name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def to_openai_format(self) -> list[dict[str, Any]]:
        return [tool.to_openai_format() for tool in self._tools.values()]

    def build_shared_guide_message(self) -> str:
        if not self._shared_guides:
            return ""

        sections: list[str] = ["Toolset Shared Guide:"]
        for guide_name, guide_content in self._shared_guides.items():
            sections.append(f"[{guide_name}]")
            sections.append(guide_content.strip())
        return "\n\n".join(sections).strip()

    def inject_shared_guide_into_system_prompt(self, system_prompt: str) -> str:
        """将共享 guide 渲染到唯一的 system prompt 中."""
        shared_guide = self.build_shared_guide_message()
        if TOOLSET_SHARED_GUIDE_PLACEHOLDER in system_prompt:
            return system_prompt.replace(
                TOOLSET_SHARED_GUIDE_PLACEHOLDER,
                shared_guide,
            )

        if not shared_guide:
            return system_prompt

        logger.warning(
            "event=tool.shared_guide_placeholder_missing placeholder=%s",
            TOOLSET_SHARED_GUIDE_PLACEHOLDER,
        )
        return f"{system_prompt.rstrip()}\n\n{shared_guide}"

    async def execute_tool_call(
        self,
        tool_call: ToolCallMessage,
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> ToolMessage:
        """按 ToolCall 执行工具并返回标准 ToolMessage。"""
        tool_id = tool_call.id
        tool_name = tool_call.function.name
        raw_arguments = tool_call.function.arguments

        if isinstance(raw_arguments, str):
            arguments = json.loads(raw_arguments)
        else:
            arguments = raw_arguments
        logger.debug(
            "event=tool.call_started tool_id=%s tool_name=%s argument_keys=%s",
            tool_id,
            tool_name,
            sorted(arguments.keys()),
        )

        tool = self.get(tool_name)
        if not tool:
            logger.warning(
                "event=tool.call_not_found tool_id=%s tool_name=%s",
                tool_id,
                tool_name,
            )
            return ToolMessage(
                tool_call_id=tool_id,
                name=tool_name,
                content=f"Error: Tool '{tool_name}' not found",
            )

        try:
            result = await tool.execute(runtime_context=runtime_context, **arguments)
            if isinstance(result, str):
                content = result
            elif isinstance(result, BaseModel):
                content = result.model_dump_json()
            else:
                content = json.dumps(result, ensure_ascii=False)

            logger.debug(
                "event=tool.call_succeeded tool_id=%s tool_name=%s",
                tool_id,
                tool_name,
            )

            return ToolMessage(
                tool_call_id=tool_id,
                name=tool_name,
                content=content,
            )
        except Exception as e:
            logger.exception(
                "event=tool.call_failed tool_id=%s tool_name=%s",
                tool_id,
                tool_name,
            )
            return ToolMessage(
                tool_call_id=tool_id,
                name=tool_name,
                content=f"Error: {e}",
            )


def _get_type_schema(type_hint: Any) -> dict[str, Any]:
    origin = get_origin(type_hint)
    args = get_args(type_hint)

    if origin in (Union, UnionType) and args:
        non_none_types = [arg for arg in args if arg is not type(None)]
        has_none = len(non_none_types) != len(args)

        if len(non_none_types) == 1:
            schema = _get_type_schema(non_none_types[0])
            if has_none:
                schema["nullable"] = True
            return schema

        return {"anyOf": [_get_type_schema(arg) for arg in non_none_types]}

    if origin is list and args:
        return {
            "type": "array",
            "items": _get_type_schema(args[0]),
        }

    if origin is dict:
        return {"type": "object"}

    if type_hint is str:
        return {"type": "string"}
    if type_hint is int:
        return {"type": "integer"}
    if type_hint is float:
        return {"type": "number"}
    if type_hint is bool:
        return {"type": "boolean"}
    if type_hint is list:
        return {"type": "array"}
    if type_hint is dict:
        return {"type": "object"}
    if type_hint is Any:
        return {}

    return {"type": "string"}


def tool(
    name: str | None = None,
    description: str | None = None,
    bound_kwargs: dict[str, Any] | None = None,
    context_params: dict[str, str] | None = None,
    shared_guides: dict[str, str] | None = None,
) -> Callable[[Callable[..., Any]], Tool]:
    """工具装饰器."""

    def decorator(func: Callable[..., Any]) -> Tool:
        tool_name = name or func.__name__
        tool_desc = description or (func.__doc__ or "").strip()

        sig = inspect.signature(func)
        type_hints = get_type_hints(func)

        properties: dict[str, Any] = {}
        required: list[str] = []

        hidden_param_names = set((bound_kwargs or {}).keys()) | set(
            (context_params or {}).keys()
        )

        for param_name, param in sig.parameters.items():
            if param_name == "return":
                continue
            if param_name in hidden_param_names:
                continue

            type_hint = type_hints.get(param_name, str)
            param_schema = _get_type_schema(type_hint)

            if param.default is not inspect.Parameter.empty:
                param_schema["default"] = param.default
            else:
                required.append(param_name)

            properties[param_name] = param_schema

        parameters = {
            "type": "object",
            "properties": properties,
            "required": required,
        }

        return Tool(
            name=tool_name,
            description=tool_desc,
            parameters=parameters,
            function=func,
            bound_kwargs=bound_kwargs or {},
            context_params=context_params or {},
            shared_guides=shared_guides or {},
        )

    return decorator
