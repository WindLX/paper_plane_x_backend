"""应用动态配置解析器.

将 Agent 的 provider_name 引用解析为具体的 LLMConfig，
消除 app_settings 与 llm_provider 服务之间的循环依赖.
"""

from paper_plane_x_backend.models.app_settings import LLMConfig
from paper_plane_x_backend.services.app_settings.repository import (
    get_app_settings_repo,
)


def resolve_agent_llm_config(agent_name: str) -> LLMConfig:
    """获取指定 Agent 的 LLM 配置.

    根据 Agent 配置的 provider_name 查找 Provider 池，
    再叠加 Agent 的覆盖参数；未配置则返回全局默认配置。

    Args:
        agent_name: Agent 名称

    Returns:
        LLMConfig: 解析后的 LLM 配置
    """
    app_settings = get_app_settings_repo().get()
    entry = getattr(app_settings.agent_llm, agent_name, None)
    if entry is None:
        return app_settings.llm

    provider = get_app_settings_repo().get_provider(entry.provider_name)

    overrides = entry.model_dump(
        exclude={"provider_name"},
        exclude_unset=True,
        exclude_none=True,
    )

    if provider is not None:
        base = provider.model_dump(mode="json", exclude_none=True)
        return LLMConfig(**{**base, **overrides})

    global_config = app_settings.llm.model_dump()
    return LLMConfig(**{**global_config, **overrides})


def build_agent_config_response(agent_name: str) -> dict:
    """构建 Agent 配置响应字典（供 settings router 使用）."""
    app_settings = get_app_settings_repo().get()
    entry = getattr(app_settings.agent_llm, agent_name, None)
    if entry is None:
        return {
            "agent_name": agent_name,
            "provider_name": "default",
            "temperature": None,
            "max_tokens": None,
            "thinking_enabled": None,
            "reasoning_effort": None,
            "is_vlm": None,
            "effective_model": app_settings.llm.model,
            "effective_base_url": app_settings.llm.base_url,
        }

    provider = get_app_settings_repo().get_provider(entry.provider_name)

    return {
        "agent_name": agent_name,
        "provider_name": entry.provider_name,
        "temperature": entry.temperature,
        "max_tokens": entry.max_tokens,
        "thinking_enabled": entry.thinking_enabled,
        "reasoning_effort": entry.reasoning_effort,
        "is_vlm": entry.is_vlm,
        "effective_model": provider.model if provider else app_settings.llm.model,
        "effective_base_url": (
            provider.base_url if provider else app_settings.llm.base_url
        ),
    }
