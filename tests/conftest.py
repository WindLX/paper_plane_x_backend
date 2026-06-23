"""Pytest 配置和 fixtures."""

import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from paper_plane_x_backend.api.dependencies import (
    get_database,
    get_task_manager,
)
from paper_plane_x_backend.config import server_config
from paper_plane_x_backend.models.app_settings import AGENT_NAMES, LLMProvider
from paper_plane_x_backend.services import Database, init_database
from paper_plane_x_backend.services.app_settings import (
    get_app_settings_repo,
    init_app_settings_repo,
)
from paper_plane_x_backend.services.data_process_tasks import (
    lifecycle as task_manager_module,
)
from paper_plane_x_backend.services.data_process_tasks.stores import (
    DataProcessTaskStateStore,
)
from paper_plane_x_backend.services.data_process_tasks.task_manager import (
    DataProcessTaskManager,
)

# 在导入 app 之前切换测试运行目录，避免生命周期初始化写入 ./data。
_TEST_RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="ppx-tests-"))
server_config.data_dir = _TEST_RUNTIME_DIR
server_config.database_path = _TEST_RUNTIME_DIR / "app.test.db"
server_config.log.file_path = _TEST_RUNTIME_DIR / "logs" / "backend.log"
server_config.api.console_dist_dir = _TEST_RUNTIME_DIR / "console"

_app_settings_repo = init_app_settings_repo(_TEST_RUNTIME_DIR / "app_settings.toml")
_app_settings_repo.update_pdf_parser(
    {"local": {"output_dir": str(_TEST_RUNTIME_DIR / "papers")}}
)

# 配置测试用的 LLM provider 和 agent_llm
_app_settings_repo.ensure_default_provider(
    LLMProvider(name="default", model="gpt-4o", api_key="test-key")
)
for agent_name in AGENT_NAMES:
    _app_settings_repo.update_agent_llm(agent_name, {"provider_name": "default"})


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_runtime_dir() -> Generator[None, None, None]:
    """会话结束后清理测试运行目录."""
    yield
    shutil.rmtree(_TEST_RUNTIME_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def ensure_test_llm_config() -> None:
    """每个测试前确保 LLM provider 和 agent_llm 配置存在."""
    repo = get_app_settings_repo()
    if repo.get_provider("default") is None:
        repo.ensure_default_provider(
            LLMProvider(name="default", model="gpt-4o", api_key="test-key")
        )
    for agent_name in AGENT_NAMES:
        entry = repo.get_agent_llm(agent_name)
        if entry is None:
            repo.update_agent_llm(agent_name, {"provider_name": "default"})


@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    """创建临时数据库文件路径."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    # 清理
    path.unlink(missing_ok=True)


@pytest.fixture
def db(temp_db_path: Path) -> Generator[Database, None, None]:
    """创建并初始化测试数据库."""
    database = init_database(temp_db_path)
    yield database


@pytest.fixture
def client(db: Database) -> Generator[TestClient, None, None]:
    """创建测试客户端，使用测试数据库."""
    from paper_plane_x_backend.main import app

    # 覆盖依赖注入，使用测试数据库
    def override_get_db() -> Database:
        return db

    test_task_manager = DataProcessTaskManager(
        worker_count=1,
        state_store=DataProcessTaskStateStore(db),
    )

    def override_get_task_manager() -> DataProcessTaskManager:
        return test_task_manager

    app.dependency_overrides[get_database] = override_get_db
    app.dependency_overrides[get_task_manager] = override_get_task_manager

    original_task_manager = task_manager_module._task_manager_instance
    task_manager_module._task_manager_instance = test_task_manager

    with TestClient(app) as test_client:
        yield test_client

    task_manager_module._task_manager_instance = original_task_manager
    # 清理依赖覆盖
    app.dependency_overrides.clear()
