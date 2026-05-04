"""Librarian API 集成测试。"""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from paper_plane_x_backend.services import Database


def _insert_paper(db: Database, paper_id: str) -> None:
    now = datetime.now()
    db.insert(
        "papers",
        {
            "paper_id": paper_id,
            "title": f"Title {paper_id}",
            "authors": json.dumps(["Alice", "Bob"], ensure_ascii=False),
            "custom_meta": json.dumps(
                {"source": {"name": "manual", "version": 2}, "tags": ["x", "y"]},
                ensure_ascii=False,
            ),
            "quick_scan": json.dumps(
                {"verdict": "include", "reason": "fit"}, ensure_ascii=False
            ),
            "synthesis_data": json.dumps(
                {"review_summary": f"summary-{paper_id}"}, ensure_ascii=False
            ),
            "md_content": "",
            "images_paths": json.dumps([], ensure_ascii=False),
            "extraction_status": "COMPLETED",
            "extraction_fact_check_status": "PASSED",
            "analysis_fact_check_status": "PASSED",
            "extraction_retry_count": 0,
            "analysis_retry_count": 0,
            "created_at": now,
            "updated_at": now,
        },
    )


class TestLibrarianAPI:
    """Librarian Layer1 API 测试。"""

    def test_search_endpoint_filters_by_query_expr(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-search-1")
        _insert_paper(db, "paper-search-2")
        db.update(
            table="papers",
            data={
                "year": 2024,
                "quick_scan": json.dumps(
                    {"verdict": "推荐精读", "reason": "fit"},
                    ensure_ascii=False,
                ),
            },
            where="paper_id = ?",
            where_params=("paper-search-1",),
        )
        db.update(
            table="papers",
            data={
                "year": 2021,
                "quick_scan": json.dumps(
                    {"verdict": "跳过", "reason": "low fit"},
                    ensure_ascii=False,
                ),
            },
            where="paper_id = ?",
            where_params=("paper-search-2",),
        )

        response = client.post(
            "/api/v1/librarian/search",
            json={
                "query_expr": "(meta.year BETWEEN [2023, 2025]) AND (quick_scan.verdict CONTAINS 推荐)",
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["paper_ids"] == ["paper-search-1"]

    def test_search_endpoint_auto_filters_unqualified_status(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-status-pass")
        _insert_paper(db, "paper-status-fail")
        db.update(
            table="papers",
            data={
                "md_content": "Lyapunov design",
            },
            where="paper_id = ?",
            where_params=("paper-status-pass",),
        )
        db.update(
            table="papers",
            data={
                "md_content": "Lyapunov design",
                "extraction_status": "FAILED",
            },
            where="paper_id = ?",
            where_params=("paper-status-fail",),
        )

        response = client.post(
            "/api/v1/librarian/search",
            json={
                "query_expr": "(md_content CONTAINS lyapunov)",
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["paper_ids"] == ["paper-status-pass"]

    def test_search_endpoint_supports_nested_query_expr(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-search-n1")
        _insert_paper(db, "paper-search-n2")
        db.update(
            table="papers",
            data={
                "year": 2024,
                "quick_scan": json.dumps({"verdict": "推荐精读"}, ensure_ascii=False),
            },
            where="paper_id = ?",
            where_params=("paper-search-n1",),
        )
        db.update(
            table="papers",
            data={
                "year": 2021,
                "quick_scan": json.dumps({"verdict": "跳过"}, ensure_ascii=False),
            },
            where="paper_id = ?",
            where_params=("paper-search-n2",),
        )

        response = client.post(
            "/api/v1/librarian/search",
            json={
                "query_expr": "(meta.year BETWEEN [2025, 2030]) OR ((quick_scan.verdict CONTAINS 推荐) AND (meta.year BETWEEN [2023, 2024]))",
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["paper_ids"] == ["paper-search-n1"]

    def test_search_returns_422_for_invalid_field(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-search-invalid")

        response = client.post(
            "/api/v1/librarian/search",
            json={
                "query_expr": "(unknown_field CONTAINS x)",
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 422
        payload = response.json()
        assert payload["detail"]["code"] == "invalid_field"


class TestLibrarianQueryBuilderAPI:
    """Librarian Query Builder API 测试。"""

    def test_query_builder_returns_expr(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证 query-builder 返回生成的 query_expr 和 explanation。"""
        from unittest.mock import AsyncMock

        from paper_plane_x_backend.agents.query_builder import QueryBuilderAgent
        from paper_plane_x_backend.schemas.agent_io.librarian import (
            QueryBuilderAgentOutput,
        )

        expected = QueryBuilderAgentOutput(
            query_expr="(meta.title CONTAINS transformer) AND (meta.year BETWEEN [2021, 2025])",
            explanation="查询标题包含 transformer 且年份在 2021-2025 之间的论文。",
        )
        monkeypatch.setattr(
            QueryBuilderAgent,
            "run",
            AsyncMock(return_value=expected),
        )
        monkeypatch.setattr(
            QueryBuilderAgent,
            "_build_system_prompt",
            lambda self: "system prompt",
        )

        response = client.post(
            "/api/v1/librarian/query-builder",
            json={
                "query": "我想查询最近五年关于 transformer 的论文",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["query_expr"] == expected.query_expr
        assert payload["explanation"] == expected.explanation

    def test_query_builder_with_project_context(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证 query-builder 支持 project_context。"""
        from unittest.mock import AsyncMock

        from paper_plane_x_backend.agents.query_builder import QueryBuilderAgent
        from paper_plane_x_backend.schemas.agent_io.librarian import (
            QueryBuilderAgentOutput,
        )

        expected = QueryBuilderAgentOutput(
            query_expr='(meta.title CONTAINS "GPT") AND (meta.publication CONTAINS NeurIPS)',
            explanation="查询标题包含 GPT 且发表在 NeurIPS 的论文。",
        )
        monkeypatch.setattr(
            QueryBuilderAgent,
            "run",
            AsyncMock(return_value=expected),
        )
        monkeypatch.setattr(
            QueryBuilderAgent,
            "_build_system_prompt",
            lambda self: "system prompt",
        )

        response = client.post(
            "/api/v1/librarian/query-builder",
            json={
                "query": "NeurIPS 上关于 GPT 的论文",
                "project_context": "NLP 研究方向",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["query_expr"] == expected.query_expr

    def test_query_builder_rejects_invalid_generated_expr(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证 query-builder 对 LLM 生成的不合法表达式返回 422。"""
        from unittest.mock import AsyncMock

        from paper_plane_x_backend.agents.query_builder import QueryBuilderAgent
        from paper_plane_x_backend.schemas.agent_io.librarian import (
            QueryBuilderAgentOutput,
        )

        expected = QueryBuilderAgentOutput(
            query_expr="invalid expr (",
            explanation="无效的查询",
        )
        monkeypatch.setattr(
            QueryBuilderAgent,
            "run",
            AsyncMock(return_value=expected),
        )
        monkeypatch.setattr(
            QueryBuilderAgent,
            "_build_system_prompt",
            lambda self: "system prompt",
        )

        response = client.post(
            "/api/v1/librarian/query-builder",
            json={
                "query": "随便输入",
            },
        )

        assert response.status_code == 422
        payload = response.json()
        assert (
            "invalid" in payload["detail"].lower()
            or "Generated invalid" in payload["detail"]
        )


class TestLibrarianGlobalFinderAPI:
    """Librarian Global Finder API 测试。"""

    def test_global_finder_returns_existing_summary(
        self, client: TestClient, db: Database
    ) -> None:
        """验证 global-finder 在 agent_summary 已存在时直接返回。"""
        from paper_plane_x_backend.models import Project
        from paper_plane_x_backend.services.project.repository import (
            ProjectRepository,
        )

        now = datetime.now()
        project = Project(
            project_id="proj-gf-1",
            name="Global Finder Test",
            description=None,
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
        db.insert("projects", project.to_db_dict())

        _insert_paper(db, "paper-gf-1")
        db.update(
            table="papers",
            data={
                "year": 2024,
                "quick_scan": json.dumps(
                    {
                        "verdict": "推荐精读",
                        "reason": "fit",
                        "tags": ["tag1"],
                        "quick_summary": "summary",
                    },
                    ensure_ascii=False,
                ),
            },
            where="paper_id = ?",
            where_params=("paper-gf-1",),
        )
        db.execute(
            "INSERT INTO paper_projects (paper_id, project_id) VALUES (?, ?)",
            ("paper-gf-1", "proj-gf-1"),
        )

        ProjectRepository(db).set_agent_summary("proj-gf-1", "existing summary")

        response = client.post(
            "/api/v1/librarian/global-finder",
            json={"project_id": "proj-gf-1"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["project_id"] == "proj-gf-1"
        assert payload["agent_summary"] == "existing summary"
        assert len(payload["papers"]) == 1
        assert payload["papers"][0]["paper_id"] == "paper-gf-1"
        assert payload["stats"]["paper_count"] == 1
        assert "year_distribution" in payload["stats"]
        assert payload["stats"]["year_range"] == "2024-2024"

    def test_global_finder_generates_summary_when_missing(
        self,
        client: TestClient,
        db: Database,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证 global-finder 在 agent_summary 缺失时触发 Agent 生成。"""
        from unittest.mock import AsyncMock

        from paper_plane_x_backend.agents.global_finder import GlobalFinderAgent
        from paper_plane_x_backend.models import Project
        from paper_plane_x_backend.schemas.agent_io.librarian import (
            GlobalFinderAgentOutput,
        )
        from paper_plane_x_backend.services.project.repository import (
            ProjectRepository,
        )

        now = datetime.now()
        project = Project(
            project_id="proj-gf-2",
            name="Global Finder Test 2",
            description=None,
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
        db.insert("projects", project.to_db_dict())

        _insert_paper(db, "paper-gf-2")
        db.update(
            table="papers",
            data={
                "year": 2023,
                "quick_scan": json.dumps(
                    {
                        "verdict": "仅作参考",
                        "reason": "fit",
                        "tags": ["tag2"],
                        "quick_summary": "summary2",
                    },
                    ensure_ascii=False,
                ),
            },
            where="paper_id = ?",
            where_params=("paper-gf-2",),
        )
        db.execute(
            "INSERT INTO paper_projects (paper_id, project_id) VALUES (?, ?)",
            ("paper-gf-2", "proj-gf-2"),
        )

        expected = GlobalFinderAgentOutput(agent_summary="generated summary")
        monkeypatch.setattr(
            GlobalFinderAgent,
            "run",
            AsyncMock(return_value=expected),
        )
        monkeypatch.setattr(
            GlobalFinderAgent,
            "_build_system_prompt",
            lambda self: "system prompt",
        )

        response = client.post(
            "/api/v1/librarian/global-finder",
            json={"project_id": "proj-gf-2"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["agent_summary"] == "generated summary"

        repo = ProjectRepository(db)
        assert repo.get_agent_summary("proj-gf-2") == "generated summary"
