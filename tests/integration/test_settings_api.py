"""Settings API integration tests."""

from fastapi.testclient import TestClient

from paper_plane_x_backend.services.app_settings import get_app_settings_repo


class TestSettingsProviders:
    """Provider CRUD API tests."""

    def _clear_providers(self) -> None:
        repo = get_app_settings_repo()
        for p in list(repo.list_providers()):
            repo.delete_provider(p.name)

    def test_list_providers_empty(self, client: TestClient) -> None:
        self._clear_providers()
        response = client.get("/api/v1/settings/providers")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []

    def test_create_and_get_provider(self, client: TestClient) -> None:
        self._clear_providers()
        create_resp = client.post(
            "/api/v1/settings/providers",
            json={
                "name": "test-provider",
                "model": "gpt-4o",
                "base_url": "http://localhost:8000/v1",
                "api_key": "sk-test",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["name"] == "test-provider"
        assert created["model"] == "gpt-4o"
        # api_key 永远不回传，只用布尔标识是否已配置
        assert "api_key" not in created
        assert created["has_api_key"] is True

        get_resp = client.get("/api/v1/settings/providers/test-provider")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "test-provider"

    def test_api_key_never_returned(self, client: TestClient) -> None:
        self._clear_providers()
        client.post(
            "/api/v1/settings/providers",
            json={"name": "secret", "model": "gpt-4o", "api_key": "sk-secret"},
        )

        # 单个、列表、全量接口均不得包含 api_key 明文
        single = client.get("/api/v1/settings/providers/secret").json()
        assert "api_key" not in single
        assert single["has_api_key"] is True

        listed = client.get("/api/v1/settings/providers").json()["items"]
        secret = next(p for p in listed if p["name"] == "secret")
        assert "api_key" not in secret

        full = client.get("/api/v1/settings").json()
        full_secret = next(p for p in full["providers"] if p["name"] == "secret")
        assert "api_key" not in full_secret

    def test_update_without_api_key_preserves_existing(
        self, client: TestClient
    ) -> None:
        self._clear_providers()
        client.post(
            "/api/v1/settings/providers",
            json={"name": "keep-key", "model": "gpt-4o", "api_key": "sk-keep"},
        )

        # 不传 api_key 的更新不应清空已有 key
        resp = client.put(
            "/api/v1/settings/providers/keep-key",
            json={"model": "gpt-4-turbo"},
        )
        assert resp.status_code == 200
        assert resp.json()["has_api_key"] is True

        repo = get_app_settings_repo()
        provider = repo.get_provider("keep-key")
        assert provider is not None
        assert provider.api_key == "sk-keep"

    def test_create_provider_conflict(self, client: TestClient) -> None:
        self._clear_providers()
        payload = {"name": "dup", "model": "gpt-4o"}
        client.post("/api/v1/settings/providers", json=payload)

        resp = client.post("/api/v1/settings/providers", json=payload)
        assert resp.status_code == 409

    def test_update_provider(self, client: TestClient) -> None:
        self._clear_providers()
        client.post(
            "/api/v1/settings/providers",
            json={"name": "to-update", "model": "gpt-4o"},
        )

        resp = client.put(
            "/api/v1/settings/providers/to-update",
            json={"model": "gpt-4-turbo"},
        )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["model"] == "gpt-4-turbo"
        assert updated["name"] == "to-update"

    def test_update_provider_not_found(self, client: TestClient) -> None:
        resp = client.put(
            "/api/v1/settings/providers/missing",
            json={"model": "gpt-4"},
        )
        assert resp.status_code == 404

    def test_delete_provider(self, client: TestClient) -> None:
        self._clear_providers()
        client.post(
            "/api/v1/settings/providers",
            json={"name": "to-delete", "model": "gpt-4o"},
        )

        resp = client.delete("/api/v1/settings/providers/to-delete")
        assert resp.status_code == 204

        get_resp = client.get("/api/v1/settings/providers/to-delete")
        assert get_resp.status_code == 404

    def test_get_provider_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/v1/settings/providers/nonexistent")
        assert resp.status_code == 404


class TestSettingsAgentLLM:
    """Agent LLM config API tests."""

    def _clear_agents(self) -> None:
        repo = get_app_settings_repo()
        for name in (
            "extraction",
            "analysis",
            "fact_check",
            "deep_diver",
            "query_builder",
            "global_finder",
            "researcher",
        ):
            repo.update_agent_llm(name, {"provider_name": "default"})

    def test_list_agent_llm(self, client: TestClient) -> None:
        resp = client.get("/api/v1/settings/agent_llm")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 7
        names = {item["agent_name"] for item in data["items"]}
        assert "extraction" in names
        assert "analysis" in names

    def test_get_agent_llm(self, client: TestClient) -> None:
        resp = client.get("/api/v1/settings/agent_llm/extraction")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "extraction"
        assert "provider_name" in data

    def test_get_agent_llm_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/v1/settings/agent_llm/unknown_agent")
        assert resp.status_code == 404

    def test_update_agent_llm(self, client: TestClient) -> None:
        self._clear_agents()
        # 先创建 provider 才能引用
        client.post(
            "/api/v1/settings/providers",
            json={"name": "agent-test-provider", "model": "gpt-4o"},
        )

        resp = client.put(
            "/api/v1/settings/agent_llm/extraction",
            json={
                "provider_name": "agent-test-provider",
                "temperature": 0.2,
                "max_tokens": 4096,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "extraction"
        assert data["provider_name"] == "agent-test-provider"
        assert data["temperature"] == 0.2
        assert data["effective_model"] == "gpt-4o"

    def test_update_agent_llm_unknown_provider(self, client: TestClient) -> None:
        self._clear_agents()
        resp = client.put(
            "/api/v1/settings/agent_llm/extraction",
            json={"provider_name": "nonexistent-provider"},
        )
        assert resp.status_code == 422

    def test_update_agent_llm_not_found(self, client: TestClient) -> None:
        resp = client.put(
            "/api/v1/settings/agent_llm/unknown_agent",
            json={"provider_name": "default"},
        )
        assert resp.status_code == 404


class TestSettingsSections:
    """Settings section (mineru / data_process / librarian) API tests."""

    def test_get_full_app_settings(self, client: TestClient) -> None:
        resp = client.get("/api/v1/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "mineru" in data
        assert "data_process" in data
        assert "librarian" in data
        assert "agent_llm" in data
        assert "providers" in data
        assert "llm" not in data

    def test_get_and_update_mineru(self, client: TestClient) -> None:
        resp = client.put(
            "/api/v1/settings/mineru",
            json={"base_url": "http://mineru-test:7860"},
        )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["base_url"] == "http://mineru-test:7860"

    def test_get_and_update_data_process(self, client: TestClient) -> None:
        resp = client.put(
            "/api/v1/settings/data-process",
            json={"worker_count": 10, "max_retries": 5},
        )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["worker_count"] == 10
        assert updated["max_retries"] == 5

    def test_get_and_update_librarian(self, client: TestClient) -> None:
        resp = client.put(
            "/api/v1/settings/librarian",
            json={"top_tags_limit": 15},
        )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["top_tags_limit"] == 15

    def test_persistence_across_requests(self, client: TestClient) -> None:
        client.put(
            "/api/v1/settings/mineru",
            json={"base_url": "http://mineru-persist:7860"},
        )

        resp = client.get("/api/v1/settings/mineru")
        assert resp.status_code == 200
        assert resp.json()["base_url"] == "http://mineru-persist:7860"

        # 通过全量接口也可见
        full_resp = client.get("/api/v1/settings")
        assert full_resp.json()["mineru"]["base_url"] == "http://mineru-persist:7860"
