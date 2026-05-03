"""AgentTraceRepository tests."""

from datetime import datetime

import pytest

from paper_plane_x_backend.models import AgentTrace
from paper_plane_x_backend.services.agent_trace.repository import (
    AgentTraceRepository,
    AgentTraceRepositoryError,
)


class TestAgentTraceRepository:
    """AgentTraceRepository 测试类."""

    def test_create_and_batch_get(self, db) -> None:
        """验证创建 trace 后可批量查询."""
        repo = AgentTraceRepository(db)
        trace = AgentTrace(
            trace_id="trace-1",
            agent_name="TestAgent",
            messages=[{"role": "user", "content": "hi"}],
            llm_model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            usage_payload={"cost": 0.01},
            caller="SomeAgent",
            caller_id="caller-trace-1",
            created_at=datetime.now(),
        )
        repo.create(trace)

        results = repo.batch_get(["trace-1"])
        assert len(results) == 1
        assert results[0]["trace_id"] == "trace-1"
        assert results[0]["agent_name"] == "TestAgent"
        assert results[0]["llm_model"] == "gpt-4"
        assert results[0]["prompt_tokens"] == 10
        assert results[0]["completion_tokens"] == 5
        assert results[0]["total_tokens"] == 15
        assert results[0]["usage_payload"] == {"cost": 0.01}
        assert results[0]["caller"] == "SomeAgent"
        assert results[0]["caller_id"] == "caller-trace-1"
        assert results[0]["messages"] == [{"role": "user", "content": "hi"}]

    def test_batch_get_empty_list_returns_empty(self, db) -> None:
        """验证空列表批量查询返回空."""
        repo = AgentTraceRepository(db)
        assert repo.batch_get([]) == []

    def test_batch_get_preserves_request_order_with_dedup(self, db) -> None:
        """验证批量查询保留去重逻辑（由调用方处理）."""
        repo = AgentTraceRepository(db)
        for i in range(2):
            repo.create(
                AgentTrace(
                    trace_id=f"trace-{i}",
                    agent_name="A",
                    messages=[],
                    created_at=datetime.now(),
                )
            )
        results = repo.batch_get(["trace-0", "trace-1"])
        assert len(results) == 2
        ids = [r["trace_id"] for r in results]
        assert ids == ["trace-0", "trace-1"]

    def test_batch_get_skips_missing(self, db) -> None:
        """验证批量查询跳过不存在的 trace_id."""
        repo = AgentTraceRepository(db)
        repo.create(
            AgentTrace(
                trace_id="exists",
                agent_name="A",
                messages=[],
                created_at=datetime.now(),
            )
        )
        results = repo.batch_get(["exists", "missing"])
        assert len(results) == 1
        assert results[0]["trace_id"] == "exists"

    def test_delete(self, db) -> None:
        """验证删除 trace."""
        repo = AgentTraceRepository(db)
        repo.create(
            AgentTrace(
                trace_id="del-1",
                agent_name="A",
                messages=[],
                created_at=datetime.now(),
            )
        )
        repo.delete("del-1")
        assert repo.batch_get(["del-1"]) == []

    def test_delete_raises_for_missing(self, db) -> None:
        """验证删除不存在的 trace 抛出异常."""
        repo = AgentTraceRepository(db)
        with pytest.raises(AgentTraceRepositoryError, match="not found") as exc_info:
            repo.delete("missing")
        assert exc_info.value.error_code == "not_found"
        assert exc_info.value.trace_id == "missing"

    def test_parse_messages_from_json_string(self) -> None:
        """验证 messages 从 JSON 字符串解析."""
        result = AgentTraceRepository._parse_messages(
            '[{"role":"user","content":"hi"}]'
        )
        assert result == [{"role": "user", "content": "hi"}]

    def test_parse_messages_from_list(self) -> None:
        """验证 messages 从 list 透传."""
        result = AgentTraceRepository._parse_messages(
            [{"role": "user", "content": "hi"}]
        )
        assert result == [{"role": "user", "content": "hi"}]

    def test_parse_messages_invalid_json_returns_empty(self) -> None:
        """验证无效 JSON 返回空列表."""
        assert AgentTraceRepository._parse_messages("not-json") == []

    def test_parse_messages_non_dict_items_filtered(self) -> None:
        """验证非 dict 元素被过滤."""
        result = AgentTraceRepository._parse_messages(
            [{"role": "user"}, "not-dict", 123]
        )
        assert result == [{"role": "user"}]

    def test_parse_usage_payload_from_json_string(self) -> None:
        """验证 usage_payload 从 JSON 字符串解析."""
        result = AgentTraceRepository._parse_usage_payload('{"cost":0.01}')
        assert result == {"cost": 0.01}

    def test_parse_usage_payload_from_dict(self) -> None:
        """验证 usage_payload 从 dict 透传."""
        result = AgentTraceRepository._parse_usage_payload({"cost": 0.01})
        assert result == {"cost": 0.01}

    def test_parse_usage_payload_invalid_json_returns_none(self) -> None:
        """验证无效 JSON 返回 None."""
        assert AgentTraceRepository._parse_usage_payload("not-json") is None

    def test_row_to_trace_with_null_fields(self, db) -> None:
        """验证 row_to_trace 处理 NULL 字段."""
        repo = AgentTraceRepository(db)
        row = {
            "trace_id": "t-null",
            "agent_name": "A",
            "messages": None,
            "llm_model": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "usage_payload": None,
            "caller": None,
            "caller_id": None,
            "created_at": "2024-01-01T00:00:00",
        }
        trace = repo._row_to_trace(row)
        assert trace["trace_id"] == "t-null"
        assert trace["messages"] == []
        assert trace["llm_model"] is None
        assert trace["usage_payload"] is None
        assert trace["caller"] is None
        assert trace["caller_id"] is None
