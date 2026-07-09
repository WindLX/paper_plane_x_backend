"""AppSettingsRepository unified section API tests."""

from pathlib import Path

import pytest

from paper_plane_x_backend.models.app_settings import (
    AGENT_NAMES,
    AgentLLMConfigEntry,
    AppSettings,
    LLMProvider,
)
from paper_plane_x_backend.services.app_settings import AppSettingsRepository
from paper_plane_x_backend.services.app_settings.repository import (
    AppSettingsRepositoryError,
)


@pytest.fixture
def repo(tmp_path: Path) -> AppSettingsRepository:
    path = tmp_path / "app_settings.toml"
    return AppSettingsRepository(path)


def test_get_returns_full_settings(repo: AppSettingsRepository) -> None:
    settings = repo.get()
    assert isinstance(settings, AppSettings)


def test_update_pdf_parser(repo: AppSettingsRepository) -> None:
    updated = repo.update_pdf_parser(
        {
            "type": "local_mineru",
            "local": {"base_url": "http://mineru:9000"},
        }
    )
    assert updated.pdf_parser.local.base_url == "http://mineru:9000"


def test_update_data_process(repo: AppSettingsRepository) -> None:
    updated = repo.update_data_process({"worker_count": 10})
    assert updated.data_process.worker_count == 10


def test_update_librarian(repo: AppSettingsRepository) -> None:
    updated = repo.update_librarian({"top_tags_limit": 20})
    assert updated.librarian.top_tags_limit == 20


def test_update_pandoc(repo: AppSettingsRepository) -> None:
    updated = repo.update_pandoc(
        {
            "pandoc_path": "/opt/pandoc/bin/pandoc",
            "html_template": "/templates/article.html",
            "pdf_engine": "typst",
        }
    )
    assert updated.pandoc.pandoc_path == "/opt/pandoc/bin/pandoc"
    assert updated.pandoc.html_template == "/templates/article.html"
    assert updated.pandoc.pdf_engine == "typst"


def test_get_agent_llm_returns_none_when_not_set(
    repo: AppSettingsRepository,
) -> None:
    entry = repo.get_agent_llm("extraction")
    assert entry is None


def test_update_agent_llm_and_get(repo: AppSettingsRepository) -> None:
    repo.update_agent_llm(
        "extraction",
        {"provider_name": "deepseek", "temperature": 0.2},
    )
    entry = repo.get_agent_llm("extraction")
    assert isinstance(entry, AgentLLMConfigEntry)
    assert entry.provider_name == "deepseek"
    assert entry.temperature == 0.2


def test_list_agent_llm_returns_all_agents(repo: AppSettingsRepository) -> None:
    result = repo.list_agent_llm()
    assert set(result.keys()) == set(AGENT_NAMES)
    assert all(v is None for v in result.values())

    repo.update_agent_llm("analysis", {"provider_name": "openai"})
    result = repo.list_agent_llm()
    assert result["analysis"] is not None
    assert result["analysis"].provider_name == "openai"  # type: ignore[union-attr]
    assert result["extraction"] is None


def test_update_agent_llm_rejects_unknown_agent(repo: AppSettingsRepository) -> None:
    with pytest.raises(AppSettingsRepositoryError) as exc:
        repo.update_agent_llm("unknown_agent", {"provider_name": "x"})
    assert exc.value.error_code == "invalid_agent"


def test_get_agent_llm_rejects_unknown_agent(repo: AppSettingsRepository) -> None:
    with pytest.raises(AppSettingsRepositoryError) as exc:
        repo.get_agent_llm("unknown_agent")
    assert exc.value.error_code == "invalid_agent"


# ---- Provider CRUD ----


def test_provider_crud(repo: AppSettingsRepository) -> None:
    p1 = LLMProvider(name="p1", model="m1")
    p2 = LLMProvider(name="p2", model="m2")

    repo.create_provider(p1)
    repo.create_provider(p2)
    assert len(repo.list_providers()) == 2

    got = repo.get_provider("p1")
    assert got is not None
    assert got.model == "m1"

    repo.update_provider("p1", {"model": "m1-updated"})
    got = repo.get_provider("p1")
    assert got is not None
    assert got.model == "m1-updated"

    repo.delete_provider("p1")
    assert repo.get_provider("p1") is None
    assert len(repo.list_providers()) == 1


def test_create_provider_rejects_duplicate(repo: AppSettingsRepository) -> None:
    p = LLMProvider(name="dup", model="m")
    repo.create_provider(p)
    with pytest.raises(AppSettingsRepositoryError) as exc:
        repo.create_provider(p)
    assert exc.value.error_code == "already_exists"


def test_update_provider_rejects_name_change(repo: AppSettingsRepository) -> None:
    p = LLMProvider(name="orig", model="m")
    repo.create_provider(p)
    with pytest.raises(AppSettingsRepositoryError) as exc:
        repo.update_provider("orig", {"name": "new_name"})
    assert exc.value.error_code == "immutable_name"


def test_delete_provider_rejects_missing(repo: AppSettingsRepository) -> None:
    with pytest.raises(AppSettingsRepositoryError) as exc:
        repo.delete_provider("missing")
    assert exc.value.error_code == "not_found"


def test_ensure_default_provider_creates_when_empty(
    repo: AppSettingsRepository,
) -> None:
    default = LLMProvider(name="default", model="gpt-4o")
    repo.ensure_default_provider(default)
    assert repo.get_provider("default") is not None


def test_ensure_default_provider_skips_when_exists(
    repo: AppSettingsRepository,
) -> None:
    existing = LLMProvider(name="default", model="gpt-4")
    repo.create_provider(existing)
    repo.ensure_default_provider(LLMProvider(name="default", model="gpt-4o"))
    got = repo.get_provider("default")
    assert got is not None
    assert got.model == "gpt-4"


# ---- Persistence ----


def test_changes_are_persisted_to_disk(repo: AppSettingsRepository) -> None:
    repo.update_pdf_parser(
        {
            "type": "local_mineru",
            "local": {"base_url": "http://persisted"},
        }
    )

    # 重新加载同一路径的仓库
    repo2 = AppSettingsRepository(repo.path)
    assert repo2.get().pdf_parser.local.base_url == "http://persisted"


def test_agent_llm_persisted(repo: AppSettingsRepository) -> None:
    repo.update_agent_llm("global_finder", {"provider_name": "p", "temperature": 0.3})

    repo2 = AppSettingsRepository(repo.path)
    entry = repo2.get_agent_llm("global_finder")
    assert entry is not None
    assert entry.provider_name == "p"
    assert entry.temperature == 0.3


def test_provider_persisted(repo: AppSettingsRepository) -> None:
    p = LLMProvider(name="disk", model="m")
    repo.create_provider(p)

    repo2 = AppSettingsRepository(repo.path)
    assert repo2.get_provider("disk") is not None


def test_pandoc_persisted(repo: AppSettingsRepository) -> None:
    repo.update_pandoc(
        {
            "pandoc_path": "/persisted/pandoc",
            "html_template": "/persisted/template.html",
            "pdf_engine": "weasyprint",
        }
    )

    repo2 = AppSettingsRepository(repo.path)
    assert repo2.get().pandoc.pandoc_path == "/persisted/pandoc"
    assert repo2.get().pandoc.html_template == "/persisted/template.html"
    assert repo2.get().pandoc.pdf_engine == "weasyprint"
