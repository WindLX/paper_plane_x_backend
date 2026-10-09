"""Settings tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from paper_plane_x_backend.config import ServerConfig
from paper_plane_x_backend.models.app_settings import (
    AgentLLMConfigEntry,
    AgentLLMConfigs,
    LLMConfig,
)


def _mock_app_settings():
    """构造 mock AppSettingsRepository 对象."""
    mock = MagicMock()
    mock.get.return_value = mock
    mock.get_provider.return_value = None
    mock.llm = LLMConfig(
        model="global-model",
        api_key="k-global",
        base_url="http://global",
        temperature=0.7,
        max_total_tokens=240000,
        timeout=60.0,
        custom_headers={"X-G": "1"},
        thinking_enabled=True,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}},
        is_vlm=False,
    )
    mock.agent_llm = AgentLLMConfigs(
        extraction=AgentLLMConfigEntry(
            provider_name="extract-provider",
            temperature=0.1,
            thinking_enabled=False,
            reasoning_effort="low",
        ),
        analysis=AgentLLMConfigEntry(
            provider_name="analysis-provider",
        ),
    )
    return mock


def test_resolve_agent_llm_config_merges_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_app = _mock_app_settings()

    mock_provider = MagicMock()
    mock_provider.model_dump.return_value = {
        "model": "extract-model",
        "base_url": "http://extract",
        "api_key": "k-extract",
        "temperature": 0.5,
        "max_output_tokens": 4096,
        "timeout": 30.0,
        "thinking_enabled": True,
        "reasoning_effort": "high",
        "is_vlm": True,
    }
    mock_app.get_provider.return_value = mock_provider

    monkeypatch.setattr(
        "paper_plane_x_backend.services.app_settings.resolver.get_app_settings_repo",
        lambda: mock_app,
    )

    from paper_plane_x_backend.services.app_settings.resolver import (
        resolve_agent_llm_config,
    )

    cfg = resolve_agent_llm_config("extraction")

    assert cfg.model == "extract-model"
    assert cfg.temperature == 0.1
    assert cfg.api_key == "k-extract"
    assert cfg.base_url == "http://extract"
    # 仅当 Agent 显式设置字段时才覆盖，Provider 基线配置应保留。
    assert cfg.max_output_tokens == 4096
    assert cfg.thinking_enabled is False
    assert cfg.reasoning_effort == "low"
    assert cfg.is_vlm is True


def test_resolve_agent_llm_config_inherits_provider_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_app = _mock_app_settings()

    mock_provider = MagicMock()
    mock_provider.model_dump.return_value = {
        "model": "analysis-model",
        "base_url": "http://analysis",
        "api_key": "k-analysis",
        "temperature": 0.5,
        "thinking_enabled": True,
        "reasoning_effort": "high",
        "extra_body": {"metadata": {"tier": "provider"}},
        "is_vlm": False,
    }
    mock_app.get_provider.return_value = mock_provider

    monkeypatch.setattr(
        "paper_plane_x_backend.services.app_settings.resolver.get_app_settings_repo",
        lambda: mock_app,
    )

    from paper_plane_x_backend.services.app_settings.resolver import (
        resolve_agent_llm_config,
    )

    cfg = resolve_agent_llm_config("analysis")

    assert cfg.model == "analysis-model"
    assert cfg.thinking_enabled is True
    assert cfg.reasoning_effort == "high"
    assert cfg.extra_body == {"metadata": {"tier": "provider"}}


def test_resolve_agent_llm_config_raises_when_agent_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_app = _mock_app_settings()

    monkeypatch.setattr(
        "paper_plane_x_backend.services.app_settings.resolver.get_app_settings_repo",
        lambda: mock_app,
    )

    from paper_plane_x_backend.services.app_settings.resolver import (
        resolve_agent_llm_config,
    )

    with pytest.raises(RuntimeError, match="has no LLM configuration"):
        resolve_agent_llm_config("fact_check")


def test_server_config_supports_static_keys() -> None:
    settings = ServerConfig(
        log={"level": "ERROR", "app_only": False},  # type: ignore
    )

    assert settings.log.level == "ERROR"
    assert settings.log.app_only is False


def test_settings_source_precedence_init_over_env_over_dotenv_over_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "profile.toml"
    config_path.write_text(
        """
app_name = "toml-name"

[api]
port = 8001
""".strip(),
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text("PPX_API__PORT=8002\n", encoding="utf-8")

    monkeypatch.setenv("PPX_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("PPX_API__PORT", "8003")

    settings = ServerConfig(
        _env_file=env_path,  # type: ignore
        app_name="init-name",
        api={"port": 8004},
    )

    assert settings.app_name == "init-name"
    assert settings.api.port == 8004


def test_test_profile_uses_test_safe_paths_and_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = Path(__file__).resolve().parents[2] / "config" / "test.toml"
    monkeypatch.setenv("PPX_CONFIG_FILE", str(config_path))

    settings = ServerConfig(_env_file=None)  # type: ignore

    assert "test" in settings.data_dir.as_posix()
    assert "test" in settings.database_path.as_posix()
    assert settings.log.to_file is False
    assert settings.api.reload is False

    monkeypatch.delenv("PPX_CONFIG_FILE", raising=False)
