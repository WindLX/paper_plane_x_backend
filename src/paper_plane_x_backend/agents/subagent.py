"""SubAgent — 被 ResearcherAgent 委派的子研究助手.

SubAgent 不能调用其他 subagent（防止递归）。
专注于完成被委派的单一任务，例如分析若干篇论文并撰写综述段落。
"""

import logging

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.core.agent_runtime import BaseAgent
from paper_plane_x_backend.models.app_settings import LLMConfig
from paper_plane_x_backend.services.app_settings import resolve_agent_llm_config
from paper_plane_x_backend.tools.conversation_io import (
    find_in_project_file,
    list_project_files,
    patch_project_file,
    read_project_file,
    read_project_file_lines,
    remove_project_file,
    replace_project_file_lines,
    replace_project_file_text,
    write_project_file,
)
from paper_plane_x_backend.tools.librarian import (
    deep_dive_tool,
    global_finder,
    matrix_compare,
    search_paper,
)
from paper_plane_x_backend.tools.paper import (
    delete_paper_agent_note,
    get_paper_agent_note,
    update_paper_agent_note,
    write_paper_agent_note,
)

logger = logging.getLogger(__name__)

_SUBAGENT_TOOLS = [
    read_project_file,
    read_project_file_lines,
    find_in_project_file,
    write_project_file,
    replace_project_file_lines,
    replace_project_file_text,
    patch_project_file,
    list_project_files,
    remove_project_file,
    global_finder,
    matrix_compare,
    search_paper,
    deep_dive_tool,
    get_paper_agent_note,
    write_paper_agent_note,
    update_paper_agent_note,
    delete_paper_agent_note,
]


class SubAgent:
    """子 Agent — 不能调用 subagent（无递归）.

    由 ResearcherAgent 通过 `delegate_to_subagent` 工具委派任务后创建并执行。
    """

    agent_name: str = "SubAgent"
    llm_config_name: str = "subagent"
    prompt_filename: str = "System.md"

    def __init__(
        self,
        project_id: str,
        task: str,
        context: str | None = None,
        llm_config: LLMConfig | None = None,
        max_steps: int = 15,
        caller: str | None = None,
        caller_id: str | None = None,
    ) -> None:
        self.project_id = project_id
        self.task = task
        self.context = context
        self.llm_config = llm_config or resolve_agent_llm_config(self.llm_config_name)

        self._agent = BaseAgent(
            mode="normal",
            system_prompt=self._build_system_prompt(),
            tools=list(_SUBAGENT_TOOLS),
            max_steps=max_steps,
            save_trace=True,
            llm_config=self.llm_config,
            agent_name=self.agent_name,
            tool_context={"project_id": project_id},
            caller=caller,
            caller_id=caller_id,
        )

        # 将任务注入 memory
        user_input = self._build_user_input()
        self._agent.memory.append_user_message({"content": user_input})

    def _build_system_prompt(self) -> str:
        return settings.load_prompt("subagent", self.prompt_filename)

    def _build_user_input(self) -> str:
        parts: list[str] = [f"任务：{self.task}"]
        if self.context:
            parts.append(f"上下文/参考资料：\n{self.context}")
        return "\n\n".join(parts)

    async def run(self) -> str:
        """执行子任务并返回结果文本."""
        result = await self._agent.run()
        return str(result)
