"""应用动态配置 TOML 存储服务.

提供 AppSettings 的增删改查，数据持久化到 TOML 文件。
与 ServerConfig（启动只读）分离。
"""

import logging
from pathlib import Path
from typing import Any

import rtoml

from paper_plane_x_backend.config import server_config
from paper_plane_x_backend.models.app_settings import (
    AGENT_NAMES,
    AgentLLMConfigEntry,
    AppSettings,
    LLMProvider,
)

logger = logging.getLogger(__name__)


class AppSettingsRepositoryError(Exception):
    """AppSettingsRepository 异常."""

    def __init__(self, message: str, error_code: str = "bad_request") -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class AppSettingsRepository:
    """应用动态配置仓库.

    使用 TOML 文件持久化 AppSettings：
    {llm = {...}, agent_llm = {...}, mineru = {...}, data_process = {...}, librarian = {...}}
    """

    _settings_path: Path
    _settings: AppSettings

    def __init__(self, settings_path: Path | str | None = None) -> None:
        if settings_path is not None:
            self._settings_path = Path(settings_path)
        else:
            self._settings_path = server_config.data_dir / "app_settings.toml"

        self._settings = AppSettings()
        self._load_or_init()

    @property
    def path(self) -> Path:
        return self._settings_path

    def _load_or_init(self) -> None:
        """加载或初始化 AppSettings."""
        if not self._settings_path.exists():
            logger.info(
                "event=app_settings.file_not_found path=%s", self._settings_path
            )
            self._save()
            return

        try:
            data = rtoml.load(self._settings_path)
        except (rtoml.TomlSerializationError, rtoml.TomlParsingError) as exc:
            logger.warning(
                "event=app_settings.load_failed path=%s error=%s",
                self._settings_path,
                exc,
            )
            raise AppSettingsRepositoryError(
                f"Failed to parse TOML: {exc}",
                error_code="invalid_toml",
            ) from exc

        try:
            self._settings = AppSettings.model_validate(data)
        except Exception as exc:
            logger.warning(
                "event=app_settings.validation_failed path=%s error=%s",
                self._settings_path,
                exc,
            )
            raise AppSettingsRepositoryError(
                f"Failed to validate settings: {exc}",
                error_code="invalid_data",
            ) from exc

        logger.info(
            "event=app_settings.loaded path=%s",
            self._settings_path,
        )

    def _save(self) -> None:
        """原子写入 TOML 文件."""
        data = self._settings.model_dump(mode="json", exclude_none=True)

        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._settings_path.with_suffix(".tmp")

        try:
            temp_path.write_text(rtoml.dumps(data), encoding="utf-8")
            temp_path.replace(self._settings_path)
        except OSError as exc:
            logger.exception(
                "event=app_settings.save_failed path=%s",
                self._settings_path,
            )
            raise AppSettingsRepositoryError(
                f"Failed to save settings: {exc}",
                error_code="io_error",
            ) from exc

        logger.debug(
            "event=app_settings.saved path=%s",
            self._settings_path,
        )

    # ---- Internal ----

    def _update_section(self, section: str, values: dict[str, Any]) -> AppSettings:
        """更新指定 object-type section."""
        current = self._settings.model_dump(mode="json", exclude_none=True)
        section_data = current.get(section, {})
        section_data.update(values)
        current[section] = section_data

        self._settings = AppSettings.model_validate(current)
        self._save()
        logger.info("event=app_settings.updated section=%s", section)
        return self._settings

    def get(self) -> AppSettings:
        """获取当前 AppSettings."""
        return self._settings

    # ---- Object-type sections (llm / mineru / data_process / librarian) ----

    def get_mineru(self) -> AppSettings:
        return self._settings

    def update_mineru(self, values: dict[str, Any]) -> AppSettings:
        return self._update_section("mineru", values)

    def get_data_process(self) -> AppSettings:
        return self._settings

    def update_data_process(self, values: dict[str, Any]) -> AppSettings:
        return self._update_section("data_process", values)

    def get_librarian(self) -> AppSettings:
        return self._settings

    def update_librarian(self, values: dict[str, Any]) -> AppSettings:
        return self._update_section("librarian", values)

    # ---- Agent LLM (nested section) ----

    def get_agent_llm(self, agent_name: str) -> AgentLLMConfigEntry | None:
        if agent_name not in AGENT_NAMES:
            raise AppSettingsRepositoryError(
                f"Unknown agent '{agent_name}'. Must be one of: {', '.join(AGENT_NAMES)}",
                error_code="invalid_agent",
            )
        return getattr(self._settings.agent_llm, agent_name, None)

    def list_agent_llm(self) -> dict[str, AgentLLMConfigEntry | None]:
        return {
            name: getattr(self._settings.agent_llm, name, None) for name in AGENT_NAMES
        }

    def update_agent_llm(self, agent_name: str, values: dict[str, Any]) -> AppSettings:
        if agent_name not in AGENT_NAMES:
            raise AppSettingsRepositoryError(
                f"Unknown agent '{agent_name}'. Must be one of: {', '.join(AGENT_NAMES)}",
                error_code="invalid_agent",
            )
        current = self._settings.model_dump(mode="json", exclude_none=True)
        agent_llm_data = current.get("agent_llm", {})
        agent_llm_data[agent_name] = values
        current["agent_llm"] = agent_llm_data
        self._settings = AppSettings.model_validate(current)
        self._save()
        logger.info("event=app_settings.updated_agent agent_name=%s", agent_name)
        return self._settings

    # ---- Provider CRUD (list-type section) ----

    def list_providers(self) -> list[LLMProvider]:
        """列出所有 provider（按名称排序）."""
        return sorted(self._settings.providers, key=lambda p: p.name)

    def get_provider(self, name: str) -> LLMProvider | None:
        """按名称获取 provider."""
        for p in self._settings.providers:
            if p.name == name:
                return p
        return None

    def create_provider(self, provider: LLMProvider) -> None:
        """创建 provider（name 必须唯一）."""
        if self.get_provider(provider.name) is not None:
            raise AppSettingsRepositoryError(
                f"Provider '{provider.name}' already exists",
                error_code="already_exists",
            )
        self._settings.providers.append(provider)
        self._save()
        logger.info(
            "event=app_settings.provider_created name=%s model=%s",
            provider.name,
            provider.model,
        )

    def update_provider(self, name: str, data: dict[str, Any]) -> LLMProvider:
        """更新 provider（允许部分字段更新）."""
        existing = self.get_provider(name)
        if existing is None:
            raise AppSettingsRepositoryError(
                f"Provider '{name}' not found",
                error_code="not_found",
            )

        updated_data = existing.model_dump(mode="json", exclude_none=True)
        updated_data.update(data)

        # 禁止修改 name
        if "name" in data and data["name"] != name:
            raise AppSettingsRepositoryError(
                "Cannot change provider name",
                error_code="immutable_name",
            )

        updated = LLMProvider.model_validate(updated_data)
        # 替换列表中的旧 provider
        self._settings.providers = [
            updated if p.name == name else p for p in self._settings.providers
        ]
        self._save()
        logger.info(
            "event=app_settings.provider_updated name=%s model=%s",
            name,
            updated.model,
        )
        return updated

    def rename_provider(self, old_name: str, new_name: str) -> LLMProvider:
        """重命名 provider（同步更新所有 agent_llm 引用）."""
        if old_name == new_name:
            existing = self.get_provider(old_name)
            if existing is None:
                raise AppSettingsRepositoryError(
                    f"Provider '{old_name}' not found",
                    error_code="not_found",
                )
            return existing

        if self.get_provider(old_name) is None:
            raise AppSettingsRepositoryError(
                f"Provider '{old_name}' not found",
                error_code="not_found",
            )
        if self.get_provider(new_name) is not None:
            raise AppSettingsRepositoryError(
                f"Provider '{new_name}' already exists",
                error_code="already_exists",
            )

        # 更新 provider 列表中的名称
        for p in self._settings.providers:
            if p.name == old_name:
                p.name = new_name
                break

        # 同步更新所有 agent_llm 引用
        for agent_name in AGENT_NAMES:
            entry = self.get_agent_llm(agent_name)
            if entry is not None and entry.provider_name == old_name:
                self.update_agent_llm(
                    agent_name,
                    {
                        **entry.model_dump(mode="json", exclude_none=True),
                        "provider_name": new_name,
                    },
                )

        self._save()
        logger.info(
            "event=app_settings.provider_renamed old=%s new=%s",
            old_name,
            new_name,
        )
        renamed = self.get_provider(new_name)
        if renamed is None:
            raise AppSettingsRepositoryError(
                f"Provider '{new_name}' not found after rename",
                error_code="not_found",
            )
        return renamed

    def delete_provider(self, name: str) -> None:
        """删除 provider."""
        if self.get_provider(name) is None:
            raise AppSettingsRepositoryError(
                f"Provider '{name}' not found",
                error_code="not_found",
            )
        self._settings.providers = [
            p for p in self._settings.providers if p.name != name
        ]
        self._save()
        logger.info("event=app_settings.provider_deleted name=%s", name)

    def ensure_default_provider(self, default_provider: LLMProvider) -> None:
        """若没有任何 provider，则创建默认 provider."""
        if not self._settings.providers:
            self.create_provider(default_provider)
            logger.info(
                "event=app_settings.provider_default_created name=%s",
                default_provider.name,
            )


# ---- Module-level singleton ----

_app_settings_repo_instance: AppSettingsRepository | None = None


def get_app_settings_repo() -> AppSettingsRepository:
    """获取 AppSettingsRepository 单例（懒加载）."""
    global _app_settings_repo_instance
    if _app_settings_repo_instance is None:
        _app_settings_repo_instance = AppSettingsRepository()
    return _app_settings_repo_instance


def init_app_settings_repo(
    settings_path: Path | str | None = None,
) -> AppSettingsRepository:
    """初始化 AppSettingsRepository 单例."""
    global _app_settings_repo_instance
    if _app_settings_repo_instance is not None:
        return _app_settings_repo_instance
    _app_settings_repo_instance = AppSettingsRepository(settings_path)
    logger.info(
        "event=app_settings.repo_initialized path=%s",
        _app_settings_repo_instance.path,
    )
    return _app_settings_repo_instance
