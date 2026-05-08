"""SubAgent 工具 — 供 ResearcherAgent 委派子任务使用.

`delegate_to_subagent` 工具本身定义在此，但 SubAgent 实现位于 agents/subagent.py。
SubAgent 不能调用其他 subagent（防止递归）。
"""

import logging
from typing import Any

from paper_plane_x_backend.agents.subagent import SubAgent
from paper_plane_x_backend.core.agent_runtime.tooling import tool

logger = logging.getLogger(__name__)


@tool(
    name="delegate_to_subagent",
    description=(
        "委派一个子 Agent 执行独立的研究/撰写任务。"
        "\n适用场景："
        "\n- 撰写综述时，指派子 Agent 分析若干篇论文并产出该部分段落。"
        "\n- 将复杂大任务拆分为若干子任务并行或串行执行。"
        "\n- 需要深入研究某几篇论文的特定主题时，委派子 Agent 完成。"
        "\n"
        "\n输入："
        "\n- task（必填）：明确、具体的任务描述，越详细越好。"
        "\n- context（可选）：额外上下文，如 paper_id 列表、已有草稿片段、需要遵循的格式要求等。"
        "\n"
        "\n输出：子 Agent 完成任务后返回的文本内容（通常是研究报告、综述段落或分析结果）。"
        "\n"
        "\n注意：子 Agent 没有调用 subagent 的能力，因此不会引发递归。"
    ),
    context_params={
        "project_id": "project_id",
        "caller": "_caller_agent_name",
        "caller_id": "_caller_trace_id",
    },
)
async def delegate_to_subagent(
    task: str,
    context: str | None = None,
    *,
    project_id: str,
    caller: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    """创建 SubAgent 并执行委派任务."""
    logger.info(
        "event=subagent.delegate_started project_id=%s task_preview=%s",
        project_id,
        task[:80],
    )

    sub = SubAgent(
        project_id=project_id,
        task=task,
        context=context,
        caller=caller,
        caller_id=caller_id,
    )
    try:
        result = await sub.run()
    except Exception as exc:
        logger.exception("event=subagent.delegate_failed project_id=%s", project_id)
        return {
            "status": "error",
            "task": task,
            "error": str(exc),
        }

    logger.info(
        "event=subagent.delegate_completed project_id=%s result_length=%s",
        project_id,
        len(result),
    )
    return {
        "status": "success",
        "task": task,
        "result": result,
    }
