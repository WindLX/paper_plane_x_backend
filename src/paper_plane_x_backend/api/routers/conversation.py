"""Conversation REST API 路由."""

import logging
from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query, status

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.models.conversation import Conversation, ConversationMessage
from paper_plane_x_backend.schemas.api.conversation import (
    ConversationCreateRequest,
    ConversationForkRequest,
    ConversationListResponse,
    ConversationMessageCreateRequest,
    ConversationMessageResponse,
    ConversationMessageUpdateRequest,
    ConversationResponse,
    ConversationTurnResponse,
    ConversationUpdateRequest,
)
from paper_plane_x_backend.services.conversation.repository import (
    ConversationMessageRepository,
    ConversationRepository,
    ConversationRepositoryError,
)
from paper_plane_x_backend.services.project.repository import ProjectRepository
from paper_plane_x_backend.utils.ids import generate_message_id

router = APIRouter(prefix="/conversations", tags=["conversations"])
logger = logging.getLogger(__name__)


def _raise_as_http(exc: ConversationRepositoryError) -> NoReturn:
    logger.warning(
        "event=conversation.domain_error error_code=%s message=%s",
        exc.error_code,
        exc.message,
    )
    status_map = {
        "not_found": status.HTTP_404_NOT_FOUND,
        "bad_request": status.HTTP_400_BAD_REQUEST,
    }
    http_status = status_map.get(exc.error_code, status.HTTP_400_BAD_REQUEST)
    raise HTTPException(status_code=http_status, detail=exc.message)


def _log_project_operation(
    db: DBDep,
    project_id: str,
    operation: str,
    detail: dict[str, object] | None = None,
) -> None:
    """记录项目操作日志."""
    try:
        ProjectRepository(db).update_operation_logs(
            project_id=project_id,
            operation=operation,
            detail=detail or {},
        )
    except Exception:
        logger.warning(
            "event=conversation.project_log_failed project_id=%s operation=%s",
            project_id,
            operation,
            exc_info=True,
        )


def _conversation_to_response(
    conversation: Conversation,
) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=conversation.conversation_id,
        project_id=conversation.project_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        forked_from_conversation_id=conversation.forked_from_conversation_id,
        forked_at_message_id=conversation.forked_at_message_id,
    )


def _message_to_response(
    message: ConversationMessage,
) -> ConversationMessageResponse:
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
        images=message.images,
        created_at=message.created_at,
    )


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建会话",
)
def create_conversation(
    request: ConversationCreateRequest,
    db: DBDep,
) -> ConversationResponse:
    """创建新会话.

    Args:
        request: 创建请求
        db: 数据库实例

    Returns:
        ConversationResponse: 创建的会话
    """
    logger.info(
        "event=conversation.create_request_received project_id=%s",
        request.project_id,
    )
    repo = ConversationRepository(db)
    conversation = repo.create(
        project_id=request.project_id,
        title=request.title or "New Conversation",
    )
    _log_project_operation(
        db,
        project_id=request.project_id,
        operation="create_conversation",
        detail={
            "conversation_id": conversation.conversation_id,
            "title": conversation.title,
        },
    )
    return _conversation_to_response(conversation)


@router.get(
    "",
    response_model=ConversationListResponse,
    summary="列出会话",
)
def list_conversations(
    db: DBDep,
    project_id: str = Query(..., description="项目 ID"),
) -> ConversationListResponse:
    """获取项目下的会话列表.

    Args:
        db: 数据库实例
        project_id: 项目 ID

    Returns:
        ConversationListResponse: 会话列表
    """
    logger.debug(
        "event=conversation.list_request_received project_id=%s",
        project_id,
    )
    repo = ConversationRepository(db)
    conversations = repo.list_by_project(project_id)
    return ConversationListResponse(
        items=[_conversation_to_response(c) for c in conversations],
        total=len(conversations),
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="获取会话详情",
)
def get_conversation(
    conversation_id: str,
    db: DBDep,
) -> ConversationResponse:
    """获取会话详情.

    Args:
        conversation_id: 会话 ID
        db: 数据库实例

    Returns:
        ConversationResponse: 会话详情
    """
    logger.debug(
        "event=conversation.get_request_received conversation_id=%s",
        conversation_id,
    )
    repo = ConversationRepository(db)
    conversation = repo.get(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found",
        )
    return _conversation_to_response(conversation)


