"""Conversation WebSocket 集成测试."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import patch

from fastapi.testclient import TestClient

from paper_plane_x_backend.services import Database
from paper_plane_x_backend.services.conversation.repository import (
    ConversationMessageRepository,
)


class MockChunk:
    """模拟 AgentStreamChunk."""

    def __init__(
        self,
        delta: str = "",
        reasoning_delta: str = "",
        tool_call_name: str | None = None,
        is_complete: bool = False,
        step: int = 0,
    ):
        self.delta = delta
        self.reasoning_delta = reasoning_delta
        self.tool_call_name = tool_call_name
        self.is_complete = is_complete
        self.step = step


async def _mock_run_stream() -> AsyncGenerator:
    """模拟流式输出."""
    yield MockChunk(delta="Hello", step=1)
    yield MockChunk(delta=" world!", is_complete=True, step=1)


class TestConversationWebSocket:
    """Conversation WebSocket 测试类."""

    def test_websocket_connection_accepted(self, client: TestClient) -> None:
        """测试 WebSocket 连接可被接受."""
        # 先创建项目和会话
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "WS Test"},
        )
        project_id = project_resp.json()["project_id"]

        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "WS Conversation"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        with patch(
            "paper_plane_x_backend.agents.researcher.ResearcherAgent.run_stream",
            return_value=_mock_run_stream(),
        ):
            with client.websocket_connect(
                f"/api/v1/ws/conversations/{conversation_id}"
            ) as websocket:
                # 发送消息
                websocket.send_json(
                    {
                        "type": "user_message",
                        "content": "Hello",
                    }
                )

                # 接收 stream_start
                msg1 = websocket.receive_json()
                assert msg1["type"] == "stream_start"
                assert msg1["message_id"].startswith("msg-")

                # 接收 stream_chunk
                msg2 = websocket.receive_json()
                assert msg2["type"] == "stream_chunk"
                assert msg2["delta"] == "Hello"

                # 接收 stream_complete（最后一个 chunk 带有 is_complete）
                msg3 = websocket.receive_json()
                assert msg3["type"] == "stream_complete"
                assert msg3["message_id"].startswith("msg-")

    def test_websocket_invalid_conversation(self, client: TestClient) -> None:
        """测试连接不存在的会话返回错误."""
        with client.websocket_connect(
            "/api/v1/ws/conversations/non-existent"
        ) as websocket:
            msg = websocket.receive_json()
            assert msg["type"] == "error"
            assert "not found" in msg["detail"].lower()

    def test_websocket_invalid_json(self, client: TestClient) -> None:
        """测试发送无效 JSON 返回错误."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "WS Invalid JSON Test"},
        )
        project_id = project_resp.json()["project_id"]

        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "WS Invalid"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        with client.websocket_connect(
            f"/api/v1/ws/conversations/{conversation_id}"
        ) as websocket:
            websocket.send_text("not-json")
            msg = websocket.receive_json()
            assert msg["type"] == "error"
            assert "Invalid JSON" in msg["detail"]

    def test_websocket_unknown_message_type(self, client: TestClient) -> None:
        """测试发送未知消息类型返回错误."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "WS Unknown Type Test"},
        )
        project_id = project_resp.json()["project_id"]

        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "WS Unknown"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        with client.websocket_connect(
            f"/api/v1/ws/conversations/{conversation_id}"
        ) as websocket:
            websocket.send_json({"type": "unknown_type", "data": "test"})
            msg = websocket.receive_json()
            assert msg["type"] == "error"
            assert "Unknown message type" in msg["detail"]

    def test_websocket_stop_message(self, client: TestClient) -> None:
        """测试发送 stop 消息."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "WS Stop Test"},
        )
        project_id = project_resp.json()["project_id"]

        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "WS Stop"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        with client.websocket_connect(
            f"/api/v1/ws/conversations/{conversation_id}"
        ) as websocket:
            websocket.send_json({"type": "stop"})
            msg = websocket.receive_json()
            assert msg["type"] == "stream_complete"
            assert msg["message_id"] is None

    def test_websocket_edit_message(self, client: TestClient) -> None:
        """测试编辑已有消息后重新生成."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "WS Edit Test"},
        )
        project_id = project_resp.json()["project_id"]

        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "WS Edit"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        # 先创建一条用户消息
        msg_resp = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"role": "user", "content": "Original"},
        )
        message_id = msg_resp.json()["message_id"]

        with patch(
            "paper_plane_x_backend.agents.researcher.ResearcherAgent.run_stream",
            return_value=_mock_run_stream(),
        ):
            with client.websocket_connect(
                f"/api/v1/ws/conversations/{conversation_id}"
            ) as websocket:
                # 编辑已有消息
                websocket.send_json(
                    {
                        "type": "user_message",
                        "content": "Edited",
                        "message_id": message_id,
                    }
                )

                # 接收 stream_start
                msg1 = websocket.receive_json()
                assert msg1["type"] == "stream_start"

                # 接收流式响应
                msg2 = websocket.receive_json()
                assert msg2["type"] == "stream_chunk"

                # 接收完成（最后一个 chunk 带有 is_complete）
                msg3 = websocket.receive_json()
                assert msg3["type"] == "stream_complete"

        # 确认原消息已被更新
        list_resp = client.get(f"/api/v1/conversations/{conversation_id}/messages")
        messages = list_resp.json()
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) == 1
        assert user_messages[0]["content"] == "Edited"

    def test_websocket_edit_nonexistent_message(self, client: TestClient) -> None:
        """测试编辑不存在的消息返回错误."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "WS Edit NF Test"},
        )
        project_id = project_resp.json()["project_id"]

        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "WS Edit NF"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        with client.websocket_connect(
            f"/api/v1/ws/conversations/{conversation_id}"
        ) as websocket:
            websocket.send_json(
                {
                    "type": "user_message",
                    "content": "Edited",
                    "message_id": "non-existent",
                }
            )
            msg = websocket.receive_json()
            assert msg["type"] == "error"
            assert "not found" in msg["detail"].lower()

    def test_websocket_tool_call_event(self, client: TestClient) -> None:
        """测试工具调用事件推送."""

        async def _mock_with_tool() -> AsyncGenerator:
            yield MockChunk(delta="Thinking", step=1)
            yield MockChunk(tool_call_name="search_paper", step=1)
            yield MockChunk(delta="Done", is_complete=True, step=1)

        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "WS Tool Test"},
        )
        project_id = project_resp.json()["project_id"]

        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "WS Tool"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        with patch(
            "paper_plane_x_backend.agents.researcher.ResearcherAgent.run_stream",
            return_value=_mock_with_tool(),
        ):
            with client.websocket_connect(
                f"/api/v1/ws/conversations/{conversation_id}"
            ) as websocket:
                websocket.send_json(
                    {
                        "type": "user_message",
                        "content": "Search papers",
                    }
                )

                # stream_start
                msg1 = websocket.receive_json()
                assert msg1["type"] == "stream_start"

                # stream_chunk
                msg2 = websocket.receive_json()
                assert msg2["type"] == "stream_chunk"

                # tool_call
                msg3 = websocket.receive_json()
                assert msg3["type"] == "tool_call"
                assert msg3["name"] == "search_paper"

                # stream_complete
                msg4 = websocket.receive_json()
                assert msg4["type"] == "stream_complete"

    def test_websocket_messages_persisted(
        self, client: TestClient, db: Database
    ) -> None:
        """测试 WebSocket 对话后消息被持久化到数据库."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "WS Persist Test"},
        )
        project_id = project_resp.json()["project_id"]

        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "WS Persist"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        with patch(
            "paper_plane_x_backend.agents.researcher.ResearcherAgent.run_stream",
            return_value=_mock_run_stream(),
        ):
            with client.websocket_connect(
                f"/api/v1/ws/conversations/{conversation_id}"
            ) as websocket:
                websocket.send_json(
                    {
                        "type": "user_message",
                        "content": "Hello",
                    }
                )

                # 消费所有消息
                while True:
                    msg = websocket.receive_json()
                    if msg["type"] == "stream_complete":
                        break

        # 验证数据库中消息数量
        rows = db.fetchall(
            "SELECT * FROM conversation_messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        assert len(rows) == 2  # user + assistant
        roles = [row["role"] for row in rows]
        assert "user" in roles
        assert "assistant" in roles

    def test_websocket_long_stream_throttles_database_updates(
        self, client: TestClient, db: Database
    ) -> None:
        """长流式输出不会对每个 chunk 都完整更新一次数据库."""

        async def _mock_long_stream() -> AsyncGenerator:
            for _ in range(1500):
                yield MockChunk(delta="x", step=1)
            yield MockChunk(is_complete=True, step=1)

        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "WS Long Stream Test"},
        )
        project_id = project_resp.json()["project_id"]

        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "WS Long Stream"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        original_update_content = ConversationMessageRepository.update_content
        update_contents: list[str] = []

        def counted_update_content(
            repo: ConversationMessageRepository,
            message_id: str,
            content: str,
        ) -> None:
            update_contents.append(content)
            original_update_content(repo, message_id, content)

        with (
            patch.object(
                ConversationMessageRepository,
                "update_content",
                counted_update_content,
            ),
            patch(
                "paper_plane_x_backend.agents.researcher.ResearcherAgent.run_stream",
                return_value=_mock_long_stream(),
            ),
        ):
            with client.websocket_connect(
                f"/api/v1/ws/conversations/{conversation_id}"
            ) as websocket:
                websocket.send_json(
                    {
                        "type": "user_message",
                        "content": "Generate a long answer",
                    }
                )

                stream_chunks = 0
                while True:
                    msg = websocket.receive_json()
                    if msg["type"] == "stream_chunk":
                        stream_chunks += 1
                    if msg["type"] == "stream_complete":
                        break

        rows = db.fetchall(
            """
            SELECT * FROM conversation_messages
            WHERE conversation_id = ? AND message_kind = 'assistant_final'
            """,
            (conversation_id,),
        )
        assert stream_chunks == 1500
        assert len(rows) == 1
        assert rows[0]["content"] == "x" * 1500
        assert update_contents[-1] == "x" * 1500
        assert len(update_contents) < 50

    def test_websocket_stop_flushes_partial_stream(
        self, client: TestClient, db: Database
    ) -> None:
        """用户 stop 后已生成内容会被保存."""

        async def _mock_stoppable_stream() -> AsyncGenerator:
            yield MockChunk(delta="partial", step=1)
            while True:
                await asyncio.sleep(0.01)
                yield MockChunk(delta=" more", step=1)

        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "WS Stop Flush Test"},
        )
        project_id = project_resp.json()["project_id"]

        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "WS Stop Flush"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        with patch(
            "paper_plane_x_backend.agents.researcher.ResearcherAgent.run_stream",
            return_value=_mock_stoppable_stream(),
        ):
            with client.websocket_connect(
                f"/api/v1/ws/conversations/{conversation_id}"
            ) as websocket:
                websocket.send_json(
                    {
                        "type": "user_message",
                        "content": "Start then stop",
                    }
                )

                while True:
                    msg = websocket.receive_json()
                    if msg["type"] == "stream_chunk":
                        assert msg["delta"].startswith("partial")
                        websocket.send_json({"type": "stop"})
                        break

                while True:
                    msg = websocket.receive_json()
                    if msg["type"] == "stream_complete":
                        assert msg["completion_status"] == "stopped"
                        assert msg["stopped_by_user"] is True
                        break

        rows = db.fetchall(
            """
            SELECT * FROM conversation_messages
            WHERE conversation_id = ? AND message_kind = 'assistant_final'
            """,
            (conversation_id,),
        )
        assert len(rows) == 1
        assert rows[0]["content"].startswith("partial")
