"""Export HTTP contract against a real worker and temporary artifacts."""

import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from paper_plane_x_backend.api.dependencies import get_database
from paper_plane_x_backend.api.routers.project_exports import router
from paper_plane_x_backend.schemas.api.project import ProjectExportRequest
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.orchestrators.project import ProjectOrchestrator
from paper_plane_x_backend.services.project.export_jobs import ProjectExportManager


@pytest.fixture
def export_client(db: Database, tmp_path: Path):
    manager = ProjectExportManager(db, tmp_path / "exports")
    project = ProjectOrchestrator(db).create_project(
        name="Synthetic export", description=None
    )
    ProjectOrchestrator(db).file_manager.write_file(
        project.project_id, "/draft.md", "# Synthetic"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.project_exports = manager
        await manager.start()
        try:
            yield
        finally:
            await manager.stop()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_database] = lambda: db
    with TestClient(app) as client:
        yield client, project.project_id, manager


def test_create_progress_download_restore_and_expiry(export_client):
    client, project_id, manager = export_client
    base = f"/api/v1/projects/{project_id}/exports"
    created = client.post(
        base, json={"fields": ["title"], "include_sandbox_files": True}
    )
    assert created.status_code == 202
    export_id = created.json()["export_id"]
    deadline = time.monotonic() + 5
    while True:
        response = client.get(f"{base}/{export_id}")
        assert response.status_code == 200
        state = response.json()
        if state["status"] not in ("queued", "running"):
            break
        assert time.monotonic() < deadline, state
        time.sleep(0.01)
    assert state["status"] == "completed", state
    assert state["processed_files"] == state["total_files"] == 2
    first = client.get(f"{base}/{export_id}/download")
    second = client.get(f"{base}/{export_id}/download")
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert first.headers["content-type"] == "application/zip"
    assert int(first.headers["content-length"]) == len(first.content)
    assert "attachment" in first.headers["content-disposition"]
    assert client.get(base).json()["items"][0]["export_id"] == export_id
    assert "artifact_path" not in state
    manager.db.execute(
        "UPDATE project_exports SET expires_at=? WHERE export_id=?",
        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), export_id),
    )
    assert client.get(f"{base}/{export_id}/download").status_code == 410
    assert client.get(f"{base}/{export_id}").json()["status"] == "expired"


def test_cancel_queued_job_and_project_scoping(export_client):
    client, project_id, manager = export_client
    job = manager.repo.create(project_id, ProjectExportRequest(fields=["title"]))
    base = f"/api/v1/projects/{project_id}/exports/{job.export_id}"
    assert client.get(f"{base}/download").status_code == 409
    assert client.post(f"{base}/cancel").json()["status"] == "canceled"
    assert client.post(f"{base}/cancel").json()["status"] == "canceled"
    other = ProjectOrchestrator(manager.db).create_project(
        name="Other", description=None
    )
    assert (
        client.get(
            f"/api/v1/projects/{other.project_id}/exports/{job.export_id}"
        ).status_code
        == 404
    )
    assert client.get("/api/v1/projects/nonexistent/exports").status_code == 404
