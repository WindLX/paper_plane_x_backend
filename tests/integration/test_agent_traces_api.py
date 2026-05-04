"""Agent traces API tests."""

import json
from datetime import datetime

from fastapi.testclient import TestClient

from paper_plane_x_backend.services import Database


class TestAgentTracesAPI:
    def test_query_agent_traces_returns_items_in_request_order(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        now = datetime.now()
        db.insert(
            "agent_traces",
            {
                "trace_id": "trc-test-1",
                "agent_name": "ExtractionAgent",
                "messages": json.dumps(
                    [{"role": "assistant", "content": "hello"}], ensure_ascii=False
                ),
                "llm_model": "deepseek-v4-flash",
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
                "usage_payload": json.dumps({"cache_hit": False}, ensure_ascii=False),
                "created_at": now,
            },
        )
        db.insert(
            "agent_traces",
            {
                "trace_id": "trc-test-2",
                "agent_name": "FactCheckAgent",
                "messages": json.dumps(
                    [{"role": "user", "content": "world"}], ensure_ascii=False
                ),
                "llm_model": "deepseek-v4-flash",
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
                "usage_payload": json.dumps({"cache_hit": True}, ensure_ascii=False),
                "created_at": now,
            },
        )

        response = client.post(
            "/api/v1/agent-traces/query",
            json={"trace_ids": ["trc-test-2", "trc-test-1", "missing", "trc-test-2"]},
        )
        assert response.status_code == 200
        payload = response.json()
        items = payload["items"]
        assert [item["trace_id"] for item in items] == ["trc-test-2", "trc-test-1"]
        assert items[0]["messages"][0]["role"] == "user"
        assert items[1]["messages"][0]["content"] == "hello"
        assert items[0]["usage_payload"]["cache_hit"] is True
        assert items[1]["total_tokens"] == 30

    def test_query_agent_traces_empty_request_returns_empty(
        self,
        client: TestClient,
    ) -> None:
        response = client.post(
            "/api/v1/agent-traces/query",
            json={"trace_ids": []},
        )
        assert response.status_code == 200
        assert response.json() == {"items": []}


class TestAgentTraceListAPI:
    """Agent trace list API 测试。"""

    def test_list_returns_pagination_and_stats(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        now = datetime.now()
        db.insert(
            "agent_traces",
            {
                "trace_id": "trc-test-1",
                "agent_name": "ExtractionAgent",
                "messages": json.dumps([{"role": "assistant"}], ensure_ascii=False),
                "llm_model": "deepseek-v4-flash",
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
                "usage_payload": json.dumps({}, ensure_ascii=False),
                "caller": "api",
                "caller_id": None,
                "created_at": now,
            },
        )
        db.insert(
            "agent_traces",
            {
                "trace_id": "trc-test-2",
                "agent_name": "FactCheckAgent",
                "messages": json.dumps([{"role": "user"}], ensure_ascii=False),
                "llm_model": "deepseek-v4-flash",
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
                "usage_payload": json.dumps({}, ensure_ascii=False),
                "caller": "data_process",
                "caller_id": "pap-test-1",
                "created_at": now,
            },
        )

        response = client.post(
            "/api/v1/agent-traces/list",
            json={
                "offset": 0,
                "limit": 10,
                "sort_by": "created_at",
                "sort_order": "desc",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 2
        assert len(payload["items"]) == 2
        assert payload["offset"] == 0
        assert payload["limit"] == 10
        assert payload["stats"]["agent_name_counts"]["ExtractionAgent"] == 1
        assert payload["stats"]["agent_name_counts"]["FactCheckAgent"] == 1

    def test_list_filters_by_agent_name(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        now = datetime.now()
        db.insert(
            "agent_traces",
            {
                "trace_id": "trc-test-1",
                "agent_name": "ExtractionAgent",
                "messages": json.dumps([], ensure_ascii=False),
                "llm_model": "m1",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "usage_payload": json.dumps({}, ensure_ascii=False),
                "created_at": now,
            },
        )
        db.insert(
            "agent_traces",
            {
                "trace_id": "trc-test-2",
                "agent_name": "FactCheckAgent",
                "messages": json.dumps([], ensure_ascii=False),
                "llm_model": "m1",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "usage_payload": json.dumps({}, ensure_ascii=False),
                "created_at": now,
            },
        )

        response = client.post(
            "/api/v1/agent-traces/list",
            json={"offset": 0, "limit": 10, "agent_name": "ExtractionAgent"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["agent_name"] == "ExtractionAgent"

    def test_list_filters_by_caller(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        now = datetime.now()
        db.insert(
            "agent_traces",
            {
                "trace_id": "trc-test-1",
                "agent_name": "A",
                "messages": json.dumps([], ensure_ascii=False),
                "llm_model": "m1",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "usage_payload": json.dumps({}, ensure_ascii=False),
                "caller": "api",
                "created_at": now,
            },
        )
        db.insert(
            "agent_traces",
            {
                "trace_id": "trc-test-2",
                "agent_name": "A",
                "messages": json.dumps([], ensure_ascii=False),
                "llm_model": "m1",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "usage_payload": json.dumps({}, ensure_ascii=False),
                "caller": "data_process",
                "created_at": now,
            },
        )

        response = client.post(
            "/api/v1/agent-traces/list",
            json={"offset": 0, "limit": 10, "caller": "api"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["items"][0]["trace_id"] == "trc-test-1"

    def test_list_pagination(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        now = datetime.now()
        for i in range(5):
            db.insert(
                "agent_traces",
                {
                    "trace_id": f"t-{i}",
                    "agent_name": "A",
                    "messages": json.dumps([], ensure_ascii=False),
                    "llm_model": "m1",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "usage_payload": json.dumps({}, ensure_ascii=False),
                    "created_at": now,
                },
            )

        response = client.post(
            "/api/v1/agent-traces/list",
            json={"offset": 0, "limit": 2},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 5
        assert len(payload["items"]) == 2

        response = client.post(
            "/api/v1/agent-traces/list",
            json={"offset": 2, "limit": 2},
        )
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["items"]) == 2

        response = client.post(
            "/api/v1/agent-traces/list",
            json={"offset": 4, "limit": 2},
        )
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["items"]) == 1

    def test_list_sort_by_total_tokens(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        now = datetime.now()
        db.insert(
            "agent_traces",
            {
                "trace_id": "t-low",
                "agent_name": "A",
                "messages": json.dumps([], ensure_ascii=False),
                "llm_model": "m1",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 10,
                "usage_payload": json.dumps({}, ensure_ascii=False),
                "created_at": now,
            },
        )
        db.insert(
            "agent_traces",
            {
                "trace_id": "t-high",
                "agent_name": "A",
                "messages": json.dumps([], ensure_ascii=False),
                "llm_model": "m1",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 100,
                "usage_payload": json.dumps({}, ensure_ascii=False),
                "created_at": now,
            },
        )

        response = client.post(
            "/api/v1/agent-traces/list",
            json={
                "offset": 0,
                "limit": 10,
                "sort_by": "total_tokens",
                "sort_order": "desc",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        tokens = [item["total_tokens"] for item in payload["items"]]
        assert tokens == [100, 10]
