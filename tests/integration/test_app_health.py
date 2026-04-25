"""Application-level integration tests."""

from fastapi.testclient import TestClient

from paper_plane_x_backend.version import get_app_version


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app_name"]


def test_openapi_version_uses_repo_version(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["info"]["version"] == get_app_version()
