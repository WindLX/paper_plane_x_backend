"""应用日志初始化工具。"""

from __future__ import annotations

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from paper_plane_x_backend.config import settings

_active_log_file_path: Path | None = None

# VERBOSE 位于 DEBUG 之下，用于逐项数据输出（如逐 chunk、逐记录日志），
# 默认与 DEBUG 一同关闭；只有显式配置 level=VERBOSE 时才输出。
VERBOSE = 5
logging.addLevelName(VERBOSE, "VERBOSE")

_LEVEL_VALUES: dict[str, int] = {
    "VERBOSE": VERBOSE,
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def resolve_log_level(name: str) -> int:
    """将已校验的日志级别名映射为 logging 级别数值。"""
    return _LEVEL_VALUES[name]


def log_verbose(logger: logging.Logger, msg: str, *args: object) -> None:
    """以 VERBOSE 级别输出逐项数据日志。"""
    logger.log(VERBOSE, msg, *args)


class AppNamespaceFilter(logging.Filter):
    """仅放行应用命名空间日志。"""

    def __init__(self, namespace_prefixes: tuple[str, ...]) -> None:
        super().__init__()
        self.namespace_prefixes = namespace_prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return any(
            record.name == prefix or record.name.startswith(f"{prefix}.")
            for prefix in self.namespace_prefixes
        )


def _build_log_file_path_for_startup(base_path: Path) -> Path:
    """基于配置路径生成本次启动专属日志文件名。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = base_path.suffix if base_path.suffix else ".log"
    return base_path.with_name(f"{base_path.stem}_{timestamp}{suffix}")


def setup_logging() -> None:
    """配置全局日志（控制台 + 文件滚动输出）。"""
    global _active_log_file_path

    settings.ensure_directories()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.log.to_file:
        _active_log_file_path = _build_log_file_path_for_startup(settings.log.file_path)
        handlers.append(
            RotatingFileHandler(
                filename=_active_log_file_path,
                maxBytes=settings.log.file_max_bytes,
                backupCount=settings.log.file_backup_count,
                encoding="utf-8",
            )
        )
    else:
        _active_log_file_path = None

    logging.basicConfig(
        level=resolve_log_level(settings.log.level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )

    if settings.log.app_only:
        app_filter = AppNamespaceFilter(("paper_plane_x_backend",))
        for handler in logging.getLogger().handlers:
            handler.addFilter(app_filter)

        # 第三方库日志统一抬高阈值，避免刷屏。
        for logger_name in (
            "uvicorn",
            "uvicorn.error",
            "uvicorn.access",
            "fastapi",
            "watchfiles",
            "httpx",
            "litellm",
            "LiteLLM",
            "asyncio",
        ):
            logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_active_log_file_path() -> Path | None:
    """返回本次进程启动使用的日志文件路径。"""
    return _active_log_file_path
