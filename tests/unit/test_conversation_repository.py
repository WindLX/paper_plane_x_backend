"""ConversationRepository tests."""

from datetime import datetime

import pytest

from paper_plane_x_backend.models.conversation import Conversation, ConversationMessage
from paper_plane_x_backend.services.conversation.repository import (
    ConversationMessageRepository,
    ConversationRepository,
    ConversationRepositoryError,
)


def _create_project(db, project_id: str) -> None:
    """Helper: 在数据库中创建测试项目."""
    db.insert(
        "projects",
        {
            "project_id": project_id,
            "name": f"Project {project_id}",
            "description": None,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "operation_logs": "[]",
        },
    )


class TestConversationRepository:
    """ConversationRepository 测试类."""

    def test_create_and_get(self, db) -> None:
        """验证创建会话后可正确读取."""
        _create_project(db, "prj-test")
        repo = ConversationRepository(db)
        conversation = repo.create(project_id="prj-test", title="Test Conversation")

        fetched = repo.get(conversation.conversation_id)
        assert fetched is not None
        assert fetched.conversation_id == conversation.conversation_id
        assert fetched.project_id == "prj-test"
        assert fetched.title == "Test Conversation"
        assert fetched.forked_from_conversation_id is None

    def test_get_returns_none_for_missing(self, db) -> None:
        """验证获取不存在的会话返回 None."""
        repo = ConversationRepository(db)
        assert repo.get("non-existent") is None

    def test_list_by_project(self, db) -> None:
        """验证按项目列出的会话按 updated_at 倒序排列."""
        _create_project(db, "prj-1")
        _create_project(db, "prj-2")
        repo = ConversationRepository(db)
        c1 = repo.create(project_id="prj-1", title="First")
        c2 = repo.create(project_id="prj-1", title="Second")
        repo.create(project_id="prj-2", title="Other")

        items = repo.list_by_project("prj-1")
        assert len(items) == 2
        # 倒序排列，后创建的在前
        assert items[0].conversation_id == c2.conversation_id
        assert items[1].conversation_id == c1.conversation_id

    def test_update_title(self, db) -> None:
        """验证更新标题."""
        _create_project(db, "prj-test")
        repo = ConversationRepository(db)
        conversation = repo.create(project_id="prj-test", title="Old Title")
        repo.update_title(conversation.conversation_id, "New Title")

        fetched = repo.get(conversation.conversation_id)
        assert fetched is not None
        assert fetched.title == "New Title"

    def test_touch_updates_timestamp(self, db) -> None:
        """验证 touch 更新 updated_at."""
        _create_project(db, "prj-test")
        repo = ConversationRepository(db)
        conversation = repo.create(project_id="prj-test", title="Test")
        old_updated = conversation.updated_at

        repo.touch(conversation.conversation_id)

        fetched = repo.get(conversation.conversation_id)
        assert fetched is not None
        assert fetched.updated_at > old_updated

    def test_delete(self, db) -> None:
        """验证删除会话."""
        _create_project(db, "prj-test")
        repo = ConversationRepository(db)
        conversation = repo.create(project_id="prj-test", title="To Delete")
        repo.delete(conversation.conversation_id)

        assert repo.get(conversation.conversation_id) is None

    def test_ensure_exists_raises(self, db) -> None:
        """验证 ensure_exists 对不存在会话抛出异常."""
        repo = ConversationRepository(db)
        with pytest.raises(ConversationRepositoryError, match="not found") as exc_info:
            repo.ensure_exists("missing")
        assert exc_info.value.error_code == "not_found"

    def test_fork(self, db) -> None:
        """验证 Fork 复制会话及消息."""
        _create_project(db, "prj-test")
        repo = ConversationRepository(db)
        msg_repo = ConversationMessageRepository(db)

        source = repo.create(project_id="prj-test", title="Source")
        msg1 = ConversationMessage(
            message_id="msg-1",
            conversation_id=source.conversation_id,
            role="user",
            content="Hello",
        )
        msg2 = ConversationMessage(
            message_id="msg-2",
            conversation_id=source.conversation_id,
            role="assistant",
            content="Hi",
        )
        msg_repo.create(msg1)
        msg_repo.create(msg2)

        forked = repo.fork(
            source_conversation_id=source.conversation_id,
            title="Forked",
            message_repo=msg_repo,
        )

        assert forked.title == "Forked"
        assert forked.project_id == "prj-test"
        assert forked.forked_from_conversation_id == source.conversation_id

        forked_messages = msg_repo.list_by_conversation(forked.conversation_id)
        assert len(forked_messages) == 2
        assert forked_messages[0].role == "user"
        assert forked_messages[0].content == "Hello"
        assert forked_messages[1].role == "assistant"
        assert forked_messages[1].content == "Hi"
        # Fork 后的消息应该有新的 message_id
        assert forked_messages[0].message_id != "msg-1"

    def test_fork_source_not_found(self, db) -> None:
        """验证 Fork 来源不存在时抛出异常."""
        repo = ConversationRepository(db)
        with pytest.raises(ConversationRepositoryError, match="not found") as exc_info:
            repo.fork("non-existent")
        assert exc_info.value.error_code == "not_found"


