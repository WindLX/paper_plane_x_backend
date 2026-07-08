"""Removed conversation API tests."""

from fastapi.testclient import TestClient


def test_conversation_rest_api_is_removed(client: TestClient) -> None:
    response = client.get("/api/v1/conversations")

    assert response.status_code == 404


def test_conversation_websocket_path_is_removed(client: TestClient) -> None:
    response = client.get("/api/v1/ws/conversations/cnv-test")

    assert response.status_code == 404