@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="更新会话标题",
)
def update_conversation(
    conversation_id: str,
    request: ConversationUpdateRequest,
    db: DBDep,
) -> ConversationResponse:
    """更新会话标题.

    Args:
        conversation_id: 会话 ID
        request: 更新请求
        db: 数据库实例

    Returns:
        ConversationResponse: 更新后的会话
    """
    logger.info(
        "event=conversation.update_request_received conversation_id=%s title=%s",
        conversation_id,
        request.title,
    )
    repo = ConversationRepository(db)
    conversation = repo.get(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found",
        )
    repo.update_title(conversation_id, request.title)
    conversation.title = request.title
    _log_project_operation(
        db,
        project_id=conversation.project_id,
        operation="update_conversation",
        detail={"conversation_id": conversation_id, "title": request.title},
    )
    return _conversation_to_response(conversation)


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除会话",
)
def delete_conversation(
    conversation_id: str,
    db: DBDep,
) -> None:
    """删除会话（级联删除消息）.

    Args:
        conversation_id: 会话 ID
        db: 数据库实例
    """
    logger.info(
        "event=conversation.delete_request_received conversation_id=%s",
        conversation_id,
    )
    repo = ConversationRepository(db)
    conversation = repo.get(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found",
        )
    project_id = conversation.project_id
    repo.delete(conversation_id)
    _log_project_operation(
        db,
        project_id=project_id,
        operation="delete_conversation",
        detail={"conversation_id": conversation_id, "title": conversation.title},
    )


@router.post(
    "/{conversation_id}/fork",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Fork 会话",
)
def fork_conversation(
    conversation_id: str,
    request: ConversationForkRequest,
    db: DBDep,
) -> ConversationResponse:
    """Fork 复制会话.

    Args:
        conversation_id: 来源会话 ID
        request: Fork 请求
        db: 数据库实例

    Returns:
        ConversationResponse: 新创建的会话
    """
    logger.info(
        "event=conversation.fork_request_received conversation_id=%s",
        conversation_id,
    )
    repo = ConversationRepository(db)
    msg_repo = ConversationMessageRepository(db)
    source = repo.get(conversation_id)
    try:
        conversation = repo.fork(
            source_conversation_id=conversation_id,
            title=request.title,
            forked_at_message_id=request.forked_at_message_id,
            message_repo=msg_repo,
        )
    except ConversationRepositoryError as exc:
        _raise_as_http(exc)
    if source is not None:
        _log_project_operation(
            db,
            project_id=source.project_id,
            operation="fork_conversation",
            detail={
                "source_conversation_id": conversation_id,
                "new_conversation_id": conversation.conversation_id,
                "title": conversation.title,
            },
        )
    return _conversation_to_response(conversation)


@router.get(
    "/{conversation_id}/messages",
    response_model=list[ConversationMessageResponse],
    summary="获取会话消息",
)
def list_messages(
    conversation_id: str,
    db: DBDep,
) -> list[ConversationMessageResponse]:
    """获取会话的所有消息.

    Args:
        conversation_id: 会话 ID
        db: 数据库实例

    Returns:
        list[ConversationMessageResponse]: 消息列表
    """
    logger.debug(
        "event=conversation.messages_list_request_received conversation_id=%s",
        conversation_id,
    )
    repo = ConversationMessageRepository(db)
    messages = repo.list_by_conversation(conversation_id)
    return [_message_to_response(m) for m in messages]


@router.get(
    "/{conversation_id}/turns",
    response_model=list[ConversationTurnResponse],
    summary="获取按轮次聚合的会话消息",
)
def list_turns(
    conversation_id: str,
    db: DBDep,
) -> list[ConversationTurnResponse]:
    """获取会话的 turn 视图."""
    logger.debug(
        "event=conversation.turns_list_request_received conversation_id=%s",
        conversation_id,
    )
    repo = ConversationMessageRepository(db)
    return repo.list_turns_by_conversation(conversation_id)


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="添加消息",
)
def create_message(
    conversation_id: str,
    request: ConversationMessageCreateRequest,
    db: DBDep,
) -> ConversationMessageResponse:
    """向会话添加消息（用于 system 注入等场景）.

    Args:
        conversation_id: 会话 ID
        request: 消息内容
        db: 数据库实例

    Returns:
        ConversationMessageResponse: 创建的消息
    """
    logger.info(
        "event=conversation.message_create_request_received conversation_id=%s role=%s",
        conversation_id,
        request.role,
    )
    repo = ConversationMessageRepository(db)
    convo_repo = ConversationRepository(db)
    conversation = convo_repo.get(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found",
        )

    message = ConversationMessage(
        message_id=generate_message_id(),
        conversation_id=conversation_id,
        role=request.role,
        content=request.content,
        name=request.name,
        sequence_no=repo.get_next_sequence_no(conversation_id),
        images=request.images,
        message_kind=(
            "system"
            if request.role == "system"
            else (
                "user_input"
                if request.role == "user"
                else "tool_result" if request.role == "tool" else "assistant_final"
            )
        ),
    )
    repo.create(message)
    convo_repo.touch(conversation_id)
    _log_project_operation(
        db,
        project_id=conversation.project_id,
        operation="create_conversation_message",
        detail={
            "conversation_id": conversation_id,
            "message_id": message.message_id,
            "role": request.role,
        },
    )
    return _message_to_response(message)


