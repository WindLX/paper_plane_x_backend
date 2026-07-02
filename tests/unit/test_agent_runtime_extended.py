"""Agent Core 扩展测试.

补充 BaseAgent/LLMClient/Tool schema 的边界覆盖。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from paper_plane_x_backend.core.agent_runtime import (
    AgentExecutionError,
    AgentValidationError,
    BaseAgent,
    LLMClient,
    LLMResponse,
    MemoryManager,
    ToolRegistry,
    tool,
)
from paper_plane_x_backend.models.app_settings import LLMConfig
from paper_plane_x_backend.schemas.agent_io.base import (
    ToolCallFunction,
    ToolCallMessage,
    ToolMessage,
)

DEFAULT_LLM_CONFIG = LLMConfig(model="gpt-4o", api_key="test-key")


class ApiOutput(BaseModel):
    value: str


class StrictTwoFieldsOutput(BaseModel):
    value: str
    detail: str


class FakeDB:
    def __init__(self) -> None:
        self.inserts: list[tuple[str, dict[str, Any]]] = []

    def insert(self, table: str, data: dict[str, Any]) -> None:
        self.inserts.append((table, data))


class TestBaseAgentExtended:
    @staticmethod
    async def _run_with_input(
        agent: BaseAgent,
        user_input: dict[str, object],
    ) -> BaseModel | str:
        agent.memory.append_user_message(user_input)
        return await agent.run()

    def test_api_mode_requires_schema(self) -> None:
        with pytest.raises(ValueError, match="output_schema is required"):
            BaseAgent(llm_config=DEFAULT_LLM_CONFIG, mode="api")

    @pytest.mark.asyncio
    async def test_api_mode_wraps_non_validation_error(self) -> None:
        agent = BaseAgent(
            llm_config=DEFAULT_LLM_CONFIG,
            output_schema=ApiOutput,
            mode="api",
            save_trace=False,
        )

        async def mock_generate_structured(messages, output_schema, **kwargs):
            raise RuntimeError("llm down")

        agent.llm.generate_structured = mock_generate_structured

        with pytest.raises(AgentExecutionError, match="API mode execution failed"):
            await self._run_with_input(agent, {"x": 1})

    @pytest.mark.asyncio
    async def test_save_trace_success_normal_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = BaseAgent(llm_config=DEFAULT_LLM_CONFIG, mode="normal", save_trace=True)

        async def mock_generate(messages, **kwargs):
            return LLMResponse(
                content="ok",
                reasoning_content="trace thinking",
                model="trace-model",
                usage={
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                    "cache_hit": False,
                },
            )

        fake_db = FakeDB()
        monkeypatch.setattr(
            "paper_plane_x_backend.core.agent_runtime.base_agent.get_db",
            lambda: fake_db,
        )
        agent.llm.generate = mock_generate

        result = await self._run_with_input(
            agent,
            {"query": "q"},
        )

        assert result == "ok"
        assert len(fake_db.inserts) == 1
        table, payload = fake_db.inserts[0]
        assert table == "agent_traces"
        assert payload["agent_name"] == agent.agent_name
        assert payload["llm_model"] == "trace-model"
        assert payload["prompt_tokens"] == 11
        assert payload["completion_tokens"] == 7
        assert payload["total_tokens"] == 18
        assert "cache_hit" in payload["usage_payload"]
        assert agent.trace_ids == [payload["trace_id"]]

    def test_save_trace_maps_input_output_tokens_to_columns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = BaseAgent(llm_config=DEFAULT_LLM_CONFIG, mode="normal", save_trace=True)
        fake_db = FakeDB()
        monkeypatch.setattr(
            "paper_plane_x_backend.core.agent_runtime.base_agent.get_db",
            lambda: fake_db,
        )

        agent.save_trace_snapshot(
            messages=[{"role": "user", "content": "hi"}],
            usage={"input_tokens": 9, "output_tokens": 4},
        )

        _, payload = fake_db.inserts[0]
        assert payload["prompt_tokens"] == 9
        assert payload["completion_tokens"] == 4
        assert payload["total_tokens"] == 13

    @pytest.mark.asyncio
    async def test_api_mode_collects_all_trace_ids_across_validation_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = BaseAgent(
            llm_config=DEFAULT_LLM_CONFIG,
            output_schema=ApiOutput,
            mode="api",
            save_trace=True,
            max_steps=2,
        )
        fake_db = FakeDB()
        monkeypatch.setattr(
            "paper_plane_x_backend.core.agent_runtime.base_agent.get_db",
            lambda: fake_db,
        )

        call_count = 0

        async def mock_generate_structured(messages, output_schema, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(content="{invalid json}", model="m", usage={})
            return LLMResponse(content='{"value": "ok"}', model="m", usage={})

        agent.llm.generate_structured = mock_generate_structured

        result = await self._run_with_input(agent, {"q": "x"})

        assert isinstance(result, ApiOutput)
        assert len(fake_db.inserts) == 2
        saved_trace_ids = [
            payload["trace_id"]
            for table, payload in fake_db.inserts
            if table == "agent_traces"
        ]
        assert agent.trace_ids == saved_trace_ids

    @pytest.mark.asyncio
    async def test_api_mode_retries_empty_thinking_response_without_thinking(
        self,
    ) -> None:
        config = LLMConfig(
            model="deepseek-v4-flash",
            api_key="test-key",
            thinking_enabled=True,
            reasoning_effort="max",
        )
        agent = BaseAgent(
            llm_config=config,
            output_schema=ApiOutput,
            mode="api",
            save_trace=False,
            max_steps=2,
        )
        calls: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []

        async def mock_generate_structured(messages, output_schema, **kwargs):
            calls.append(([dict(message) for message in messages], dict(kwargs)))
            if len(calls) == 1:
                return LLMResponse(
                    content="",
                    reasoning_content="reasoning consumed the response",
                    model="deepseek-v4-flash",
                    usage={},
                )
            return LLMResponse(
                content='{"value": "ok"}',
                model="deepseek-v4-flash",
                usage={},
            )

        agent.llm.generate_structured = mock_generate_structured

        result = await self._run_with_input(agent, {"q": "x"})

        assert isinstance(result, ApiOutput)
        assert result.value == "ok"
        assert calls[0][1] == {}
        assert calls[1][1] == {
            "extra_body": {"thinking": {"type": "disabled"}},
            "reasoning_effort": None,
        }
        assert all(message["role"] != "assistant" for message in calls[1][0])
        assert "Output validation failed" in calls[1][0][-1]["content"]

    @pytest.mark.asyncio
    async def test_tool_argument_json_error_bubbles_to_execution_error(self) -> None:
        @tool()
        def noop() -> str:
            return "ok"

        agent = BaseAgent(
            llm_config=DEFAULT_LLM_CONFIG,
            mode="normal",
            tools=[noop],
            max_steps=1,
            save_trace=False,
        )

        async def mock_generate_with_tools(messages, tools, **kwargs):
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallMessage(
                        id="c1",
                        type="function",
                        function=ToolCallFunction(
                            name="noop",
                            arguments="{bad-json}",
                        ),
                    )
                ],
            )

        agent.llm.generate_with_tools = mock_generate_with_tools

        with pytest.raises(AgentExecutionError, match="Step execution failed"):
            await self._run_with_input(agent, {"x": 1})

    @pytest.mark.asyncio
    async def test_api_mode_prefers_larger_json_candidate(self) -> None:
        agent = BaseAgent(
            llm_config=DEFAULT_LLM_CONFIG,
            output_schema=StrictTwoFieldsOutput,
            mode="api",
            save_trace=False,
            max_steps=1,
        )

        async def mock_generate_structured(messages, output_schema, **kwargs):
            return LLMResponse(
                content=('small={"value":"v"}\nlarge={"value":"v","detail":"use-me"}'),
                model="test-model",
                usage={},
            )

        agent.llm.generate_structured = mock_generate_structured

        result = await self._run_with_input(agent, {"q": "x"})
        assert isinstance(result, StrictTwoFieldsOutput)
        assert result.value == "v"
        assert result.detail == "use-me"

    @pytest.mark.asyncio
    async def test_api_mode_rejects_array_root_json(self) -> None:
        agent = BaseAgent(
            llm_config=DEFAULT_LLM_CONFIG,
            output_schema=ApiOutput,
            mode="api",
            save_trace=False,
            max_steps=2,
        )

        call_count = 0

        async def mock_generate_structured(messages, output_schema, **kwargs):
            nonlocal call_count
            call_count += 1
            return LLMResponse(
                content='[{"value": "not-allowed"}]',
                model="test-model",
                usage={},
            )

        agent.llm.generate_structured = mock_generate_structured

        with pytest.raises(
            AgentValidationError,
            match="root type must be JSON object",
        ):
            await self._run_with_input(agent, {"q": "x"})
        assert call_count == 2


class TestMemoryManagerExtended:
    def test_short_memory_window_keeps_recent_messages(self) -> None:
        memory = MemoryManager(short_memory_window=2)

        memory.append_user_message({"q": "first"})
        memory.append_assistant_message(content="ok")
        memory.append_user_message({"q": "second"})

        messages = memory.get_messages()

        assert len(messages) == 2
        assert messages[0]["role"] == "assistant"
        assert messages[1]["role"] == "user"

    def test_update_messages_by_role(self) -> None:
        memory = MemoryManager()

        memory.append_user_message({"q": "old"})
        memory.append_assistant_message(
            content="old assistant",
            reasoning_content="old thinking",
        )
        memory.append_tool_message(
            ToolMessage(
                role="tool", tool_call_id="t1", name="search", content="old tool"
            )
        )

        memory.update_user_message({"q": "new"})
        memory.update_assistant_message(
            content="new assistant",
            reasoning_content="new thinking",
        )
        memory.update_tool_message(
            ToolMessage(
                role="tool", tool_call_id="t1", name="search", content="new tool"
            )
        )

        messages = memory.get_messages()
        assert messages[0]["role"] == "user"
        assert '"q": "new"' in str(messages[0]["content"])
        assert messages[1]["content"] == "new assistant"
        assert messages[1]["reasoning_content"] == "new thinking"
        assert messages[2]["content"] == "new tool"

    def test_assistant_message_omits_empty_reasoning_content(self) -> None:
        memory = MemoryManager()

        memory.append_assistant_message(content="ok")

        assert memory.get_messages() == [{"role": "assistant", "content": "ok"}]

    def test_delete_messages_by_role(self) -> None:
        memory = MemoryManager()

        memory.append_user_message({"q": "u1"})
        memory.append_assistant_message(content="a1")
        memory.append_tool_message(
            ToolMessage(role="tool", tool_call_id="t1", name="search", content="x")
        )

        memory.delete_tool_message()
        memory.delete_assistant_message()
        memory.delete_user_message()

        assert memory.get_messages() == []

    def test_update_delete_raise_when_role_missing(self) -> None:
        memory = MemoryManager()

        with pytest.raises(IndexError):
            memory.delete_user_message()
        with pytest.raises(IndexError):
            memory.update_assistant_message(content="x")

    def test_occurrence_from_end_validation(self) -> None:
        memory = MemoryManager()
        memory.append_user_message({"q": "u1"})

        with pytest.raises(ValueError, match="occurrence_from_end"):
            memory.delete_user_message(occurrence_from_end=0)


class TestLLMClientExtended:
    def test_from_config_maps_fields(self) -> None:
        cfg = LLMConfig(
            model="m1",
            api_key="k1",
            base_url="http://x",
            temperature=0.1,
            max_tokens=12,
            timeout=9.0,
            custom_headers={"X-Test": "1"},
            thinking_enabled=True,
            reasoning_effort="high",
            extra_body={"vendor": {"flag": True}},
        )
        client = LLMClient.from_config(cfg)

        assert client.model == "m1"
        assert client.api_key == "k1"
        assert client.base_url == "http://x"
        assert client.temperature == 0.1
        assert client.max_tokens == 12
        assert client.timeout == 9.0
        assert client.custom_headers == {"X-Test": "1"}
        assert client.thinking_enabled is True
        assert client.reasoning_effort == "high"
        assert client.extra_body == {"vendor": {"flag": True}}

    @pytest.mark.asyncio
    async def test_chat_builds_tool_request(
        self, capture_llm_request: dict[str, Any]
    ) -> None:
        client = LLMClient(model="m", api_key="k")
        tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]

        resp = await client.chat(
            messages=[{"role": "user", "content": "hi"}], tools=tools
        )

        assert resp.content == "ok"
        assert capture_llm_request["tools"] == tools
        assert capture_llm_request["tool_choice"] == "auto"
        assert capture_llm_request["api_key"] == "k"

    @pytest.mark.asyncio
    async def test_chat_builds_structured_request(
        self, capture_llm_request: dict[str, Any]
    ) -> None:
        client = LLMClient(model="m")
        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            output_schema=ApiOutput,
            temperature=0.33,
        )

        assert capture_llm_request["response_format"]["type"] == "json_object"
        assert "schema" in capture_llm_request["response_format"]
        assert capture_llm_request["temperature"] == 0.33

    @pytest.mark.asyncio
    async def test_chat_infers_openai_provider_for_base_url(
        self, capture_llm_request: dict[str, Any]
    ) -> None:
        client = LLMClient(model="deepseek-chat", base_url="https://example.com/v1")
        await client.chat(messages=[{"role": "user", "content": "hi"}])

        assert capture_llm_request["model"] == "deepseek-chat"
        assert capture_llm_request["custom_llm_provider"] == "openai"

    @pytest.mark.asyncio
    async def test_chat_builds_reasoning_request(
        self, capture_llm_request: dict[str, Any]
    ) -> None:
        client = LLMClient(
            model="deepseek-chat",
            thinking_enabled=True,
            reasoning_effort="high",
            extra_body={"metadata": {"source": "config"}},
        )
        await client.chat(messages=[{"role": "user", "content": "hi"}])

        assert capture_llm_request["reasoning_effort"] == "high"
        assert capture_llm_request["allowed_openai_params"] == ["reasoning_effort"]
        assert capture_llm_request["extra_body"] == {
            "thinking": {"type": "enabled"},
            "metadata": {"source": "config"},
        }

    @pytest.mark.asyncio
    async def test_chat_allows_extra_body_override(
        self, capture_llm_request: dict[str, Any]
    ) -> None:
        client = LLMClient(
            model="deepseek-chat",
            thinking_enabled=True,
            reasoning_effort="medium",
        )
        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            reasoning_effort="low",
            extra_body={"thinking": {"type": "disabled"}},
        )

        assert capture_llm_request["reasoning_effort"] == "low"
        assert capture_llm_request["allowed_openai_params"] == ["reasoning_effort"]
        assert capture_llm_request["extra_body"] == {"thinking": {"type": "disabled"}}

    @pytest.mark.asyncio
    async def test_chat_omits_reasoning_fields_by_default(
        self, capture_llm_request: dict[str, Any]
    ) -> None:
        client = LLMClient(model="m")
        await client.chat(messages=[{"role": "user", "content": "hi"}])

        assert "extra_body" not in capture_llm_request
        assert "reasoning_effort" not in capture_llm_request

    def test_parse_response_with_tool_calls(self, make_litellm_response) -> None:
        client = LLMClient(model="m")
        tc = SimpleNamespace(
            id="id1",
            type="function",
            function=SimpleNamespace(name="sum", arguments='{"a":1}'),
        )
        raw = make_litellm_response(
            content=None,
            reasoning_content="thinking",
            tool_calls=[tc],
            usage={"total_tokens": 5},
        )

        parsed = client._parse_response(raw)

        assert parsed.content is None
        assert parsed.reasoning_content == "thinking"
        assert parsed.tool_calls is not None
        assert parsed.tool_calls[0].function.name == "sum"
        assert parsed.usage["total_tokens"] == 5

    def test_parse_response_ignores_non_string_reasoning_content(
        self, make_litellm_response
    ) -> None:
        client = LLMClient(model="m")
        raw = make_litellm_response(content="ok", reasoning_content={"bad": True})

        parsed = client._parse_response(raw)

        assert parsed.content == "ok"
        assert parsed.reasoning_content is None

    def test_extract_usage_from_attribute_object(self) -> None:
        client = LLMClient(model="m")

        class UsageObject:
            prompt_tokens = 12
            completion_tokens = 3
            total_tokens = 15

        class ResponseObject:
            usage = UsageObject()

        parsed = client._extract_usage(ResponseObject())

        assert parsed == {
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "total_tokens": 15,
        }

    @pytest.mark.asyncio
    async def test_tool_registry_execute_tool_call_returns_tool_message(self) -> None:
        @tool()
        def code_runner(language: str, code: str) -> dict[str, str]:
            return {"language": language, "code": code}

        registry = ToolRegistry()
        registry.register(code_runner)

        tool_call = ToolCallMessage(
            id="1",
            function=ToolCallFunction(
                name="code_runner",
                arguments='{"language":"python","code":"print(1)"}',
            ),
        )

        tool_msg = await registry.execute_tool_call(tool_call)

        assert tool_msg.role == "tool"
        assert tool_msg.tool_call_id == "1"
        assert tool_msg.name == "code_runner"
        assert '"language": "python"' in tool_msg.content


class TestToolSchemaExtended:
    def test_tool_schema_for_optional_union_and_collections(self) -> None:
        @tool()
        def complex_tool(
            a: int | None,
            b: str | int,
            c: list[int],
            d: dict[str, int],
        ) -> None:
            return None

        props = complex_tool.parameters["properties"]
        assert props["a"]["type"] == "integer"
        assert props["a"]["nullable"] is True
        assert "anyOf" in props["b"]
        assert props["c"]["type"] == "array"
        assert props["c"]["items"]["type"] == "integer"
        assert props["d"]["type"] == "object"

    def test_tool_schema_ignores_annotated_metadata(self) -> None:
        @tool()
        def annotated_tool(
            query: Annotated[
                str,
                "搜索关键词",
                {"examples": ["llm safety"]},
            ],
        ) -> None:
            return None

        query_schema = annotated_tool.parameters["properties"]["query"]
        assert query_schema["type"] == "string"
        assert "description" not in query_schema
        assert "examples" not in query_schema

    @pytest.mark.asyncio
    async def test_execute_raises_when_function_unbound(self) -> None:
        # 通过装饰器创建后手动清空 function，模拟异常路径
        @tool()
        def t(x: int) -> int:
            return x

        t.function = None

        with pytest.raises(RuntimeError, match="has no bound function"):
            await t.execute(x=1)


class TestLLMClientStream:
    """LLMClient chat_stream 流式调用测试."""

    @pytest.mark.asyncio
    async def test_chat_stream_sets_stream_flag(
        self, capture_llm_request: dict[str, Any]
    ) -> None:
        """验证 chat_stream 在请求中设置 stream=True."""
        client = LLMClient(model="m")

        # 需要一个模拟的流式响应
        async def fake_stream():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="ok"), finish_reason="stop"
                    )
                ],
                model="m",
            )

        import paper_plane_x_backend.core.agent_runtime.llm_client as llm_mod

        original_acompletion = llm_mod.acompletion

        async def mock_acompletion(**kwargs):
            capture_llm_request.update(kwargs)
            return fake_stream()

        llm_mod.acompletion = mock_acompletion
        try:
            chunks = []
            async for chunk in client.chat_stream(
                messages=[{"role": "user", "content": "hi"}]
            ):
                chunks.append(chunk)
            assert capture_llm_request["stream"] is True
            assert len(chunks) == 1
            assert chunks[0].content_delta == "ok"
            assert chunks[0].is_finished is True
        finally:
            llm_mod.acompletion = original_acompletion

    @pytest.mark.asyncio
    async def test_chat_stream_yields_content_deltas(self) -> None:
        """验证 chat_stream 逐块 yield content_delta."""
        client = LLMClient(model="m")

        async def fake_stream():
            deltas = ["Hel", "lo"]
            for i, d in enumerate(deltas):
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=d),
                            finish_reason="stop" if i == len(deltas) - 1 else None,
                        )
                    ],
                    model="m",
                )

        import paper_plane_x_backend.core.agent_runtime.llm_client as llm_mod

        original_acompletion = llm_mod.acompletion

        async def mock_acompletion(**kwargs):
            return fake_stream()

        llm_mod.acompletion = mock_acompletion
        try:
            chunks = []
            async for chunk in client.chat_stream(
                messages=[{"role": "user", "content": "hi"}]
            ):
                chunks.append(chunk)
            assert len(chunks) == 2
            assert chunks[0].content_delta == "Hel"
            assert chunks[0].is_finished is False
            assert chunks[1].content_delta == "lo"
            assert chunks[1].is_finished is True
        finally:
            llm_mod.acompletion = original_acompletion

    @pytest.mark.asyncio
    async def test_chat_stream_yields_reasoning_content_deltas(self) -> None:
        """验证 chat_stream 能解析 reasoning_content_delta."""
        client = LLMClient(model="m")

        async def fake_stream():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="ok", reasoning_content="think"),
                        finish_reason="stop",
                    )
                ],
                model="m",
            )

        import paper_plane_x_backend.core.agent_runtime.llm_client as llm_mod

        original_acompletion = llm_mod.acompletion

        async def mock_acompletion(**kwargs):
            return fake_stream()

        llm_mod.acompletion = mock_acompletion
        try:
            chunks = []
            async for chunk in client.chat_stream(
                messages=[{"role": "user", "content": "hi"}]
            ):
                chunks.append(chunk)
            assert chunks[0].content_delta == "ok"
            assert chunks[0].reasoning_content_delta == "think"
        finally:
            llm_mod.acompletion = original_acompletion

    @pytest.mark.asyncio
    async def test_chat_stream_accumulates_tool_calls(self) -> None:
        """验证 chat_stream 能按 index 累积流式 tool_calls."""
        client = LLMClient(model="m")

        async def fake_stream():
            # 分两段返回同一个 tool_call
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="tc-1",
                                    function=SimpleNamespace(
                                        name="g", arguments='{"a":'
                                    ),
                                )
                            ],
                        ),
                        finish_reason=None,
                    )
                ],
                model="m",
            )
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    function=SimpleNamespace(name="", arguments="1}"),
                                )
                            ],
                        ),
                        finish_reason="stop",
                    )
                ],
                model="m",
            )

        import paper_plane_x_backend.core.agent_runtime.llm_client as llm_mod

        original_acompletion = llm_mod.acompletion

        async def mock_acompletion(**kwargs):
            return fake_stream()

        llm_mod.acompletion = mock_acompletion
        try:
            chunks = []
            async for chunk in client.chat_stream(
                messages=[{"role": "user", "content": "hi"}]
            ):
                chunks.append(chunk)
            # 非 finish 块不携带 tool_calls
            assert chunks[0].tool_calls == []
            # finish 块携带累积后的 tool_calls
            assert len(chunks[1].tool_calls) == 1
            assert chunks[1].tool_calls[0].function.name == "g"
            assert chunks[1].tool_calls[0].function.arguments == '{"a":1}'
        finally:
            llm_mod.acompletion = original_acompletion

    @pytest.mark.asyncio
    async def test_chat_stream_yields_usage_from_terminal_usage_only_chunk(
        self,
    ) -> None:
        """验证 chat_stream 不会丢掉只有 usage 的末尾 chunk."""
        client = LLMClient(model="m")

        async def fake_stream():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="done"),
                        finish_reason="stop",
                    )
                ],
                model="m",
            )
            yield SimpleNamespace(
                choices=[],
                model="m",
                usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            )

        import paper_plane_x_backend.core.agent_runtime.llm_client as llm_mod

        original_acompletion = llm_mod.acompletion

        async def mock_acompletion(**kwargs):
            return fake_stream()

        llm_mod.acompletion = mock_acompletion
        try:
            chunks = []
            async for chunk in client.chat_stream(
                messages=[{"role": "user", "content": "hi"}]
            ):
                chunks.append(chunk)
            assert len(chunks) == 2
            assert chunks[0].content_delta == "done"
            assert chunks[0].usage == {}
            assert chunks[1].content_delta is None
            assert chunks[1].usage == {
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "total_tokens": 15,
            }
        finally:
            llm_mod.acompletion = original_acompletion

    @pytest.mark.asyncio
    async def test_chat_stream_yields_usage_when_present_on_non_finished_chunk(
        self,
    ) -> None:
        """验证 usage 出现在 finish_reason=None 的 chunk 上时也会透传."""
        client = LLMClient(model="m")

        async def fake_stream():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None),
                        finish_reason="tool_calls",
                    )
                ],
                model="m",
            )
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None),
                        finish_reason=None,
                    )
                ],
                model="m",
                usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            )

        import paper_plane_x_backend.core.agent_runtime.llm_client as llm_mod

        original_acompletion = llm_mod.acompletion

        async def mock_acompletion(**kwargs):
            return fake_stream()

        llm_mod.acompletion = mock_acompletion
        try:
            chunks = []
            async for chunk in client.chat_stream(
                messages=[{"role": "user", "content": "hi"}]
            ):
                chunks.append(chunk)
            assert len(chunks) == 2
            assert chunks[1].usage == {
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "total_tokens": 15,
            }
        finally:
            llm_mod.acompletion = original_acompletion

    def test_build_messages_with_tool_guide_renders_shared_guide_in_system_prompt(
        self,
    ) -> None:
        """验证共享 guide 被渲染到唯一的 system prompt 中."""

        @tool(
            name="test_tool",
            description="A test tool.",
            shared_guides={"Test Guide": "This is the test guide content."},
        )
        def test_tool(x: str) -> str:
            return x

        agent = BaseAgent(
            mode="normal",
            system_prompt="You are a test agent.\n\n{{TOOLSET_SHARED_GUIDE}}",
            tools=[test_tool],
            llm_config=DEFAULT_LLM_CONFIG,
        )
        agent.memory.append_user_message({"content": "hello"})

        messages = agent.build_messages_with_tool_guide()

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "You are a test agent." in messages[0]["content"]
        assert "Toolset Shared Guide:" in messages[0]["content"]
        assert "[Test Guide]" in messages[0]["content"]
        assert "This is the test guide content." in messages[0]["content"]
        assert messages[1]["role"] == "user"

    def test_build_messages_without_tools_returns_plain_messages(self) -> None:
        """验证没有工具时 build_messages_with_tool_guide 返回原始消息."""
        agent = BaseAgent(
            mode="normal",
            system_prompt="You are a test agent.",
            llm_config=DEFAULT_LLM_CONFIG,
        )
        agent.memory.append_user_message({"content": "hello"})

        messages = agent.build_messages_with_tool_guide()

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
