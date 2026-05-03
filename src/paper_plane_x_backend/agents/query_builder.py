"""Query Builder Agent.

将用户自然语言查询转换为 Librarian DSL 条件表达式。
"""

import json
import logging

from pydantic import BaseModel

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.core.agent_runtime import BaseAgent
from paper_plane_x_backend.models.app_settings import LLMConfig
from paper_plane_x_backend.schemas.agent_io.librarian import (
    QueryBuilderAgentInput,
    QueryBuilderAgentOutput,
)
from paper_plane_x_backend.services.app_settings import resolve_agent_llm_config

logger = logging.getLogger(__name__)


class QueryBuilderAgent:
    """QueryBuilder Agent.

    帮助用户将自然语言查询需求转换为 Librarian 统一搜索 API
    所需的 DSL 条件表达式（query_expr）。
    """

    agent_name: str = "QueryBuilderAgent"
    llm_config_name: str = "query_builder"
    prompt_filename: str = "System.md"

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self.llm_config = llm_config or resolve_agent_llm_config(self.llm_config_name)

        self._agent = BaseAgent(
            output_schema=QueryBuilderAgentOutput,
            mode="api",
            system_prompt=self._build_system_prompt(),
            max_steps=1,
            save_trace=True,
            llm_config=self.llm_config,
            agent_name=self.agent_name,
            caller="api",
            caller_id=None,
        )

    def _build_system_prompt(self) -> str:
        system_md = settings.load_prompt("query_builder", self.prompt_filename)
        system_md = self._inject_schema_template(
            prompt_template=system_md,
            schema_model=QueryBuilderAgentOutput,
        )
        return system_md

    @staticmethod
    def _inject_schema_template(
        prompt_template: str,
        schema_model: type[BaseModel],
    ) -> str:
        """将 Pydantic 导出的完整 JSON Schema 注入提示词模板。"""
        schema_json = json.dumps(
            schema_model.model_json_schema(),
            ensure_ascii=False,
            indent=2,
        )
        return prompt_template.replace("{{OUTPUT_SCHEMA_JSON}}", schema_json)

    @property
    def runtime_name(self) -> str:
        return self._agent.agent_name

    @property
    def trace_ids(self) -> list[str]:
        return list(self._agent.trace_ids)

    def reset_memory(self) -> None:
        self._agent.memory.reset_memory()

    def append_user_message(self, payload: QueryBuilderAgentInput) -> None:
        self._agent.memory.append_user_message(payload.model_dump())

    async def run(self) -> QueryBuilderAgentOutput:
        result = await self._agent.run()
        assert isinstance(result, QueryBuilderAgentOutput), (
            f"Expected output of type {QueryBuilderAgentOutput.__name__}, "
            f"but got {type(result).__name__}"
        )
        return result
