"""HITL (Human-in-the-loop) 工具集合.

提供 Agent 向人类提问的能力，用于在关键决策点获取人类确认或建议。
"""

import asyncio
import logging
from typing import Any

from paper_plane_x_backend.core.agent_runtime.tooling import tool
from paper_plane_x_backend.services.hitl import get_hitl_manager
from paper_plane_x_backend.services.hitl.manager import HITLOption, HITLQuestion

logger = logging.getLogger(__name__)


@tool(
    name="ask_human",
    description=(
        "向人类用户提问以获取建议、确认或决策。"
        "\n适用场景："
        "\n- 需要人类确认某个关键决策（如方向选择、方法选择）。"
        "\n- 需要人类提供额外信息以继续任务。"
        "\n- 需要人类对多个选项进行评价或排序。"
        "\n- 当 AI 不确定如何继续时寻求人类指导。"
        "\n"
        "\n输入："
        "\n- questions（必填）：问题列表，每个问题包含："
        "\n  - text: 问题文本"
        "\n  - options: 选项列表，每个选项包含 id 和 text"
        "\n  - allow_multiple: 是否允许多选（默认 false）"
        "\n"
        "\n每个问题固定会有一个「自定义回答」选项，用户可自由输入文本。"
        "\n"
        "\n输出：人类回答列表，每项包含："
        "\n  - question_index: 问题索引"
        "\n  - selected_option_ids: 用户选择的选项 ID 列表"
        "\n  - custom_text: 用户自定义回答文本（如果选择了自定义选项）"
        "\n"
        "\n注意：此工具会阻塞等待人类回答，请确保问题表述清晰，不要同时发起多个 ask_human。"
    ),
)
async def ask_human(
    questions: list[dict[str, Any]],
    *,
    project_id: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """向人类提问并等待回答."""
    manager = get_hitl_manager()

    # 解析问题
    hitl_questions: list[HITLQuestion] = []
    for idx, q in enumerate(questions):
        options = [
            HITLOption(id=opt["id"], text=opt["text"]) for opt in q.get("options", [])
        ]
        hitl_questions.append(
            HITLQuestion(
                text=q.get("text", f"问题 {idx + 1}"),
                options=options,
                allow_multiple=q.get("allow_multiple", False),
                custom_answer_label=q.get(
                    "custom_answer_label", "其他（请自定义回答）"
                ),
            )
        )

    # 注册问题
    record = manager.register_question(
        questions=hitl_questions,
        project_id=project_id,
        conversation_id=conversation_id,
    )

    # 广播到 HITL WebSocket 客户端
    await manager.broadcast_question(record)

    logger.info(
        "event=hitl.ask_human_waiting question_id=%s project_id=%s conversation_id=%s question_count=%s",
        record.question_id,
        project_id,
        conversation_id,
        len(hitl_questions),
    )

    # 阻塞等待人类回答（带超时保护）
    try:
        await asyncio.wait_for(record.event.wait(), timeout=600.0)
    except asyncio.TimeoutError:
        manager.remove_question(record.question_id)
        logger.warning(
            "event=hitl.ask_human_timeout question_id=%s project_id=%s",
            record.question_id,
            project_id,
        )
        return {
            "status": "timeout",
            "question_id": record.question_id,
            "error": "人类未在 10 分钟内回答，任务已超时。",
        }

    # 获取回答
    answers = record.answers
    manager.remove_question(record.question_id)

    logger.info(
        "event=hitl.ask_human_completed question_id=%s project_id=%s answer_count=%s",
        record.question_id,
        project_id,
        len(answers),
    )

    return {
        "status": "success",
        "question_id": record.question_id,
        "answers": answers,
    }
