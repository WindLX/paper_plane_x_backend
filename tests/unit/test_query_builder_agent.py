"""QueryBuilderAgent tests."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from paper_plane_x_backend.agents.query_builder import QueryBuilderAgent
from paper_plane_x_backend.schemas.agent_io.librarian import (
    QueryBuilderAgentInput,
    QueryBuilderAgentOutput,
)


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch) -> QueryBuilderAgent:
    """创建 QueryBuilderAgent 实例，mock 掉 LLM 调用。"""
    with patch.object(
        QueryBuilderAgent,
        "_build_system_prompt",
        return_value="system prompt",
    ):
        agent = QueryBuilderAgent()
    return agent


class TestQueryBuilderAgent:
    @pytest.mark.asyncio
    async def test_run_returns_structured_output(
        self, agent: QueryBuilderAgent
    ) -> None:
        """验证 run 返回 QueryBuilderAgentOutput。"""
        expected = QueryBuilderAgentOutput(
            query_expr="(meta.title CONTAINS transformer) AND (meta.year BETWEEN [2021, 2025])",
            explanation="查询标题包含 transformer 且年份在 2021-2025 之间的论文。",
        )
        agent._agent.run = AsyncMock(return_value=expected)

        result = await agent.run()
        assert isinstance(result, QueryBuilderAgentOutput)
        assert result.query_expr == expected.query_expr
        assert result.explanation == expected.explanation

    @pytest.mark.asyncio
    async def test_run_asserts_wrong_type(self, agent: QueryBuilderAgent) -> None:
        """验证 run 对错误返回类型触发断言。"""
        agent._agent.run = AsyncMock(return_value="wrong type")

        with pytest.raises(AssertionError, match="Expected output of type"):
            await agent.run()

    def test_append_user_message(self, agent: QueryBuilderAgent) -> None:
        """验证 append_user_message 将输入写入 memory。"""
        payload = QueryBuilderAgentInput(
            query="我想查询关于 GPT 的论文",
            project_context="NLP 项目",
        )
        agent.append_user_message(payload)
        messages = agent._agent.memory.get_messages()
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        content = json.loads(user_msgs[0]["content"])
        assert content["query"] == payload.query
        assert content["project_context"] == payload.project_context

    def test_trace_ids_empty_before_run(self, agent: QueryBuilderAgent) -> None:
        """验证运行前 trace_ids 为空。"""
        assert agent.trace_ids == []

    def test_runtime_name(self, agent: QueryBuilderAgent) -> None:
        """验证 runtime_name 为 agent_name。"""
        assert agent.runtime_name == "QueryBuilderAgent"

    def test_reset_memory(self, agent: QueryBuilderAgent) -> None:
        """验证 reset_memory 清空记忆。"""
        agent.append_user_message(
            QueryBuilderAgentInput(query="test", project_context=None)
        )
        assert (
            len([m for m in agent._agent.memory.get_messages() if m["role"] == "user"])
            == 1
        )
        agent.reset_memory()
        # reset_memory 保留 system prompt
        assert (
            len([m for m in agent._agent.memory.get_messages() if m["role"] == "user"])
            == 0
        )
