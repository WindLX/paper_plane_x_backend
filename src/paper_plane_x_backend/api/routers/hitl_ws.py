"""HITL (Human-in-the-loop) WebSocket 路由.

提供实时的人类交互能力，Agent 可通过 ask_human 工具向用户提问，
用户通过此 WebSocket 接收问题并提交回答。
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from paper_plane_x_backend.services.hitl import get_hitl_manager

router = APIRouter(tags=["hitl_ws"])
logger = logging.getLogger(__name__)


@router.websocket("/ws/hitl")
async def hitl_websocket(websocket: WebSocket) -> None:
    """HITL WebSocket.

    连接后立即推送所有当前 pending 的问题。

    客户端 → 服务端：
    {
        "type": "answer",
        "question_id": "hit-xxx",
        "answers": [
            {"question_index": 0, "selected_option_ids": ["opt-1"], "custom_text": ""},
            ...
        ]
    }

    服务端 → 客户端：
    {
        "type": "hitl_question",
        "question_id": "hit-xxx",
        "project_id": "prj-xxx",
        "conversation_id": "cnv-xxx",
        "questions": [
            {
                "text": "问题文本",
                "options": [{"id": "opt-1", "text": "选项A"}],
                "allow_multiple": false,
                "custom_answer_label": "其他（请自定义回答）"
            }
        ],
        "created_at": 1234567890.0
    }

    {
        "type": "hitl_answered",
        "question_id": "hit-xxx"
    }

    {
        "type": "error",
        "detail": "错误信息"
    }
    """
    await websocket.accept()
    manager = get_hitl_manager()
    manager.register_ws(websocket)

    # 推送所有当前 pending 的问题
    for record in manager.list_pending():
        try:
            await websocket.send_json(
                {
                    "type": "hitl_question",
                    **record.to_dict(),
                }
            )
        except Exception:
            logger.debug(
                "event=hitl.ws_push_pending_failed question_id=%s", record.question_id
            )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "Invalid JSON"})
                continue

            msg_type = data.get("type")

            if msg_type == "answer":
                question_id = data.get("question_id")
                answers = data.get("answers", [])
                if not question_id:
                    await websocket.send_json(
                        {"type": "error", "detail": "Missing question_id"}
                    )
                    continue

                success = manager.answer_question(question_id, answers)
                if success:
                    await websocket.send_json(
                        {
                            "type": "hitl_answered",
                            "question_id": question_id,
                        }
                    )
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "detail": f"Question {question_id} not found or already answered",
                        }
                    )
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": f"Unknown message type: {msg_type}",
                    }
                )

    except WebSocketDisconnect:
        logger.info("event=hitl_ws.disconnected")
    except Exception as exc:
        logger.exception("event=hitl_ws.error")
        await websocket.send_json(
            {"type": "error", "detail": f"WebSocket error: {exc}"}
        )
    finally:
        manager.unregister_ws(websocket)
