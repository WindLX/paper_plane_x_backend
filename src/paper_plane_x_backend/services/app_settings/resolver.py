"""应用动态配置解析器.

将 Agent 的 provider_name 引用解析为具体的 LLMConfig，
消除 app_settings 与 llm_provider 服务之间的循环依赖.
"""

from typing import Any, TypedDict

from paper_plane_x_backend.models.app_settings import (
    DEFAULT_MAX_TOTAL_TOKENS,
    LLMConfig,
)
from paper_plane_x_backend.services.app_settings.repository import (
    get_app_settings_repo,
)


class AgentConfigResponsePayload(TypedDict):
    agent_name: str
    provider_name: str
    temperature: float
    max_total_tokens: int
    timeout: float
    thinking_enabled: bool
    reasoning_effort: str | None
    extra_body: dict[str, Any] | None
    is_vlm: bool
    short_memory_window: int
    effective_model: str | None
    effective_base_url: str | None


def resolve_agent_llm_config(agent_name: str) -> LLMConfig:
    """获取指定 Agent 的 LLM 配置.

    根据 Agent 配置的 provider_name 查找 Provider 池，
    再叠加 Agent 的覆盖参数。不再继承全局默认配置，
    要求用户为每个 Agent 手动配置好 provider。

    Args:
        agent_name: Agent 名称

    Returns:
        LLMConfig: 解析后的 LLM 配置

    Raises:
        RuntimeError: Agent 未配置或引用的 Provider 不存在。
    """
    app_settings = get_app_settings_repo().get()
    entry = getattr(app_settings.agent_llm, agent_name, None)
    if entry is None:
        raise RuntimeError(
            f"Agent '{agent_name}' has no LLM configuration. "
            f"Please configure it via /api/v1/settings/agent_llm/{agent_name}"
        )

    provider = get_app_settings_repo().get_provider(entry.provider_name)
    if provider is None:
        raise RuntimeError(
            f"Agent '{agent_name}' references provider '{entry.provider_name}' "
            f"which does not exist. Please create the provider first."
        )

    overrides = entry.model_dump(
        exclude={"provider_name"},
        exclude_unset=True,
    )

    base = provider.model_dump(mode="json", exclude_none=True)
    return LLMConfig(**{**base, **overrides})


def build_agent_config_response(agent_name: str) -> AgentConfigResponsePayload:
    """构建 Agent 配置响应字典（供 settings router 使用）."""
    app_settings = get_app_settings_repo().get()
    entry = getattr(app_settings.agent_llm, agent_name, None)
    if entry is None:
        return {
            "agent_name": agent_name,
            "provider_name": "default",
            "temperature": 0.7,
            "max_total_tokens": DEFAULT_MAX_TOTAL_TOKENS,
            "timeout": 180.0,
            "thinking_enabled": False,
            "reasoning_effort": None,
            "extra_body": None,
            "is_vlm": False,
            "short_memory_window": 99999999,
            "effective_model": None,
            "effective_base_url": None,
        }

    provider = get_app_settings_repo().get_provider(entry.provider_name)

    return {
        "agent_name": agent_name,
        "provider_name": entry.provider_name,
        "temperature": entry.temperature,
        "max_total_tokens": entry.max_total_tokens,
        "timeout": entry.timeout,
        "thinking_enabled": entry.thinking_enabled,
        "reasoning_effort": entry.reasoning_effort,
        "extra_body": entry.extra_body,
        "is_vlm": entry.is_vlm,
        "short_memory_window": entry.short_memory_window,
        "effective_model": provider.model if provider else None,
        "effective_base_url": provider.base_url if provider else None,
    }
