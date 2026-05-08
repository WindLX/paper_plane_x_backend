"""Data Process Task WebSocket 状态广播管理器."""

import asyncio
import logging
from typing import Any

from paper_plane_x_backend.schemas.api.data_process import DataProcessTaskResponse
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessTaskState,
)

logger = logging.getLogger(__name__)


class DataProcessTaskWebSocketManager:
    """管理 data-process WebSocket 连接并广播任务状态变更."""

    _instance: "DataProcessTaskWebSocketManager | None" = None
    _lock: asyncio.Lock = asyncio.Lock()

    _connections: set[Any]

    def __new__(cls) -> "DataProcessTaskWebSocketManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._connections = set()
        return cls._instance

    def register_ws(self, websocket: Any) -> None:
        """注册 WebSocket 连接."""
        self._connections.add(websocket)
        logger.debug(
            "event=data_process_ws.registered total=%s",
            len(self._connections),
        )

    def unregister_ws(self, websocket: Any) -> None:
        """注销 WebSocket 连接."""
        self._connections.discard(websocket)
        logger.debug(
            "event=data_process_ws.unregistered total=%s",
            len(self._connections),
        )

    async def broadcast_task_update(self, state: DataProcessTaskState) -> None:
        """向所有连接的客户端广播任务状态变更."""
        if not self._connections:
            return

        payload = self._build_payload(state)
        dead: list[Any] = []
        for ws in self._connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    @staticmethod
    def _build_payload(state: DataProcessTaskState) -> dict[str, Any]:
        """构造广播消息体."""
        response = DataProcessTaskResponse(
            task_id=state.task_id,
            paper_id=state.paper_id,
            status=state.status,
            created_at=state.created_at,
            started_at=state.started_at,
            finished_at=state.finished_at,
            error=state.error,
            retry_of_task_id=state.retry_of_task_id,
            extraction_trace_ids=list(state.extraction_trace_ids),
            analysis_trace_ids=list(state.analysis_trace_ids),
            extraction_fact_check_trace_ids=list(state.extraction_fact_check_trace_ids),
            analysis_fact_check_trace_ids=list(state.analysis_fact_check_trace_ids),
        )
        return {
            "type": "task_update",
            "task": response.model_dump(mode="json"),
        }


# 全局单例
_ws_manager_instance: DataProcessTaskWebSocketManager | None = None


def get_data_process_ws_manager() -> DataProcessTaskWebSocketManager:
    """获取 DataProcessTaskWebSocketManager 全局单例."""
    global _ws_manager_instance
    if _ws_manager_instance is None:
        _ws_manager_instance = DataProcessTaskWebSocketManager()
    return _ws_manager_instance
