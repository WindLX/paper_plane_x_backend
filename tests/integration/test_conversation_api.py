"""Conversation API 集成测试."""

from fastapi.testclient import TestClient

from paper_plane_x_backend.services import Database


class TestConversationAPI:
    """Conversation REST API 测试类."""

    def test_create_conversation(self, client: TestClient) -> None:
        """测试创建会话."""
        # 先创建项目
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Test Project"},
        )
        project_id = project_resp.json()["project_id"]

        response = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Test Conversation"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == project_id
        assert data["title"] == "Test Conversation"
        assert data["conversation_id"].startswith("cnv-")

    def test_create_conversation_without_title(self, client: TestClient) -> None:
        """测试创建会话（无标题时使用默认）."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Test Project 2"},
        )
        project_id = project_resp.json()["project_id"]

        response = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "New Conversation"

    def test_list_conversations(self, client: TestClient) -> None:
        """测试列出项目下的会话."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "List Test"},
        )
        project_id = project_resp.json()["project_id"]

        client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "First"},
        )
        client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Second"},
        )

        response = client.get(f"/api/v1/conversations?project_id={project_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_list_conversations_missing_project(self, client: TestClient) -> None:
        """测试列出不存在项目的会话返回空列表."""
        response = client.get("/api/v1/conversations?project_id=non-existent")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_get_conversation(self, client: TestClient) -> None:
        """测试获取会话详情."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Get Test"},
        )
        project_id = project_resp.json()["project_id"]

        create_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Get Me"},
        )
        conversation_id = create_resp.json()["conversation_id"]

        response = client.get(f"/api/v1/conversations/{conversation_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == conversation_id
        assert data["title"] == "Get Me"

    def test_get_conversation_not_found(self, client: TestClient) -> None:
        """测试获取不存在的会话."""
        response = client.get("/api/v1/conversations/non-existent")
        assert response.status_code == 404

    def test_update_conversation_title(self, client: TestClient) -> None:
        """测试更新会话标题."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Update Test"},
        )
        project_id = project_resp.json()["project_id"]

        create_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Old Title"},
        )
        conversation_id = create_resp.json()["conversation_id"]

        response = client.patch(
            f"/api/v1/conversations/{conversation_id}",
            json={"title": "New Title"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "New Title"

    def test_update_conversation_not_found(self, client: TestClient) -> None:
        """测试更新不存在的会话."""
        response = client.patch(
            "/api/v1/conversations/non-existent",
            json={"title": "New Title"},
        )
        assert response.status_code == 404

    def test_delete_conversation(self, client: TestClient) -> None:
        """测试删除会话."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Delete Test"},
        )
        project_id = project_resp.json()["project_id"]

        create_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Delete Me"},
        )
        conversation_id = create_resp.json()["conversation_id"]

        response = client.delete(f"/api/v1/conversations/{conversation_id}")
        assert response.status_code == 204

        # 确认已删除
        get_resp = client.get(f"/api/v1/conversations/{conversation_id}")
        assert get_resp.status_code == 404

    def test_delete_conversation_not_found(self, client: TestClient) -> None:
        """测试删除不存在的会话."""
        response = client.delete("/api/v1/conversations/non-existent")
        assert response.status_code == 404

    def test_fork_conversation(self, client: TestClient) -> None:
        """测试 Fork 会话."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Fork Test"},
        )
        project_id = project_resp.json()["project_id"]

        create_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Source"},
        )
        source_id = create_resp.json()["conversation_id"]

        # 添加消息
        client.post(
            f"/api/v1/conversations/{source_id}/messages",
            json={"role": "user", "content": "Hello"},
        )

        response = client.post(
            f"/api/v1/conversations/{source_id}/fork",
            json={"title": "Forked"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Forked"
        assert data["forked_from_conversation_id"] == source_id
        assert data["conversation_id"].startswith("cnv-")

        # 确认消息也被复制
        messages_resp = client.get(
            f"/api/v1/conversations/{data['conversation_id']}/messages"
        )
        assert messages_resp.status_code == 200
        messages = messages_resp.json()
        assert len(messages) == 1
        assert messages[0]["content"] == "Hello"

    def test_fork_conversation_not_found(self, client: TestClient) -> None:
        """测试 Fork 不存在的会话."""
        response = client.post(
            "/api/v1/conversations/non-existent/fork",
            json={},
        )
        assert response.status_code == 404

    def test_create_and_list_messages(self, client: TestClient) -> None:
        """测试创建和列出消息."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Message Test"},
        )
        project_id = project_resp.json()["project_id"]

        create_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Messages"},
        )
        conversation_id = create_resp.json()["conversation_id"]

        # 创建消息
        msg_resp = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"role": "system", "content": "System prompt"},
        )
        assert msg_resp.status_code == 201
        msg_data = msg_resp.json()
        assert msg_data["role"] == "system"
        assert msg_data["content"] == "System prompt"
        assert msg_data["message_id"].startswith("msg-")

        # 列出消息
        list_resp = client.get(f"/api/v1/conversations/{conversation_id}/messages")
        assert list_resp.status_code == 200
        messages = list_resp.json()
        assert len(messages) == 1

    def test_update_message(self, client: TestClient) -> None:
        """测试更新消息（编辑后截断）."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Update Msg Test"},
        )
        project_id = project_resp.json()["project_id"]

        create_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Update Msg"},
        )
        conversation_id = create_resp.json()["conversation_id"]

        # 创建两条消息
        msg1_resp = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"role": "user", "content": "First"},
        )
        msg1_id = msg1_resp.json()["message_id"]

        client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"role": "assistant", "content": "Second"},
        )

        # 更新第一条消息
        response = client.patch(
            f"/api/v1/conversations/{conversation_id}/messages/{msg1_id}",
            json={"content": "Updated First"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Updated First"

        # 确认第二条消息被截断删除
        list_resp = client.get(f"/api/v1/conversations/{conversation_id}/messages")
        messages = list_resp.json()
        assert len(messages) == 1
        assert messages[0]["content"] == "Updated First"

    def test_delete_message(self, client: TestClient) -> None:
        """测试删除消息."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Delete Msg Test"},
        )
        project_id = project_resp.json()["project_id"]

        create_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Delete Msg"},
        )
        conversation_id = create_resp.json()["conversation_id"]

        msg_resp = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"role": "user", "content": "Delete me"},
        )
        msg_id = msg_resp.json()["message_id"]

        response = client.delete(
            f"/api/v1/conversations/{conversation_id}/messages/{msg_id}"
        )
        assert response.status_code == 204

        # 确认已删除
        list_resp = client.get(f"/api/v1/conversations/{conversation_id}/messages")
        messages = list_resp.json()
        assert len(messages) == 0

    def test_delete_message_not_found(self, client: TestClient) -> None:
        """测试删除不存在的消息."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Delete Msg NF Test"},
        )
        project_id = project_resp.json()["project_id"]

        create_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Delete Msg NF"},
        )
        conversation_id = create_resp.json()["conversation_id"]

        response = client.delete(
            f"/api/v1/conversations/{conversation_id}/messages/non-existent"
        )
        assert response.status_code == 404

    def test_cascade_delete(self, client: TestClient, db: Database) -> None:
        """测试删除项目时级联删除会话和消息."""
        project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Cascade Test"},
        )
        project_id = project_resp.json()["project_id"]

        create_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Cascade"},
        )
        conversation_id = create_resp.json()["conversation_id"]

        client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"role": "user", "content": "Hello"},
        )

        # 删除项目
        client.delete(f"/api/v1/projects/{project_id}")

        # 确认会话和消息都被级联删除
        conv_resp = client.get(f"/api/v1/conversations/{conversation_id}")
        assert conv_resp.status_code == 404
