"""DataProcessorAgentGroup behavior tests."""

import json
from typing import Any

import pytest

from paper_plane_x_backend.agents.data_processor import (
    AnalysisAgent,
    DataProcessorAgentGroup,
    ExtractionAgent,
    FactCheckAgent,
)
from paper_plane_x_backend.models.app_settings import LLMConfig


def _llm_config(*, is_vlm: bool = False) -> LLMConfig:
    return LLMConfig(model="test-model", api_key="test-key", is_vlm=is_vlm)


def test_agents_share_system_and_document_prefix_before_task_contract() -> None:
    agents = [
        ExtractionAgent(llm_config=_llm_config()),
        AnalysisAgent(llm_config=_llm_config()),
        FactCheckAgent(llm_config=_llm_config()),
    ]

    for agent in agents:
        agent.append_user_message(
            agent.build_user_message(md_content="# Shared paper", images=[])
        )
        agent.append_task_message()

    messages_by_agent = [agent._agent.memory.get_messages() for agent in agents]
    common_prefix = [messages[:2] for messages in messages_by_agent]
    assert common_prefix[0] == common_prefix[1] == common_prefix[2]

    system_message, paper_message = common_prefix[0]
    assert system_message["role"] == "system"
    assert "不可信数据" in system_message["content"]
    assert paper_message["role"] == "user"
    assert json.loads(paper_message["content"]) == {"md_content": "# Shared paper"}

    task_messages = [messages[2] for messages in messages_by_agent]
    assert all(message["role"] == "user" for message in task_messages)
    assert "quick_scan" in task_messages[0]["content"]
    assert "analysis_report" in task_messages[1]["content"]
    assert "is_passed" in task_messages[2]["content"]
    assert len({message["content"] for message in task_messages}) == 3


def test_vlm_agents_share_stable_paper_and_image_prefix() -> None:
    extraction = ExtractionAgent(llm_config=_llm_config(is_vlm=True))
    fact_check = FactCheckAgent(llm_config=_llm_config(is_vlm=True))
    images = ["data:image/png;base64,first", "data:image/png;base64,second"]

    for agent in (extraction, fact_check):
        agent.append_user_message(
            agent.build_user_message(md_content="# Shared paper", images=images)
        )
        agent.append_task_message()

    extraction_messages = extraction._agent.memory.get_messages()
    fact_check_messages = fact_check._agent.memory.get_messages()
    assert extraction_messages[:2] == fact_check_messages[:2]
    assert extraction_messages[1]["content"] == [
        {"type": "text", "text": '{"md_content": "# Shared paper"}'},
        {"type": "image_url", "image_url": {"url": images[0]}},
        {"type": "image_url", "image_url": {"url": images[1]}},
    ]


def test_fact_check_report_and_retry_feedback_follow_task_contract() -> None:
    agent = FactCheckAgent(llm_config=_llm_config())
    agent.append_user_message(
        agent.build_user_message(md_content="# Shared paper", images=[])
    )
    agent.append_task_message()
    agent.append_assistant_message(
        {"extraction_result": {"quick_scan": {"title": "Example"}}},
        name="ExtractionAgent",
    )
    agent._agent.memory.append_validation_feedback("missing errors")

    messages = agent._agent.memory.get_messages()
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "user",
        "assistant",
        "user",
    ]
    assert json.loads(messages[1]["content"]) == {"md_content": "# Shared paper"}
    assert "is_passed" in messages[2]["content"]
    assert "extraction_result" in messages[3]["content"]
    assert "Output validation failed" in messages[4]["content"]


class _FakeSection:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return self._payload


class _FakeExtractionResult:
    def __init__(self) -> None:
        self.quick_scan = _FakeSection({"quick_summary": "ok"})
        self.synthesis_data = _FakeSection({"review_summary": "ok"})

    def model_dump(self) -> dict[str, Any]:
        return {
            "quick_scan": self.quick_scan.model_dump(),
            "synthesis_data": self.synthesis_data.model_dump(),
        }


class _FakeError:
    def __init__(self) -> None:
        self.field_path = "synthesis_data.methodology.core_logic"
        self.suggestion = "Fix it"


class _FakeFactCheckResult:
    def __init__(self, is_passed: bool) -> None:
        self.is_passed = is_passed
        self.errors = [] if is_passed else [_FakeError()]

    def model_dump(self) -> dict[str, Any]:
        return {
            "is_passed": self.is_passed,
            "errors": [
                {
                    "field_path": e.field_path,
                    "suggestion": e.suggestion,
                }
                for e in self.errors
            ],
        }


