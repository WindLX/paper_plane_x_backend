"""Project workbench API tests (activities + overview)."""

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from paper_plane_x_backend.api.dependencies import get_database
from paper_plane_x_backend.api.routers import project_workbench
from paper_plane_x_backend.models import Project
from paper_plane_x_backend.services import Database
from paper_plane_x_backend.services.project.activity import ProjectActivityStore
from paper_plane_x_backend.services.project.repository import ProjectRepository


def _build_client(db: Database) -> TestClient:
    app = FastAPI()
    app.include_router(project_workbench.router, prefix="/api/v1")
    app.dependency_overrides[get_database] = lambda: db
    return TestClient(app)


def _create_project(db: Database, project_id: str) -> None:
    now = datetime(2025, 1, 1)
    ProjectRepository(db).create(
        Project(
            project_id=project_id,
            name=f"Project {project_id}",
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
    )


class TestProjectWorkbenchAPI:
    def test_activities_returns_404_for_unknown_project(self, db: Database) -> None:
        client = _build_client(db)

        response = client.get("/api/v1/projects/missing/activities")

        assert response.status_code == 404

    def test_overview_returns_404_for_unknown_project(self, db: Database) -> None:
        client = _build_client(db)

        response = client.get("/api/v1/projects/missing/overview")

        assert response.status_code == 404

    def test_list_activities_supports_filters_and_pagination(
        self, db: Database
    ) -> None:
        _create_project(db, "p-api")
        store = ProjectActivityStore(db)
        base = datetime(2026, 5, 1, 8, 0, 0)
        store.record(
            project_id="p-api",
            category="project",
            event_type="project_updated",
            created_at=base,
        )
        store.record(
            project_id="p-api",
            category="task",
            event_type="task_failed",
            status="failed",
            task_id="task-api",
            error="api boom",
            created_at=base + timedelta(minutes=1),
        )
        client = _build_client(db)

        response = client.get("/api/v1/projects/p-api/activities")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 3
        assert payload["offset"] == 0
        assert payload["limit"] == 20
        assert [item["event_type"] for item in payload["items"]] == [
            "task_failed",
            "project_updated",
            "project_created",
        ]

        filtered = client.get(
            "/api/v1/projects/p-api/activities",
            params={"category": "task", "status": "failed", "keyword": "task-api"},
        )
        assert filtered.status_code == 200
        filtered_payload = filtered.json()
        assert filtered_payload["total"] == 1
        item = filtered_payload["items"][0]
        assert item["category"] == "task"
        assert item["task_id"] == "task-api"
        assert item["task_exists"] is False
        assert item["error"] == "api boom"
        assert isinstance(item["created_at"], str)

        paged = client.get(
            "/api/v1/projects/p-api/activities", params={"offset": 1, "limit": 1}
        )
        assert paged.status_code == 200
        assert paged.json()["total"] == 3
        assert len(paged.json()["items"]) == 1

    def test_overview_returns_contract_shape(self, db: Database) -> None:
        _create_project(db, "p-api-overview")
        now = datetime.now()
        db.insert(
            "papers",
            {
                "paper_id": "paper-api",
                "title": "API Paper",
                "authors": "[]",
                "year": 2024,
                "md_content": "body",
                "extraction_status": "COMPLETED",
                "extraction_fact_check_status": "PASSED",
                "analysis_fact_check_status": "PASSED",
                "created_at": now,
                "updated_at": now,
            },
        )
        db.execute(
            "INSERT INTO paper_projects (paper_id, project_id) VALUES (?, ?)",
            ("paper-api", "p-api-overview"),
        )
        client = _build_client(db)

        response = client.get("/api/v1/projects/p-api-overview/overview")

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {
            "project_id",
            "agent_summary",
            "stats",
            "attention_items",
            "recent_papers",
            "recent_files",
            "recent_activities",
            "top_tags",
            "year_distribution",
            "year_range",
            "section_errors",
        }
        assert payload["stats"] == {
            "paper_count": 1,
            "parsed_count": 1,
            "active_task_count": 0,
            "attention_count": 0,
        }
        assert payload["recent_papers"][0]["paper_id"] == "paper-api"
        assert payload["year_range"] == "2024-2024"
        assert "available_count" in payload["year_distribution"]
