"""日志级别基础设施与分级迁移的回归测试。"""

import io
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import UploadFile, status

from paper_plane_x_backend.config import LogConfig, ServerConfig
from paper_plane_x_backend.models import ExtractionStatus, PaperSortKey, SortOrder
from paper_plane_x_backend.services.data_process_tasks.task_manager import (
    DataProcessTaskManager,
)
from paper_plane_x_backend.services.orchestrators.data_process import (
    DataProcessDomainError,
    DataProcessOrchestrator,
)
from paper_plane_x_backend.services.orchestrators.paper import PaperOrchestrator
from paper_plane_x_backend.utils.logging import (
    VERBOSE,
    log_verbose,
    resolve_log_level,
    setup_logging,
)


def test_log_config_accepts_verbose_and_normalizes_case() -> None:
    config = LogConfig(level="verbose")
    assert config.level == "VERBOSE"


def test_log_config_rejects_unknown_level() -> None:
    with pytest.raises(ValueError, match="log.level"):
        LogConfig(level="TRACE")


def test_server_config_log_level_error_is_actionable() -> None:
    with pytest.raises(ValueError, match="VERBOSE/DEBUG/INFO/WARNING/ERROR/CRITICAL"):
        ServerConfig(log={"level": "CHAT"})  # type: ignore[typeddict-item]


def test_resolve_log_level_maps_names() -> None:
    assert resolve_log_level("VERBOSE") == VERBOSE == 5
    assert resolve_log_level("DEBUG") == logging.DEBUG
    assert resolve_log_level("INFO") == logging.INFO
    assert resolve_log_level("VERBOSE") < resolve_log_level("DEBUG")


def test_setup_logging_applies_verbose_root_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_plane_x_backend.config import settings

    original_root_level = logging.getLogger().level
    try:
        with monkeypatch.context() as ctx:
            ctx.setattr(settings.log, "level", "VERBOSE")
            ctx.setattr(settings.log, "to_file", False)
            ctx.setattr(settings.log, "app_only", False)

            setup_logging()
            assert logging.getLogger().level == VERBOSE
        # context 退出后配置已恢复原值，再按原配置重建根日志。
        setup_logging()
        assert logging.getLogger().level == resolve_log_level(settings.log.level)
    finally:
        logging.getLogger().setLevel(original_root_level)
    assert logging.getLogger().level == original_root_level


def test_log_verbose_emits_below_debug(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("paper_plane_x_backend.test_verbose")
    with caplog.at_level(VERBOSE, logger=logger.name):
        log_verbose(logger, "event=test.verbose item=%s", 1)
        logger.debug("event=test.debug_only")

    verbose_records = [r for r in caplog.records if r.levelno == VERBOSE]
    assert len(verbose_records) == 1
    assert verbose_records[0].levelname == "VERBOSE"
    assert verbose_records[0].getMessage() == "event=test.verbose item=1"


async def test_stream_verbose_logs_exclude_content_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """VERBOSE 流式日志只含协议元数据，不得包含模型正文等敏感内容。"""
    from paper_plane_x_backend.core.agent_runtime import llm_client as llm_module
    from paper_plane_x_backend.core.agent_runtime.llm_client import LLMClient

    secret_content = "SECRET-PAPER-BODY-TEXT"

    def make_chunk(*, content: str | None, usage: dict | None = None):
        return SimpleNamespace(
            model="synthetic-model",
            usage=usage,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=content,
                        reasoning_content=None,
                        tool_calls=None,
                    ),
                    finish_reason=None,
                )
            ]
            if content is not None
            else [],
        )

    async def fake_stream():
        for index in range(1, 21):
            yield make_chunk(content=f"{secret_content}-{index}")
        yield make_chunk(
            content=None, usage={"prompt_tokens": 1, "completion_tokens": 2}
        )

    async def fake_acompletion(**kwargs: object):
        return fake_stream()

    monkeypatch.setattr(llm_module, "acompletion", fake_acompletion)
    client = LLMClient(model="openai/synthetic")

    logger_name = "paper_plane_x_backend.core.agent_runtime.llm_client"
    with caplog.at_level(VERBOSE, logger=logger_name):
        chunks = [
            chunk
            async for chunk in client.chat_stream([{"role": "user", "content": "q"}])
        ]

    verbose_messages = [r.getMessage() for r in caplog.records if r.levelno == VERBOSE]
    assert any("event=llm.stream_chunk_summary" in msg for msg in verbose_messages)
    assert any("event=llm.stream_usage_chunk" in msg for msg in verbose_messages)
    for msg in verbose_messages:
        assert secret_content not in msg
    assert chunks


def _insert_paper(db, paper_id: str, extraction_status: ExtractionStatus) -> None:
    now = datetime.now()
    db.insert(
        "papers",
        {
            "paper_id": paper_id,
            "title": "t",
            "authors": "[]",
            "extraction_status": extraction_status.value,
            "extraction_fact_check_status": "PENDING",
            "analysis_fact_check_status": "PENDING",
            "created_at": now,
            "updated_at": now,
        },
    )


def test_paper_read_paths_log_at_debug_not_info(
    db, caplog: pytest.LogCaptureFixture
) -> None:
    """读路径（list/get）不得在默认 INFO 下刷屏。"""
    _insert_paper(db, "pap-log-1", ExtractionStatus.COMPLETED)
    orchestrator = PaperOrchestrator(
        db=db, task_manager=DataProcessTaskManager(worker_count=1)
    )

    with caplog.at_level(
        logging.INFO, logger="paper_plane_x_backend.services.orchestrators.paper"
    ):
        orchestrator.list_papers(
            offset=0,
            limit=10,
            sort_order=SortOrder.DESC,
            sort_by=PaperSortKey.CREATED_AT,
        )
        orchestrator.get_paper(paper_id="pap-log-1")

    events = [r.getMessage() for r in caplog.records]
    assert not any("event=paper.listed" in msg for msg in events)
    assert not any("event=paper.fetched" in msg for msg in events)

    with caplog.at_level(
        logging.DEBUG, logger="paper_plane_x_backend.services.orchestrators.paper"
    ):
        orchestrator.get_paper(paper_id="pap-log-1")

    assert any("event=paper.fetched" in r.getMessage() for r in caplog.records)


async def test_retry_blocked_logs_warning(db, caplog: pytest.LogCaptureFixture) -> None:
    """业务规则阻断的重试属于 WARNING，不得降级隐藏。"""
    _insert_paper(db, "pap-log-2", ExtractionStatus.PROCESSING)
    orchestrator = DataProcessOrchestrator(
        db=db, task_manager=DataProcessTaskManager(worker_count=1)
    )
    upload = UploadFile(filename="x.pdf", file=io.BytesIO(b"%PDF-1.4 fake"))

    with pytest.raises(DataProcessDomainError) as exc_info:
        await orchestrator.retry_upload(paper_id="pap-log-2", upload_file=upload)
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT

    blocked = [
        r
        for r in caplog.records
        if "event=data_process.retry_blocked" in r.getMessage()
    ]
    assert len(blocked) == 1
    assert blocked[0].levelno == logging.WARNING
