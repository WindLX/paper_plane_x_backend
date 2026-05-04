"""HITL 状态管理器.

管理待处理的人类交互问题，支持跨 WebSocket 连接的状态持久。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, cast

from paper_plane_x_backend.utils.ids import generate_hitl_question_id

logger = logging.getLogger(__name__)


@dataclass
class HITLOption:
    """HITL 问题选项."""

    id: str
    text: str


@dataclass
class HITLQuestion:
    """HITL 单条问题."""

    text: str
    options: list[HITLOption]
    allow_multiple: bool = False
    custom_answer_label: str = "其他（请自定义回答）"


@dataclass
class PendingQuestion:
    """待人类回答的问题记录."""

    question_id: str
    questions: list[HITLQuestion]
    project_id: str | None
    conversation_id: str | None
    event: asyncio.Event = field(default_factory=asyncio.Event)
    answers: list[dict[str, Any]] = field(
        default_factory=lambda: cast(list[dict[str, Any]], [])
    )
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 的结构（不含 Event）."""
        return {
            "question_id": self.question_id,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "questions": [
                {
                    "text": q.text,
                    "options": [{"id": o.id, "text": o.text} for o in q.options],
                    "allow_multiple": q.allow_multiple,
                    "custom_answer_label": q.custom_answer_label,
                }
                for q in self.questions
            ],
            "created_at": self.created_at,
        }


class HITLManager:
    """HITL 全局状态管理器.

    单例模式，管理所有 pending 的人类交互问题。
    """

    _instance: "HITLManager | None" = None
    _lock: asyncio.Lock = asyncio.Lock()

    _pending: dict[str, PendingQuestion]
    _ws_connections: set[Any]

    def __new__(cls) -> "HITLManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._pending = {}
            cls._instance._ws_connections = set()
        return cls._instance

    def register_question(
        self,
        questions: list[HITLQuestion],
        *,
        project_id: str | None = None,
        conversation_id: str | None = None,
    ) -> PendingQuestion:
        """注册一个新的待回答问题.

        Returns:
            PendingQuestion: 包含 question_id 和用于等待回答的 asyncio.Event。
        """
        question_id = generate_hitl_question_id()
        record = PendingQuestion(
            question_id=question_id,
            questions=questions,
            project_id=project_id,
            conversation_id=conversation_id,
        )
        self._pending[question_id] = record
        logger.info(
            "event=hitl.question_registered question_id=%s project_id=%s conversation_id=%s",
            question_id,
            project_id,
            conversation_id,
        )
        return record

    def answer_question(
        self,
        question_id: str,
        answers: list[dict[str, Any]],
    ) -> bool:
        """提交人类回答.

        Returns:
            bool: 是否成功匹配到 pending question 并设置回答。
        """
        record = self._pending.get(question_id)
        if record is None:
            logger.warning(
                "event=hitl.answer_rejected question_id=%s reason=not_found",
                question_id,
            )
            return False

        record.answers = answers
        record.event.set()
        logger.info(
            "event=hitl.question_answered question_id=%s project_id=%s",
            question_id,
            record.project_id,
        )
        return True

    def get_pending(self, question_id: str) -> PendingQuestion | None:
        """获取指定 pending question."""
        return self._pending.get(question_id)

    def list_pending(self) -> list[PendingQuestion]:
        """列出所有待回答问题."""
        return list(self._pending.values())

    def remove_question(self, question_id: str) -> bool:
        """移除已完成的 question（通常由 ask_human 工具在获取回答后调用）."""
        if question_id in self._pending:
            del self._pending[question_id]
            logger.info(
                "event=hitl.question_removed question_id=%s",
                question_id,
            )
            return True
        return False

    def register_ws(self, websocket: Any) -> None:
        """注册 WebSocket 连接."""
        self._ws_connections.add(websocket)
        logger.debug(
            "event=hitl.ws_registered total=%s",
            len(self._ws_connections),
        )

    def unregister_ws(self, websocket: Any) -> None:
        """注销 WebSocket 连接."""
        self._ws_connections.discard(websocket)
        logger.debug(
            "event=hitl.ws_unregistered total=%s",
            len(self._ws_connections),
        )

    async def broadcast_question(self, record: PendingQuestion) -> None:
        """向所有 HITL WebSocket 客户端广播新问题."""
        dead: list[Any] = []
        for ws in self._ws_connections:
            try:
                await ws.send_json(
                    {
                        "type": "hitl_question",
                        **record.to_dict(),
                    }
                )
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ws_connections.discard(ws)


# 全局单例
_hitl_manager: HITLManager | None = None


def get_hitl_manager() -> HITLManager:
    global _hitl_manager
    if _hitl_manager is None:
        _hitl_manager = HITLManager()
    return _hitl_manager