class _FakeExtractionAgent:
    runtime_name = "ExtractionAgent"

    def __init__(self) -> None:
        self.trace_ids = ["trace-extraction"]

    def reset_memory(self) -> None:
        return

    def append_user_message(self, payload: dict[str, Any]) -> None:
        return

    def append_task_message(self) -> None:
        return

    def append_assistant_message(self, payload: dict[str, Any], *, name: str) -> None:
        return

    def build_user_message(self, md_content: str, images: list[str]) -> dict[str, Any]:
        return {"md_content": md_content, "images": images}

    async def run(self):
        return _FakeExtractionResult()


class _FakeFactCheckAgent:
    runtime_name = "FactCheckAgent"

    def __init__(self, result: Any) -> None:
        self._result = result
        self.trace_ids = ["trace-fact-check"]

    def reset_memory(self) -> None:
        return

    def append_user_message(self, payload: dict[str, Any]) -> None:
        return

    def append_task_message(self) -> None:
        return

    def append_assistant_message(self, payload: dict[str, Any], *, name: str) -> None:
        return

    def build_user_message(self, md_content: str, images: list[str]) -> dict[str, Any]:
        return {"md_content": md_content, "images": images}

    async def run(self):
        return self._result


class _FakeAnalysisResult:
    def __init__(self) -> None:
        self.analysis_report = _FakeSection(
            {
                "summary": "analysis-ok",
                "related_references": [
                    {"title": "Reference A", "reason": "classic prior work"}
                ],
            }
        )

    def model_dump(self) -> dict[str, Any]:
        return {"analysis_report": self.analysis_report.model_dump()}


class _FakeAnalysisAgent:
    runtime_name = "AnalysisAgent"

    def __init__(self) -> None:
        self.trace_ids = ["trace-analysis"]

    def reset_memory(self) -> None:
        return

    def append_user_message(self, payload: dict[str, Any]) -> None:
        return

    def append_task_message(self) -> None:
        return

    def append_assistant_message(self, payload: dict[str, Any], *, name: str) -> None:
        return

    def build_user_message(self, md_content: str, images: list[str]) -> dict[str, Any]:
        return {"md_content": md_content, "images": images}

    async def run(self):
        return _FakeAnalysisResult()


@pytest.mark.asyncio
async def test_group_does_not_raise_when_fact_check_failed_with_result() -> None:
    group = DataProcessorAgentGroup(
        extraction_agent=_FakeExtractionAgent(),  # type: ignore
        fact_check_agent1=_FakeFactCheckAgent(result=_FakeFactCheckResult(False)),  # type: ignore
    )

    extraction, fact_check, retry_count = await group.run_extraction_fact_check_loop(
        md_content="# md",
        images=[],
        max_retries=1,
    )

    assert extraction.quick_scan.model_dump()["quick_summary"] == "ok"
    assert fact_check.is_passed is False
    assert retry_count == 1


@pytest.mark.asyncio
async def test_group_run_parallel_loops_returns_both_branches_and_trace_ids() -> None:
    group = DataProcessorAgentGroup(
        extraction_agent=_FakeExtractionAgent(),  # type: ignore
        fact_check_agent1=_FakeFactCheckAgent(result=_FakeFactCheckResult(True)),  # type: ignore
        analysis_agent=_FakeAnalysisAgent(),  # type: ignore
        fact_check_agent2=_FakeFactCheckAgent(result=_FakeFactCheckResult(True)),  # type: ignore
    )

    (
        extraction_result,
        extraction_fact_check_result,
        extraction_retry_count,
        analysis_result,
        analysis_fact_check_result,
        analysis_retry_count,
    ) = await group.run_parallel_loops(md_content="# md", images=[], max_retries=2)

    assert extraction_result.quick_scan.model_dump()["quick_summary"] == "ok"
    assert extraction_fact_check_result.is_passed is True
    assert extraction_retry_count == 0

    assert analysis_result.analysis_report.model_dump()["summary"] == "analysis-ok"
    assert analysis_result.analysis_report.model_dump()["related_references"] == [
        {"title": "Reference A", "reason": "classic prior work"}
    ]
    assert analysis_fact_check_result.is_passed is True
    assert analysis_retry_count == 0

    assert group.extraction_trace_ids == ["trace-extraction"]
    assert group.analysis_trace_ids == ["trace-analysis"]
    assert group.extraction_fact_check_trace_ids == ["trace-fact-check"]
    assert group.analysis_fact_check_trace_ids == ["trace-fact-check"]
