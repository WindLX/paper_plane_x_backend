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
                "trace_id": "t-1",
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
                "trace_id": "t-2",
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
            json={"trace_ids": ["t-2", "t-1", "missing", "t-2"]},
        )
        assert response.status_code == 200
        payload = response.json()
        items = payload["items"]
        assert [item["trace_id"] for item in items] == ["t-2", "t-1"]
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
