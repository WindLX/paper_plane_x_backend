import json
import logging

from pydantic import BaseModel

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.core.agent_runtime import BaseAgent
from paper_plane_x_backend.models.app_settings import LLMConfig
from paper_plane_x_backend.schemas.agent_io.librarian import (
    DeepDiverAgentInput,
    DeepDiverAgentOutput,
)
from paper_plane_x_backend.services.app_settings import resolve_agent_llm_config

logger = logging.getLogger(__name__)


class DeepDiverAgent:
    """Deep Diver Agent"""

    agent_name: str = "DeepDiverAgent"
    llm_config_name: str = "deep_diver"
    prompt_filename: str = "DeepDiverAgent.md"

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        caller: str | None = None,
        caller_id: str | None = None,
    ) -> None:
        self.llm_config = llm_config or resolve_agent_llm_config(self.llm_config_name)

        self._agent = BaseAgent(
            output_schema=DeepDiverAgentOutput,
            mode="api",
            system_prompt=self._build_system_prompt(),
            max_steps=3,
            save_trace=True,
            llm_config=self.llm_config,
            agent_name=self.agent_name,
            caller=caller,
            caller_id=caller_id,
        )

    def _build_system_prompt(self) -> str:
        system_md = settings.load_prompt("deep_diver", "System.md")
        system_md = self._inject_schema_template(
            prompt_template=system_md,
            schema_model=DeepDiverAgentOutput,
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

    def append_user_message(self, payload: DeepDiverAgentInput) -> None:
        self._agent.memory.append_user_message(payload.model_dump())

    async def run(self) -> DeepDiverAgentOutput:
        result = await self._agent.run()
        assert isinstance(result, DeepDiverAgentOutput), (
            f"Expected output of type {DeepDiverAgentOutput.__name__}, "
            f"but got {type(result).__name__}"
        )
        return result
