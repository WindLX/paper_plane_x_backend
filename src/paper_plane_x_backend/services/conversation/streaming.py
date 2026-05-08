"""Conversation 流式对话辅助逻辑.

将 WebSocket 路由中的状态推进、事件落库与事件推送拆出，
让 router 只负责协议入口与异常边界。
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, TypeAlias, cast

from fastapi import WebSocket

from paper_plane_x_backend.agents.researcher import ResearcherAgent
from paper_plane_x_backend.core.agent_runtime.stream_types import AgentStreamChunk
from paper_plane_x_backend.models.conversation import (
    ConversationMessage,
    ConversationMessageKind,
    ConversationRole,
)
from paper_plane_x_backend.services.conversation.repository import (
    ConversationMessageRepository,
)
from paper_plane_x_backend.utils.ids import generate_message_id

AgentMessagePayload: TypeAlias = dict[str, Any]


class UserStopRequested(Exception):
    """Raised when the client requests to stop the running stream."""


async def stream_agent_with_cancel(
    agent: ResearcherAgent,
    websocket: WebSocket,
) -> AsyncIterator[AgentStreamChunk]:
    """包装 agent.run_stream，使其支持通过 WebSocket stop 消息取消."""
    chunk_queue: asyncio.Queue[AgentStreamChunk] = asyncio.Queue()

    async def producer() -> None:
        try:
            async for chunk in agent.run_stream():
                await chunk_queue.put(chunk)
        except asyncio.CancelledError:
            agent.cancel()
            raise

    producer_task: asyncio.Task[None] = asyncio.create_task(producer())

    try:
        while not producer_task.done():
            ws_future: asyncio.Task[str] = asyncio.create_task(websocket.receive_text())
            chunk_future: asyncio.Task[AgentStreamChunk] = asyncio.create_task(
                chunk_queue.get()
            )

            pending_tasks: tuple[asyncio.Task[object], ...] = (
                cast(asyncio.Task[object], ws_future),
                cast(asyncio.Task[object], chunk_future),
            )
            done, pending = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for future in pending:
                future.cancel()
                try:
                    await future
                except asyncio.CancelledError:
                    pass

            if chunk_future in done:
                yield chunk_future.result()
                continue

            if ws_future in done:
                raw = ws_future.result()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "stop":
                    producer_task.cancel()
                    try:
                        await producer_task
                    except asyncio.CancelledError:
                        pass
                    raise UserStopRequested("User stopped")
                continue

        while not chunk_queue.empty():
            yield chunk_queue.get_nowait()
    finally:
        if not producer_task.done():
            producer_task.cancel()
            try:
                await producer_task
            except asyncio.CancelledError:
                pass


def messages_to_agent_format(
    messages: list[ConversationMessage],
) -> list[AgentMessagePayload]:
    """将数据库消息恢复为 Agent memory 格式."""
    result: list[AgentMessagePayload] = []
    for msg in messages:
        entry: AgentMessagePayload
        if msg.message_kind == "system":
            entry = {"role": "system", "content": msg.content or ""}
        elif msg.message_kind == "user_input":
            content = msg.content or ""
            if msg.paper_ids:
                paper_refs = "\n".join(f"- {pid}" for pid in msg.paper_ids)
                content = f"[用户关注以下文献]\n{paper_refs}\n\n{content}"
            entry = {"role": "user", "content": content}
        elif msg.message_kind == "tool_result":
            entry = {
                "role": "tool",
                "content": msg.content or "",
                "tool_call_id": msg.tool_call_id or "",
                "name": msg.name or "",
            }
        else:
            entry = {"role": "assistant"}
            entry["content"] = msg.content or ""
            if msg.reasoning_content is not None:
                entry["reasoning_content"] = msg.reasoning_content
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls

        if msg.name:
            entry["name"] = msg.name
        if msg.tool_calls and "tool_calls" not in entry:
            entry["tool_calls"] = msg.tool_calls
        if msg.tool_call_id and "tool_call_id" not in entry:
            entry["tool_call_id"] = msg.tool_call_id
        if msg.reasoning_content and "reasoning_content" not in entry:
            entry["reasoning_content"] = msg.reasoning_content
        result.append(entry)
    return result


class ConversationTurnStreamSession:
    """管理单个 conversation turn 的流式落库与回推."""

    def __init__(
        self,
        *,
        websocket: WebSocket,
        message_repo: ConversationMessageRepository,
        agent: ResearcherAgent,
        conversation_id: str,
        turn_id: str,
        user_message: ConversationMessage,
    ) -> None:
        self.websocket = websocket
        self.message_repo = message_repo
        self.agent = agent
        self.conversation_id = conversation_id
        self.turn_id = turn_id
        self.user_message = user_message
        self.next_sequence_no = message_repo.get_next_sequence_no(conversation_id)
        self.last_message_id = user_message.message_id
        self.active_reasoning_msg: ConversationMessage | None = None
        self.active_final_msg: ConversationMessage | None = None
        self.streamed_message_ids: list[str] = []

    async def send_stream_start(self) -> None:
        """向客户端发送 turn 起始事件."""
        await self.websocket.send_json(
            {
                "type": "stream_start",
                "turn_id": self.turn_id,
                "message_id": self.user_message.message_id,
                "message_kind": "user_input",
                "sequence_no": self.user_message.sequence_no,
                "user_message": {
                    "message_id": self.user_message.message_id,
                    "conversation_id": self.user_message.conversation_id,
                    "role": self.user_message.role,
                    "content": self.user_message.content,
                    "name": self.user_message.name,
                    "tool_calls": self.user_message.tool_calls,
                    "tool_call_id": self.user_message.tool_call_id,
                    "sequence_no": self.user_message.sequence_no,
                    "turn_id": self.user_message.turn_id,
                    "parent_message_id": self.user_message.parent_message_id,
                    "message_kind": self.user_message.message_kind,
                    "trace_ids": self.user_message.trace_ids,
                    "reasoning_content": self.user_message.reasoning_content,
                    "images": self.user_message.images,
                    "paper_ids": self.user_message.paper_ids,
                    "created_at": self.user_message.created_at.isoformat(),
                },
            }
        )

    async def handle_chunk(self, chunk: AgentStreamChunk) -> None:
        """将单个 Agent chunk 映射为持久化事件与 WS 推送."""
        should_stream_delta = not chunk.is_complete

        if chunk.reasoning_delta:
            await self._append_reasoning_chunk(
                reasoning_delta=chunk.reasoning_delta,
                step=chunk.step,
                should_stream_delta=should_stream_delta,
            )

        if chunk.delta:
            await self._append_final_chunk(
                delta=chunk.delta,
                step=chunk.step,
                should_stream_delta=should_stream_delta,
            )

        if chunk.tool_call_name:
            tool_call = getattr(chunk, "tool_call", None)
            tool_result = getattr(chunk, "tool_result", None)
            await self._record_tool_activity(
                tool_call_name=chunk.tool_call_name,
                tool_call=tool_call,
                tool_result=tool_result,
                step=chunk.step,
            )

    def finalize(self, trace_ids: list[str]) -> ConversationMessage | None:
        """在 turn 结束时回填 trace_ids，并返回完成事件锚点."""
        trace_target = self.active_final_msg
        if trace_target is None and self.streamed_message_ids:
            trace_target = self.message_repo.get(self.streamed_message_ids[-1])
        if trace_target is not None and trace_ids:
            self.message_repo.update_trace_ids(trace_target.message_id, trace_ids)
        return trace_target

    async def send_stream_complete(
        self,
        *,
        trace_target: ConversationMessage | None,
        trace_ids: list[str],
        completion_status: str = "completed",
        stopped_by_user: bool = False,
    ) -> None:
        """发送 turn 完成事件."""
        await self.websocket.send_json(
            {
                "type": "stream_complete",
                "turn_id": self.turn_id,
                "message_id": trace_target.message_id if trace_target else None,
                "message_kind": (
                    trace_target.message_kind if trace_target else "assistant_final"
                ),
                "sequence_no": trace_target.sequence_no if trace_target else None,
                "trace_ids": trace_ids,
                "completion_status": completion_status,
                "stopped_by_user": stopped_by_user,
            }
        )

    def _create_event_message(
        self,
        *,
        role: ConversationRole,
        message_kind: ConversationMessageKind,
        content_value: str | None = None,
        name: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        reasoning_content: str | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            message_id=generate_message_id(),
            conversation_id=self.conversation_id,
            role=role,
            content=content_value,
            name=name,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            sequence_no=self.next_sequence_no,
            turn_id=self.turn_id,
            parent_message_id=self.last_message_id,
            message_kind=message_kind,
            trace_ids=None,
            reasoning_content=reasoning_content,
            tools=self.agent.tool_registry.to_openai_format(),
        )
        self.message_repo.create(message)
        self.streamed_message_ids.append(message.message_id)
        self.next_sequence_no += 1
        self.last_message_id = message.message_id
        return message

    async def _append_reasoning_chunk(
        self,
        *,
        reasoning_delta: str,
        step: int,
        should_stream_delta: bool,
    ) -> None:
        if self.active_reasoning_msg is None:
            self.active_reasoning_msg = self._create_event_message(
                role="assistant",
                message_kind="assistant_reasoning",
                content_value=None,
                name=self.agent.runtime_name,
                reasoning_content="",
            )
        new_reasoning = (
            self.active_reasoning_msg.reasoning_content or ""
        ) + reasoning_delta
        self.active_reasoning_msg.reasoning_content = new_reasoning
        self.active_reasoning_msg.content = new_reasoning
        self.message_repo.update_fields(
            self.active_reasoning_msg.message_id,
            {
                "content": None,
                "reasoning_content": new_reasoning,
            },
        )
        if should_stream_delta:
            await self.websocket.send_json(
                {
                    "type": "stream_chunk",
                    "turn_id": self.turn_id,
                    "message_id": self.active_reasoning_msg.message_id,
                    "message_kind": "assistant_reasoning",
                    "sequence_no": self.active_reasoning_msg.sequence_no,
                    "delta": "",
                    "reasoning_delta": reasoning_delta,
                    "step": step,
                }
            )

    async def _append_final_chunk(
        self,
        *,
        delta: str,
        step: int,
        should_stream_delta: bool,
    ) -> None:
        if self.active_final_msg is None:
            self.active_final_msg = self._create_event_message(
                role="assistant",
                message_kind="assistant_final",
                content_value="",
                name=self.agent.runtime_name,
            )
        new_content = (self.active_final_msg.content or "") + delta
        self.active_final_msg.content = new_content
        self.message_repo.update_content(self.active_final_msg.message_id, new_content)
        if should_stream_delta:
            await self.websocket.send_json(
                {
                    "type": "stream_chunk",
                    "turn_id": self.turn_id,
                    "message_id": self.active_final_msg.message_id,
                    "message_kind": "assistant_final",
                    "sequence_no": self.active_final_msg.sequence_no,
                    "delta": delta,
                    "reasoning_delta": "",
                    "step": step,
                }
            )

    async def _record_tool_activity(
        self,
        *,
        tool_call_name: str,
        tool_call: dict[str, Any] | None,
        tool_result: dict[str, Any] | None,
        step: int,
    ) -> None:
        self.active_reasoning_msg = None
        self.active_final_msg = None

        tool_call_payload: list[dict[str, Any]] | None = (
            [tool_call] if isinstance(tool_call, dict) else None
        )
        tool_call_msg = self._create_event_message(
            role="assistant",
            message_kind="assistant_tool_call",
            content_value=None,
            name=self.agent.runtime_name,
            tool_calls=tool_call_payload,
        )
        await self.websocket.send_json(
            {
                "type": "tool_call",
                "turn_id": self.turn_id,
                "message_id": tool_call_msg.message_id,
                "message_kind": "assistant_tool_call",
                "sequence_no": tool_call_msg.sequence_no,
                "name": tool_call_name,
                "tool_call": tool_call,
                "step": step,
            }
        )

        if tool_result:
            tool_result_msg = self._create_event_message(
                role="tool",
                message_kind="tool_result",
                content_value=tool_result.get("content"),
                name=tool_result.get("name"),
                tool_call_id=tool_result.get("tool_call_id"),
            )
            await self.websocket.send_json(
                {
                    "type": "tool_result",
                    "turn_id": self.turn_id,
                    "message_id": tool_result_msg.message_id,
                    "message_kind": "tool_result",
                    "sequence_no": tool_result_msg.sequence_no,
                    "tool_call_id": tool_result_msg.tool_call_id,
                    "name": tool_result_msg.name,
                    "content": tool_result_msg.content,
                    "step": step,
                }
            )