class TestConversationMessageRepository:
    """ConversationMessageRepository 测试类."""

    @pytest.fixture
    def conversation(self, db) -> Conversation:
        """创建测试会话."""
        _create_project(db, "prj-test")
        repo = ConversationRepository(db)
        return repo.create(project_id="prj-test", title="Test")

    def test_create_and_get(self, db, conversation) -> None:
        """验证创建消息后可正确读取."""
        repo = ConversationMessageRepository(db)
        message = ConversationMessage(
            message_id="msg-test-1",
            conversation_id=conversation.conversation_id,
            role="user",
            content="Hello",
        )
        repo.create(message)

        fetched = repo.get("msg-test-1")
        assert fetched is not None
        assert fetched.message_id == "msg-test-1"
        assert fetched.role == "user"
        assert fetched.content == "Hello"

    def test_list_by_conversation(self, db, conversation) -> None:
        """验证按会话列出消息按创建时间正序排列."""
        repo = ConversationMessageRepository(db)
        msg1 = ConversationMessage(
            message_id="msg-1",
            conversation_id=conversation.conversation_id,
            role="user",
            content="First",
        )
        msg2 = ConversationMessage(
            message_id="msg-2",
            conversation_id=conversation.conversation_id,
            role="assistant",
            content="Second",
        )
        repo.create(msg1)
        repo.create(msg2)

        items = repo.list_by_conversation(conversation.conversation_id)
        assert len(items) == 2
        assert items[0].message_id == "msg-1"
        assert items[1].message_id == "msg-2"

    def test_update_content(self, db, conversation) -> None:
        """验证更新消息内容."""
        repo = ConversationMessageRepository(db)
        message = ConversationMessage(
            message_id="msg-update",
            conversation_id=conversation.conversation_id,
            role="user",
            content="Original",
        )
        repo.create(message)
        repo.update_content("msg-update", "Updated")

        fetched = repo.get("msg-update")
        assert fetched is not None
        assert fetched.content == "Updated"

    def test_update_trace_ids(self, db, conversation) -> None:
        """验证更新 trace_ids."""
        repo = ConversationMessageRepository(db)
        message = ConversationMessage(
            message_id="msg-traces",
            conversation_id=conversation.conversation_id,
            role="assistant",
            content="Hello",
        )
        repo.create(message)
        repo.update_trace_ids("msg-traces", ["trc-1", "trc-2"])

        fetched = repo.get("msg-traces")
        assert fetched is not None
        assert fetched.trace_ids == ["trc-1", "trc-2"]

    def test_update_reasoning_content(self, db, conversation) -> None:
        """验证更新 reasoning_content."""
        repo = ConversationMessageRepository(db)
        message = ConversationMessage(
            message_id="msg-reasoning",
            conversation_id=conversation.conversation_id,
            role="assistant",
            content="Answer",
        )
        repo.create(message)
        repo.update_reasoning_content("msg-reasoning", "Thinking process")

        fetched = repo.get("msg-reasoning")
        assert fetched is not None
        assert fetched.reasoning_content == "Thinking process"

    def test_delete(self, db, conversation) -> None:
        """验证删除单条消息."""
        repo = ConversationMessageRepository(db)
        message = ConversationMessage(
            message_id="msg-delete",
            conversation_id=conversation.conversation_id,
            role="user",
            content="Delete me",
        )
        repo.create(message)
        repo.delete("msg-delete")

        assert repo.get("msg-delete") is None

    def test_delete_after(self, db, conversation) -> None:
        """验证删除某条消息之后的所有消息."""
        repo = ConversationMessageRepository(db)
        for i in range(3):
            msg = ConversationMessage(
                message_id=f"msg-{i}",
                conversation_id=conversation.conversation_id,
                role="user",
                content=f"Message {i}",
            )
            repo.create(msg)

        deleted = repo.delete_after(conversation.conversation_id, "msg-1")
        assert deleted == 1  # msg-2 被删除

        items = repo.list_by_conversation(conversation.conversation_id)
        assert len(items) == 2
        assert items[0].message_id == "msg-0"
        assert items[1].message_id == "msg-1"

    def test_delete_after_returns_zero_for_missing(self, db, conversation) -> None:
        """验证 delete_after 对不存在消息返回 0."""
        repo = ConversationMessageRepository(db)
        deleted = repo.delete_after(conversation.conversation_id, "non-existent")
        assert deleted == 0

    def test_delete_all_by_conversation(self, db, conversation) -> None:
        """验证删除会话的所有消息."""
        repo = ConversationMessageRepository(db)
        for i in range(3):
            msg = ConversationMessage(
                message_id=f"msg-{i}",
                conversation_id=conversation.conversation_id,
                role="user",
                content=f"Message {i}",
            )
            repo.create(msg)

        deleted = repo.delete_all_by_conversation(conversation.conversation_id)
        assert deleted == 3
        assert repo.list_by_conversation(conversation.conversation_id) == []

    def test_tool_calls_roundtrip(self, db, conversation) -> None:
        """验证 tool_calls JSON 序列化/反序列化."""
        repo = ConversationMessageRepository(db)
        tool_calls = [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "search_paper", "arguments": '{"q": "test"}'},
            }
        ]
        message = ConversationMessage(
            message_id="msg-tool",
            conversation_id=conversation.conversation_id,
            role="assistant",
            content="Using tool",
            tool_calls=tool_calls,
        )
        repo.create(message)

        fetched = repo.get("msg-tool")
        assert fetched is not None
        assert fetched.tool_calls is not None
        assert len(fetched.tool_calls) == 1
        assert fetched.tool_calls[0]["id"] == "call-1"
