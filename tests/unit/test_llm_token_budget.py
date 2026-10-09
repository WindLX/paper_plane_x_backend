"""Token budget regressions, with no provider calls or private prompts."""

from typing import Any

import pytest
from pydantic import BaseModel

from paper_plane_x_backend.core.agent_runtime import llm_client as llm_module
from paper_plane_x_backend.core.agent_runtime.llm_client import LLMClient
from paper_plane_x_backend.models.app_settings import AgentLLMConfigEntry, LLMConfig


class SyntheticOutput(BaseModel):
    answer: str


def fake_count(*, model: str, messages=None, text=None, **kwargs) -> int:
    return 512 if text is not None else 76261


def test_default_budget_is_240000_and_generation_is_auto() -> None:
    for config in (LLMConfig(), AgentLLMConfigEntry()):
        assert config.max_total_tokens == 240000
        assert "max_tokens" not in type(config).model_fields


@pytest.mark.asyncio
async def test_long_prompt_reduces_output_instead_of_reserving_total_budget(
    monkeypatch: pytest.MonkeyPatch, capture_llm_request: dict[str, Any]
) -> None:
    monkeypatch.setattr(llm_module, "token_counter", fake_count)
    client = LLMClient(
        model="openai/synthetic",
        max_total_tokens=240000,
        context_window_tokens=262144,
    )
    messages = [
        {"role": "system", "content": "synthetic system"},
        {"role": "user", "content": "synthetic input"},
    ]
    await client.chat(messages)
    assert capture_llm_request["max_tokens"] == 240000 - 76261 - 4096
    assert capture_llm_request["messages"] == messages
    assert "max_total_tokens" not in capture_llm_request


@pytest.mark.asyncio
async def test_structured_request_includes_schema_in_budget(
    monkeypatch: pytest.MonkeyPatch, capture_llm_request: dict[str, Any]
) -> None:
    monkeypatch.setattr(llm_module, "token_counter", fake_count)
    client = LLMClient(model="openai/synthetic", max_total_tokens=240000)
    await client.generate_structured(
        [{"role": "user", "content": "input"}], SyntheticOutput
    )
    assert capture_llm_request["max_tokens"] == 240000 - 76261 - 512 - 4096


@pytest.mark.asyncio
async def test_model_context_and_output_limits_apply(
    monkeypatch: pytest.MonkeyPatch, capture_llm_request: dict[str, Any]
) -> None:
    monkeypatch.setattr(llm_module, "token_counter", fake_count)
    client = LLMClient(
        model="openai/synthetic", context_window_tokens=100000, max_output_tokens=12000
    )
    await client.chat([{"role": "user", "content": "input"}])
    assert capture_llm_request["max_tokens"] == 12000
    client = LLMClient(model="openai/synthetic", context_window_tokens=80000)
    with pytest.raises(ValueError, match="token budget"):
        await client.chat([{"role": "user", "content": "input"}])


@pytest.mark.asyncio
async def test_complete_tool_messages_are_counted_each_time(
    monkeypatch: pytest.MonkeyPatch, capture_llm_request: dict[str, Any]
) -> None:
    inputs: list[list[dict[str, Any]]] = []
    tools = [{"type": "function", "function": {"name": "read", "parameters": {}}}]

    def count(*, messages=None, tools=None, **kwargs):
        assert tools is not None
        inputs.append(messages)
        return 5000 * len(messages)

    monkeypatch.setattr(llm_module, "token_counter", count)
    client = LLMClient(model="openai/synthetic")
    messages = [{"role": "user", "content": "input"}]
    await client.generate_with_tools(messages, tools)
    first_limit = capture_llm_request["max_tokens"]
    messages = messages + [
        {"role": "assistant", "tool_calls": []},
        {"role": "tool", "content": "synthetic result", "tool_call_id": "call-test"},
    ]
    await client.generate_with_tools(messages, tools)
    assert capture_llm_request["max_tokens"] == first_limit - 10000
    assert inputs == [[{"role": "user", "content": "input"}], messages]


@pytest.mark.asyncio
async def test_registry_capabilities_and_explicit_gateway_overrides(
    monkeypatch: pytest.MonkeyPatch, capture_llm_request: dict[str, Any]
) -> None:
    monkeypatch.setattr(llm_module, "token_counter", fake_count)
    monkeypatch.setattr(
        llm_module,
        "model_cost",
        {"synthetic-known": {"max_input_tokens": 100000, "max_output_tokens": 12000}},
    )
    client = LLMClient(model="openai/synthetic-known")
    await client.chat([{"role": "user", "content": "input"}])
    assert capture_llm_request["max_tokens"] == 12000
    client = LLMClient(
        model="openai/synthetic-known",
        context_window_tokens=262144,
        max_output_tokens=200000,
    )
    await client.chat([{"role": "user", "content": "input"}])
    assert capture_llm_request["max_tokens"] == 240000 - 76261 - 4096


@pytest.mark.asyncio
async def test_stream_and_normal_calls_use_the_same_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    captured: dict[str, Any] = {}

    async def chunks():
        yield SimpleNamespace(
            model="synthetic",
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="ok"), finish_reason="stop"
                )
            ],
            usage={},
        )

    async def complete(**kwargs):
        captured.update(kwargs)
        return chunks()

    monkeypatch.setattr(llm_module, "token_counter", fake_count)
    monkeypatch.setattr(llm_module, "acompletion", complete)
    client = LLMClient(model="openai/synthetic")
    result = [
        chunk
        async for chunk in client.chat_stream([{"role": "user", "content": "input"}])
    ]
    assert result
    assert captured["stream"] is True
    assert captured["max_tokens"] == 240000 - 76261 - 4096


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        {"max_tokens": 200000},
        {"max_completion_tokens": 200000},
        {"extra_body": {"max_tokens": 200000}},
    ],
)
async def test_legacy_overrides_cannot_bypass_budget(
    monkeypatch: pytest.MonkeyPatch,
    capture_llm_request: dict[str, Any],
    options: dict[str, Any],
) -> None:
    monkeypatch.setattr(llm_module, "token_counter", fake_count)
    client = LLMClient(model="openai/synthetic")
    with pytest.raises(ValueError, match="automatic"):
        await client.chat([{"role": "user", "content": "input"}], **options)
    assert capture_llm_request == {}


def test_legacy_config_field_is_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Extra inputs"):
        AgentLLMConfigEntry.model_validate(
            {"provider_name": "default", "max_tokens": 200000}
        )
