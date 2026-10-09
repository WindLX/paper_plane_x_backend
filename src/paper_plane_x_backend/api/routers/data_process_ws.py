"""Data Process WebSocket 路由.

提供 data-process 任务状态实时推送，任务状态变更时自动通知前端.
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from paper_plane_x_backend.services.data_process_tasks.ws_manager import (
    get_data_process_ws_manager,
)

router = APIRouter(tags=["data_process_ws"])
logger = logging.getLogger(__name__)


@router.websocket("/ws/data-process")
async def data_process_websocket(websocket: WebSocket) -> None:
    """Data Process 任务状态 WebSocket.

    连接后自动订阅所有任务状态变更推送.

    客户端 → 服务端：
    {
        "type": "ping"
    }

    服务端 → 客户端：
    {
        "type": "task_update",
        "task": {
            "task_id": "tsk-xxx",
            "paper_id": "ppr-xxx",
            "status": "RUNNING",
            "created_at": "...",
            "started_at": "...",
            "finished_at": null,
            "error": null,
            "retry_of_task_id": null,
            "extraction_trace_ids": [],
            "analysis_trace_ids": [],
            "extraction_fact_check_trace_ids": [],
            "analysis_fact_check_trace_ids": []
        }
    }

    {
        "type": "pong"
    }

    {
        "type": "error",
        "detail": "错误信息"
    }
    """
    await websocket.accept()
    manager = get_data_process_ws_manager()
    manager.register_ws(websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "Invalid JSON"})
                continue

            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": f"Unknown message type: {msg_type}",
                    }
                )

    except WebSocketDisconnect:
        logger.debug("event=data_process_ws.disconnected")
    except Exception as exc:
        logger.exception("event=data_process_ws.error")
        await websocket.send_json(
            {"type": "error", "detail": f"WebSocket error: {exc}"}
        )
    finally:
        manager.unregister_ws(websocket)
