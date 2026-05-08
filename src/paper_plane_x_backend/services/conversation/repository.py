"""Conversation 数据仓库.

封装 conversations 表和 conversation_messages 表的数据库访问。
"""

import logging
from collections import OrderedDict
from datetime import datetime
from typing import Any, Literal, cast

from paper_plane_x_backend.models.conversation import Conversation, ConversationMessage
from paper_plane_x_backend.schemas.api.conversation import (
    ConversationTurnEventResponse,
    ConversationTurnResponse,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.utils.ids import (
    generate_conversation_id,
    generate_message_id,
    generate_turn_id,
)

logger = logging.getLogger(__name__)


class ConversationRepositoryError(Exception):
    """ConversationRepository 异常."""

    def __init__(
        self,
        message: str,
        conversation_id: str | None = None,
        error_code: str = "bad_request",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.conversation_id = conversation_id
        self.error_code = error_code


class ConversationRepository:
    """Conversation 数据访问层."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, project_id: str, title: str = "New Conversation") -> Conversation:
        """创建新会话."""
        now = datetime.now()
        conversation = Conversation(
            conversation_id=generate_conversation_id(),
            project_id=project_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self.db.insert("conversations", conversation.to_db_dict())
        logger.info(
            "event=conversation.created conversation_id=%s project_id=%s",
            conversation.conversation_id,
            project_id,
        )
        return conversation

    def get(self, conversation_id: str) -> Conversation | None:
        """获取会话详情."""
        row = self.db.fetchone(
            "SELECT * FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        if not row:
            return None
        return Conversation.from_db_row(row)

    def list_by_project(self, project_id: str) -> list[Conversation]:
        """列出项目下的所有会话（按 updated_at 倒序）."""
        rows = self.db.fetchall(
            "SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        )
        return [Conversation.from_db_row(row) for row in rows]

    def update_title(self, conversation_id: str, title: str) -> None:
        """更新会话标题."""
        self.db.update(
            "conversations",
            {"title": title, "updated_at": datetime.now()},
            "conversation_id = ?",
            (conversation_id,),
        )
        logger.info(
            "event=conversation.title_updated conversation_id=%s title=%s",
            conversation_id,
            title,
        )

    def touch(self, conversation_id: str) -> None:
        """更新会话的 updated_at 时间戳."""
        self.db.update(
            "conversations",
            {"updated_at": datetime.now()},
            "conversation_id = ?",
            (conversation_id,),
        )

    def delete(self, conversation_id: str) -> None:
        """删除会话（级联删除消息）."""
        self.db.delete("conversations", "conversation_id = ?", (conversation_id,))
        logger.info("event=conversation.deleted conversation_id=%s", conversation_id)

    def count_by_project(self, project_id: str) -> int:
        """统计项目下的会话数量."""
        row = self.db.fetchone(
            "SELECT COUNT(*) as count FROM conversations WHERE project_id = ?",
            (project_id,),
        )
        return int(row["count"]) if row else 0

    def fork(
        self,
        source_conversation_id: str,
        title: str | None = None,
        forked_at_message_id: str | None = None,
        message_repo: "ConversationMessageRepository | None" = None,
    ) -> Conversation:
        """Fork 复制会话.

        创建新会话并复制原会话的所有消息。
        """
        source = self.get(source_conversation_id)
        if source is None:
            raise ConversationRepositoryError(
                f"Source conversation {source_conversation_id} not found",
                error_code="not_found",
            )

        now = datetime.now()
        new_title = title or f"{source.title} (fork)"
        conversation = Conversation(
            conversation_id=generate_conversation_id(),
            project_id=source.project_id,
            title=new_title,
            created_at=now,
            updated_at=now,
            forked_from_conversation_id=source_conversation_id,
            forked_at_message_id=forked_at_message_id,
        )
        self.db.insert("conversations", conversation.to_db_dict())

        # 复制消息
        if message_repo is not None:
            messages = message_repo.list_by_conversation(source_conversation_id)
            if forked_at_message_id is not None:
                cutoff_message = next(
                    (msg for msg in messages if msg.message_id == forked_at_message_id),
                    None,
                )
                if cutoff_message is None:
                    raise ConversationRepositoryError(
                        f"Message {forked_at_message_id} not found in conversation {source_conversation_id}",
                        conversation_id=source_conversation_id,
                        error_code="not_found",
                    )
                messages = [
                    msg
                    for msg in messages
                    if msg.sequence_no <= cutoff_message.sequence_no
                ]

            turn_id_map: dict[str, str] = {}
            message_id_map: dict[str, str] = {}
            for msg in messages:
                new_message_id = generate_message_id()
                mapped_turn_id = None
                if msg.turn_id:
                    mapped_turn_id = turn_id_map.setdefault(
                        msg.turn_id, generate_turn_id()
                    )
                new_msg = ConversationMessage(
                    message_id=new_message_id,
                    conversation_id=conversation.conversation_id,
                    role=msg.role,
                    content=msg.content,
                    name=msg.name,
                    tool_calls=msg.tool_calls,
                    tool_call_id=msg.tool_call_id,
                    sequence_no=msg.sequence_no,
                    turn_id=mapped_turn_id,
                    parent_message_id=message_id_map.get(msg.parent_message_id or ""),
                    message_kind=msg.message_kind,
                    trace_ids=None,
                    reasoning_content=msg.reasoning_content,
                    tools=msg.tools,
                    created_at=now,
                )
                message_repo.create(new_msg)
                message_id_map[msg.message_id] = new_message_id

        logger.info(
            "event=conversation.forked new_id=%s source_id=%s",
            conversation.conversation_id,
            source_conversation_id,
        )
        return conversation

    def ensure_exists(self, conversation_id: str) -> None:
        """确保会话存在，不存在则抛出异常."""
        row = self.db.fetchone(
            "SELECT 1 FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        if row is None:
            raise ConversationRepositoryError(
                f"Conversation {conversation_id} not found",
                conversation_id=conversation_id,
                error_code="not_found",
            )


class ConversationMessageRepository:
    """ConversationMessage 数据访问层."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, message: ConversationMessage) -> None:
        """插入单条消息."""
        if message.sequence_no <= 0:
            message.sequence_no = self.get_next_sequence_no(message.conversation_id)
        self.db.insert("conversation_messages", message.to_db_dict())

    def get(self, message_id: str) -> ConversationMessage | None:
        """获取单条消息."""
        row = self.db.fetchone(
            "SELECT * FROM conversation_messages WHERE message_id = ?",
            (message_id,),
        )
        if not row:
            return None
        return ConversationMessage.from_db_row(row)

    def list_by_conversation(self, conversation_id: str) -> list[ConversationMessage]:
        """列出会话下的所有消息（按创建时间正序）."""
        rows = self.db.fetchall(
            """
            SELECT * FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY sequence_no ASC, created_at ASC, message_id ASC
            """,
            (conversation_id,),
        )
        return [ConversationMessage.from_db_row(row) for row in rows]

    def list_turns_by_conversation(
        self,
        conversation_id: str,
    ) -> list[ConversationTurnResponse]:
        """将会话消息按 turn 分组，供前端聊天视图消费."""
        messages = self.list_by_conversation(conversation_id)
        turns: "OrderedDict[str, ConversationTurnResponse]" = OrderedDict()

        for message in messages:
            turn_id = message.turn_id
            if message.message_kind == "system" or not turn_id:
                continue

            turn = turns.get(turn_id)
            if turn is None:
                turn = ConversationTurnResponse(
                    turn_id=turn_id,
                    user_message=None,
                    assistant_events=[],
                    trace_ids=[],
                )
                turns[turn_id] = turn

            if message.message_kind == "user_input":
                turn.user_message = self._to_message_response(message)
                continue

            turn.assistant_events.append(
                ConversationTurnEventResponse(
                    message_id=message.message_id,
                    role=cast(Literal["assistant", "tool"], message.role),
                    message_kind=message.message_kind,
                    content=message.content,
                    reasoning_content=message.reasoning_content,
                    name=message.name,
                    tool_calls=message.tool_calls,
                    tool_call_id=message.tool_call_id,
                    sequence_no=message.sequence_no,
                    parent_message_id=message.parent_message_id,
                    created_at=message.created_at,
                )
            )
            if message.trace_ids:
                turn.trace_ids = list(
                    dict.fromkeys([*turn.trace_ids, *message.trace_ids])
                )

        return list(turns.values())

    def update_content(self, message_id: str, content: str) -> None:
        """更新消息内容."""
        self.db.update(
            "conversation_messages",
            {"content": content},
            "message_id = ?",
            (message_id,),
        )

    def update_fields(self, message_id: str, data: dict[str, Any]) -> None:
        """更新消息的任意字段."""
        if not data:
            return
        payload = dict(data)
        for json_field in ("tool_calls", "trace_ids", "tools"):
            if json_field in payload and payload[json_field] is not None:
                import json

                payload[json_field] = json.dumps(
                    payload[json_field], ensure_ascii=False
                )
        self.db.update(
            "conversation_messages",
            payload,
            "message_id = ?",
            (message_id,),
        )

    def update_trace_ids(self, message_id: str, trace_ids: list[str]) -> None:
        """更新消息关联的 trace_ids."""
        import json

        self.db.update(
            "conversation_messages",
            {"trace_ids": json.dumps(trace_ids, ensure_ascii=False)},
            "message_id = ?",
            (message_id,),
        )

    def update_tools(self, message_id: str, tools: list[dict[str, Any]] | None) -> None:
        """更新消息关联的可用工具列表."""
        import json

        self.db.update(
            "conversation_messages",
            {
                "tools": (
                    json.dumps(tools, ensure_ascii=False) if tools is not None else None
                )
            },
            "message_id = ?",
            (message_id,),
        )

    def update_reasoning_content(self, message_id: str, reasoning_content: str) -> None:
        """更新思考过程内容."""
        self.db.update(
            "conversation_messages",
            {"reasoning_content": reasoning_content},
            "message_id = ?",
            (message_id,),
        )

    def update_tool_calls(
        self, message_id: str, tool_calls: list[dict[str, Any]]
    ) -> None:
        """更新消息的工具调用列表."""
        import json

        self.db.update(
            "conversation_messages",
            {"tool_calls": json.dumps(tool_calls, ensure_ascii=False)},
            "message_id = ?",
            (message_id,),
        )

    def delete(self, message_id: str) -> None:
        """删除单条消息."""
        self.db.delete("conversation_messages", "message_id = ?", (message_id,))

    def delete_after(self, conversation_id: str, message_id: str) -> int:
        """删除某条消息之后的所有消息（用于编辑后截断）.

        Returns:
            int: 删除的消息数量
        """
        row = self.db.fetchone(
            """
            SELECT sequence_no FROM conversation_messages
            WHERE message_id = ? AND conversation_id = ?
            """,
            (message_id, conversation_id),
        )
        if row is None:
            return 0

        cutoff = row["sequence_no"]
        deleted = self.db.delete(
            "conversation_messages",
            "conversation_id = ? AND sequence_no > ?",
            (conversation_id, cutoff),
        )
        logger.info(
            "event=conversation.messages_truncated conversation_id=%s after_message=%s deleted=%s",
            conversation_id,
            message_id,
            deleted,
        )
        return deleted

    def delete_turn(self, conversation_id: str, turn_id: str) -> int:
        """删除单个 turn 内的所有消息，并修复后继消息的 parent_message_id。"""
        rows = self.db.fetchall(
            """
            SELECT message_id, sequence_no
            FROM conversation_messages
            WHERE conversation_id = ? AND turn_id = ?
            ORDER BY sequence_no ASC, created_at ASC, message_id ASC
            """,
            (conversation_id, turn_id),
        )
        if not rows:
            return 0

        first_sequence = int(rows[0]["sequence_no"])
        last_sequence = int(rows[-1]["sequence_no"])

        previous_row = self.db.fetchone(
            """
            SELECT message_id
            FROM conversation_messages
            WHERE conversation_id = ? AND sequence_no < ?
            ORDER BY sequence_no DESC, created_at DESC, message_id DESC
            LIMIT 1
            """,
            (conversation_id, first_sequence),
        )
        next_row = self.db.fetchone(
            """
            SELECT message_id
            FROM conversation_messages
            WHERE conversation_id = ? AND sequence_no > ?
            ORDER BY sequence_no ASC, created_at ASC, message_id ASC
            LIMIT 1
            """,
            (conversation_id, last_sequence),
        )

        deleted = self.db.delete(
            "conversation_messages",
            "conversation_id = ? AND turn_id = ?",
            (conversation_id, turn_id),
        )

        if next_row is not None:
            self.db.update(
                "conversation_messages",
                {
                    "parent_message_id": (
                        previous_row["message_id"] if previous_row else None
                    )
                },
                "message_id = ?",
                (next_row["message_id"],),
            )

        logger.info(
            "event=conversation.turn_deleted conversation_id=%s turn_id=%s deleted=%s",
            conversation_id,
            turn_id,
            deleted,
        )
        return deleted

    def delete_all_by_conversation(self, conversation_id: str) -> int:
        """删除会话的所有消息.

        Returns:
            int: 删除的消息数量
        """
        return self.db.delete(
            "conversation_messages",
            "conversation_id = ?",
            (conversation_id,),
        )

    def get_next_sequence_no(self, conversation_id: str) -> int:
        """获取会话的下一个 sequence_no."""
        row = self.db.fetchone(
            """
            SELECT COALESCE(MAX(sequence_no), 0) AS max_sequence
            FROM conversation_messages
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        )
        return int(row["max_sequence"]) + 1 if row is not None else 1

    def create_with_next_sequence(
        self,
        message: ConversationMessage,
    ) -> ConversationMessage:
        """插入消息并自动分配顺序号."""
        self.create(message)
        return message

    @staticmethod
    def _to_message_response(message: ConversationMessage):
        from paper_plane_x_backend.schemas.api.conversation import (
            ConversationMessageResponse,
        )

        return ConversationMessageResponse(
            message_id=message.message_id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            name=message.name,
            tool_calls=message.tool_calls,
            tool_call_id=message.tool_call_id,
            sequence_no=message.sequence_no,
            turn_id=message.turn_id,
            parent_message_id=message.parent_message_id,
            message_kind=message.message_kind,
            trace_ids=message.trace_ids,
            reasoning_content=message.reasoning_content,
            created_at=message.created_at,
        )