@router.patch(
    "/{conversation_id}/messages/{message_id}",
    response_model=ConversationMessageResponse,
    summary="更新消息内容",
)
def update_message(
    conversation_id: str,
    message_id: str,
    request: ConversationMessageUpdateRequest,
    db: DBDep,
) -> ConversationMessageResponse:
    """更新消息内容（用于编辑）.

    编辑后会删除该消息之后的所有消息。

    Args:
        conversation_id: 会话 ID
        message_id: 消息 ID
        request: 更新请求
        db: 数据库实例

    Returns:
        ConversationMessageResponse: 更新后的消息
    """
    logger.info(
        "event=conversation.message_update_request_received conversation_id=%s message_id=%s",
        conversation_id,
        message_id,
    )
    repo = ConversationMessageRepository(db)
    convo_repo = ConversationRepository(db)

    message = repo.get(message_id)
    if message is None or message.conversation_id != conversation_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Message {message_id} not found in conversation {conversation_id}",
        )

    update_payload: dict[str, object] = {"content": request.content}
    if request.images is not None:
        update_payload["images"] = request.images
    repo.update_fields(message_id, update_payload)
    repo.delete_after(conversation_id, message_id)
    convo_repo.touch(conversation_id)

    conversation = convo_repo.get(conversation_id)
    if conversation is not None:
        _log_project_operation(
            db,
            project_id=conversation.project_id,
            operation="update_conversation_message",
            detail={"conversation_id": conversation_id, "message_id": message_id},
        )

    message.content = request.content
    if request.images is not None:
        message.images = request.images
    return _message_to_response(message)


@router.delete(
    "/{conversation_id}/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除消息",
)
def delete_message(
    conversation_id: str,
    message_id: str,
    db: DBDep,
) -> None:
    """删除单条消息.

    Args:
        conversation_id: 会话 ID
        message_id: 消息 ID
        db: 数据库实例
    """
    logger.info(
        "event=conversation.message_delete_request_received conversation_id=%s message_id=%s",
        conversation_id,
        message_id,
    )
    repo = ConversationMessageRepository(db)
    convo_repo = ConversationRepository(db)
    message = repo.get(message_id)
    if message is None or message.conversation_id != conversation_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Message {message_id} not found in conversation {conversation_id}",
        )
    repo.delete(message_id)
    conversation = convo_repo.get(conversation_id)
    if conversation is not None:
        _log_project_operation(
            db,
            project_id=conversation.project_id,
            operation="delete_conversation_message",
            detail={"conversation_id": conversation_id, "message_id": message_id},
        )


@router.delete(
    "/{conversation_id}/turns/{turn_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除对话轮次",
)
def delete_turn(
    conversation_id: str,
    turn_id: str,
    db: DBDep,
) -> None:
    """删除单个 turn 内的所有消息。"""
    logger.info(
        "event=conversation.turn_delete_request_received conversation_id=%s turn_id=%s",
        conversation_id,
        turn_id,
    )
    repo = ConversationMessageRepository(db)
    convo_repo = ConversationRepository(db)
    deleted = repo.delete_turn(conversation_id, turn_id)
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Turn {turn_id} not found in conversation {conversation_id}",
        )

    convo_repo.touch(conversation_id)
    conversation = convo_repo.get(conversation_id)
    if conversation is not None:
        _log_project_operation(
            db,
            project_id=conversation.project_id,
            operation="delete_conversation_turn",
            detail={"conversation_id": conversation_id, "turn_id": turn_id},
        )
