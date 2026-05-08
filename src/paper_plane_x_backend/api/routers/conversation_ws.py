"""Conversation WebSocket 路由.

提供流式对话能力，通过 WebSocket 接收用户消息并流式推送 Agent 响应。
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from paper_plane_x_backend.agents.researcher import ResearcherAgent
from paper_plane_x_backend.api.dependencies import get_database
from paper_plane_x_backend.models.conversation import ConversationMessage
from paper_plane_x_backend.services import Database
from paper_plane_x_backend.services.conversation.repository import (
    ConversationMessageRepository,
    ConversationRepository,
)
from paper_plane_x_backend.services.conversation.streaming import (
    ConversationTurnStreamSession,
    UserStopRequested,
    messages_to_agent_format,
    stream_agent_with_cancel,
)
from paper_plane_x_backend.services.project.repository import ProjectRepository
from paper_plane_x_backend.utils.ids import generate_message_id, generate_turn_id

router = APIRouter(tags=["conversations_ws"])
logger = logging.getLogger(__name__)


async def _send_error(websocket: WebSocket, detail: str) -> None:
    await websocket.send_json({"type": "error", "detail": detail})


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_websocket(
    websocket: WebSocket,
    conversation_id: str,
    db: Database = Depends(get_database),
) -> None:
    """Conversation 流式对话 WebSocket.

    消息协议（JSON）：
    客户端 → 服务端：
    {
        "type": "user_message",
        "content": "用户输入文本",
        "message_id": "可选，用于编辑已有消息",
        "images": ["可选，base64 图片列表"],
        "paper_ids": ["可选，用户关注的文献 ID 列表"]
    }
    {
        "type": "stop"
    }

    服务端 → 客户端：
    {
        "type": "stream_start",
        "message_id": "msg-xxx"
    }
    {
        "type": "stream_chunk",
        "delta": "文本片段",
        "reasoning_delta": "思考片段"
    }
    {
        "type": "tool_call",
        "name": "tool_name"
    }
    {
        "type": "stream_complete",
        "message_id": "msg-xxx",
        "trace_ids": ["trc-xxx"]
    }
    {
        "type": "error",
        "detail": "错误信息"
    }
    """
    await websocket.accept()
    convo_repo = ConversationRepository(db)
    msg_repo = ConversationMessageRepository(db)

    # 验证 conversation 存在
    conversation = convo_repo.get(conversation_id)
    if conversation is None:
        await _send_error(websocket, f"Conversation {conversation_id} not found")
        await websocket.close()
        return

    # 验证 project 存在
    project_repo = ProjectRepository(db)
    project = project_repo.get(conversation.project_id)
    if project is None:
        await _send_error(
            websocket,
            f"Project {conversation.project_id} not found",
        )
        await websocket.close()
        return

    # 初始化 Agent
    agent = ResearcherAgent(
        project_id=conversation.project_id,
        caller="conversation",
        caller_id=conversation_id,
        conversation_id=conversation_id,
    )

    # 加载历史消息到 Agent memory
    history = msg_repo.list_by_conversation(conversation_id)
    agent.set_memory(messages_to_agent_format(history))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, "Invalid JSON")
                continue

            msg_type = data.get("type")

            if msg_type == "user_message":
                content = data.get("content", "")
                edit_message_id = data.get("message_id")
                images = data.get("images")
                paper_ids = data.get("paper_ids")

                # 保存或更新用户消息
                if edit_message_id:
                    user_msg = msg_repo.get(edit_message_id)
                    if user_msg and user_msg.conversation_id == conversation_id:
                        turn_id = user_msg.turn_id or generate_turn_id()
                        update_payload: dict[str, object] = {
                            "content": content,
                            "turn_id": turn_id,
                            "message_kind": "user_input",
                        }
                        if images is not None:
                            update_payload["images"] = images
                        if paper_ids is not None:
                            update_payload["paper_ids"] = paper_ids
                        msg_repo.update_fields(
                            edit_message_id,
                            update_payload,
                        )
                        user_msg.content = content
                        user_msg.turn_id = turn_id
                        user_msg.message_kind = "user_input"
                        if images is not None:
                            user_msg.images = images
                        if paper_ids is not None:
                            user_msg.paper_ids = paper_ids
                        msg_repo.delete_after(conversation_id, edit_message_id)
                    else:
                        await _send_error(
                            websocket,
                            f"Message {edit_message_id} not found",
                        )
                        continue
                else:
                    turn_id = generate_turn_id()
                    prior_history = msg_repo.list_by_conversation(conversation_id)
                    parent_message_id = (
                        prior_history[-1].message_id if prior_history else None
                    )
                    user_msg = ConversationMessage(
                        message_id=generate_message_id(),
                        conversation_id=conversation_id,
                        role="user",
                        content=content,
                        sequence_no=msg_repo.get_next_sequence_no(conversation_id),
                        turn_id=turn_id,
                        parent_message_id=parent_message_id,
                        message_kind="user_input",
                        images=images,
                        paper_ids=paper_ids,
                    )
                    msg_repo.create(user_msg)

                turn_id = user_msg.turn_id or generate_turn_id()

                convo_repo.touch(conversation_id)

                try:
                    project_repo.update_operation_logs(
                        project_id=conversation.project_id,
                        operation="conversation_user_message",
                        detail={
                            "conversation_id": conversation_id,
                            "message_id": edit_message_id or user_msg.message_id,
                            "edit": bool(edit_message_id),
                        },
                    )
                except Exception:
                    logger.warning(
                        "event=conversation_ws.project_log_failed project_id=%s",
                        conversation.project_id,
                        exc_info=True,
                    )

                # 重新加载历史到 Agent
                history = msg_repo.list_by_conversation(conversation_id)
                agent.reset_memory()
                agent.set_memory(messages_to_agent_format(history))
                turn_session = ConversationTurnStreamSession(
                    websocket=websocket,
                    message_repo=msg_repo,
                    agent=agent,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    user_message=user_msg,
                )
                await turn_session.send_stream_start()

                # 流式执行 Agent（支持外部取消）
                try:
                    async for chunk in stream_agent_with_cancel(agent, websocket):
                        await turn_session.handle_chunk(chunk)
                except UserStopRequested:
                    logger.info(
                        "event=conversation_ws.user_stopped conversation_id=%s",
                        conversation_id,
                    )
                    convo_repo.touch(conversation_id)
                    trace_target = turn_session.finalize(agent.trace_ids)
                    await turn_session.send_stream_complete(
                        trace_target=trace_target,
                        trace_ids=agent.trace_ids,
                        completion_status="stopped",
                        stopped_by_user=True,
                    )
                    continue
                except asyncio.CancelledError:
                    logger.info(
                        "event=conversation_ws.user_cancelled conversation_id=%s",
                        conversation_id,
                    )
                    msg_repo.delete_after(conversation_id, user_msg.message_id)
                except Exception as exc:
                    logger.exception(
                        "event=conversation_ws.agent_error conversation_id=%s",
                        conversation_id,
                    )
                    await _send_error(websocket, f"Agent execution failed: {exc}")
                    msg_repo.delete_after(conversation_id, user_msg.message_id)
                    continue

                convo_repo.touch(conversation_id)
                trace_target = turn_session.finalize(agent.trace_ids)
                await turn_session.send_stream_complete(
                    trace_target=trace_target,
                    trace_ids=agent.trace_ids,
                )

            elif msg_type == "stop":
                # Agent 未在运行时收到 stop，直接返回完成事件
                logger.info(
                    "event=conversation_ws.stop_no_agent conversation_id=%s",
                    conversation_id,
                )
                await websocket.send_json(
                    {
                        "type": "stream_complete",
                        "message_id": None,
                        "trace_ids": [],
                        "completion_status": "stopped",
                        "stopped_by_user": True,
                    }
                )

            else:
                await _send_error(websocket, f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info(
            "event=conversation_ws.disconnected conversation_id=%s",
            conversation_id,
        )
    except Exception as exc:
        logger.exception(
            "event=conversation_ws.error conversation_id=%s",
            conversation_id,
        )
        await _send_error(websocket, f"WebSocket error: {exc}")
        await websocket.close()
