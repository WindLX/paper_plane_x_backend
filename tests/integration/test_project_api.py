"""Project API 测试."""

import io
import json
import zipfile
from datetime import datetime

from fastapi.testclient import TestClient

from paper_plane_x_backend.services import Database


def _insert_linked_paper(
    db: Database, project_id: str, payload: dict[str, object]
) -> None:
    data = dict(payload)
    paper_id = data["paper_id"]
    db.insert("papers", data)
    db.execute(
        """
        INSERT INTO paper_projects (paper_id, project_id)
        VALUES (?, ?)
        """,
        (paper_id, project_id),
    )


class TestProjectAPI:
    """Project API 测试类."""

    def test_create_project(self, client: TestClient) -> None:
        """测试创建项目."""
        response = client.post(
            "/api/v1/projects",
            json={"name": "Test Project", "description": "Test Description"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Project"
        assert data["description"] == "Test Description"
        assert "project_id" in data

    def test_create_project_without_description(self, client: TestClient) -> None:
        """测试创建项目（无描述）."""
        response = client.post(
            "/api/v1/projects",
            json={"name": "Test Project 2"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Project 2"
        assert data["description"] is None

    def test_create_project_validation_error(self, client: TestClient) -> None:
        """测试创建项目参数验证失败."""
        # 空名称
        response = client.post(
            "/api/v1/projects",
            json={"name": ""},
        )
        assert response.status_code == 422

    def test_get_project(self, client: TestClient) -> None:
        """测试获取项目详情."""
        # 先创建项目
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Get Test", "description": "Get Description"},
        )
        project_id = create_response.json()["project_id"]

        # 获取项目
        response = client.get(f"/api/v1/projects/{project_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == project_id
        assert data["name"] == "Get Test"

    def test_get_project_not_found(self, client: TestClient) -> None:
        """测试获取不存在的项目."""
        response = client.get("/api/v1/projects/non-existent-id")
        assert response.status_code == 404

    def test_list_projects(self, client: TestClient) -> None:
        """测试列出项目."""
        # 创建多个项目
        for i in range(3):
            client.post(
                "/api/v1/projects",
                json={"name": f"List Test {i}", "description": f"Desc {i}"},
            )

        # 获取列表
        response = client.get("/api/v1/projects?offset=0&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["offset"] == 0
        assert data["limit"] == 2
        assert len(data["items"]) <= 2

    def test_update_project(self, client: TestClient) -> None:
        """测试更新项目."""
        # 先创建项目
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Update Test", "description": "Original Desc"},
        )
        project_id = create_response.json()["project_id"]

        # 更新项目
        response = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"name": "Updated Name", "description": "Updated Desc"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["description"] == "Updated Desc"

    def test_update_project_partial(self, client: TestClient) -> None:
        """测试部分更新项目."""
        # 先创建项目
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Partial Update Test", "description": "Keep Desc"},
        )
        project_id = create_response.json()["project_id"]

        # 只更新名称
        response = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"name": "Only Name Updated"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Only Name Updated"
        assert data["description"] == "Keep Desc"

    def test_update_project_not_found(self, client: TestClient) -> None:
        """测试更新不存在的项目."""
        response = client.patch(
            "/api/v1/projects/non-existent-id",
            json={"name": "New Name"},
        )
        assert response.status_code == 404

    def test_delete_project(self, client: TestClient) -> None:
        """测试删除项目."""
        # 先创建项目
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Delete Test"},
        )
        project_id = create_response.json()["project_id"]

        # 删除项目
        response = client.delete(f"/api/v1/projects/{project_id}")
        assert response.status_code == 200
        data = response.json()
        assert "deleted" in data["message"]

        # 确认已删除
        get_response = client.get(f"/api/v1/projects/{project_id}")
        assert get_response.status_code == 404

    def test_delete_project_also_cleans_paper_links(
        self, client: TestClient, db: Database
    ) -> None:
        """删除 project 时会清理 paper_projects 关联."""
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Delete With Links"},
        )
        project_id = create_response.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-linked-to-delete-project",
                "title": "Linked Paper",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "extraction_retry_count": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        before = db.fetchone(
            "SELECT COUNT(*) AS count FROM paper_projects WHERE project_id = ?",
            (project_id,),
        )
        assert before is not None and before["count"] == 1

        response = client.delete(f"/api/v1/projects/{project_id}")
        assert response.status_code == 200

        after = db.fetchone(
            "SELECT COUNT(*) AS count FROM paper_projects WHERE project_id = ?",
            (project_id,),
        )
        assert after is not None and after["count"] == 0

    def test_delete_project_also_cleans_conversations(
        self, client: TestClient, db: Database
    ) -> None:
        """删除 project 时会级联删除 conversations 和 conversation_messages."""
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Delete With Conversations"},
        )
        project_id = create_response.json()["project_id"]

        # 创建对话
        conv_resp = client.post(
            "/api/v1/conversations",
            json={"project_id": project_id, "title": "Test Chat"},
        )
        conversation_id = conv_resp.json()["conversation_id"]

        # 创建消息
        msg_resp = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"role": "user", "content": "Hello"},
        )
        assert msg_resp.status_code == 201

        # 删除项目前确认数据存在
        conv_before = db.fetchone(
            "SELECT COUNT(*) AS count FROM conversations WHERE project_id = ?",
            (project_id,),
        )
        msg_before = db.fetchone(
            "SELECT COUNT(*) AS count FROM conversation_messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        assert conv_before is not None and conv_before["count"] == 1
        assert msg_before is not None and msg_before["count"] == 1

        # 删除项目
        response = client.delete(f"/api/v1/projects/{project_id}")
        assert response.status_code == 200

        # 确认级联删除生效
        conv_after = db.fetchone(
            "SELECT COUNT(*) AS count FROM conversations WHERE project_id = ?",
            (project_id,),
        )
        msg_after = db.fetchone(
            "SELECT COUNT(*) AS count FROM conversation_messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        assert conv_after is not None and conv_after["count"] == 0
        assert msg_after is not None and msg_after["count"] == 0

    def test_delete_project_not_found(self, client: TestClient) -> None:
        """测试删除不存在的项目."""
        response = client.delete("/api/v1/projects/non-existent-id")
        assert response.status_code == 404

    def test_delete_paper(self, client: TestClient, db: Database) -> None:
        """测试删除单篇论文."""
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Paper Delete Project"},
        )
        project_id = create_response.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-to-delete",
                "title": "A Paper",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "extraction_retry_count": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.delete(
            f"/api/v1/projects/{project_id}/papers/paper-to-delete"
        )
        assert response.status_code == 200
        assert "unlinked" in response.json()["message"]

        detail_response = client.get(
            f"/api/v1/projects/{project_id}/papers/paper-to-delete"
        )
        assert detail_response.status_code == 404

    def test_delete_paper_not_found(self, client: TestClient) -> None:
        """测试删除不存在的论文."""
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Paper Delete 404 Project"},
        )
        project_id = create_response.json()["project_id"]

        response = client.delete(f"/api/v1/projects/{project_id}/papers/non-existent")
        assert response.status_code == 404

    def test_delete_paper_conflict_when_processing(
        self, client: TestClient, db: Database
    ) -> None:
        """测试处理中论文不可删除."""
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Paper Delete Conflict Project"},
        )
        project_id = create_response.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-processing",
                "title": "Processing Paper",
                "authors": json.dumps(["Bob"], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "PROCESSING",
                "extraction_fact_check_status": "PENDING",
                "extraction_retry_count": 0,
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.delete(
            f"/api/v1/projects/{project_id}/papers/paper-processing"
        )
        assert response.status_code == 200

    def test_update_project_writes_operation_log_and_updates_timestamp(
        self, client: TestClient, db: Database
    ) -> None:
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Update Log Project", "description": "before"},
        )
        project_id = create_response.json()["project_id"]
        before = db.fetchone(
            "SELECT updated_at FROM projects WHERE project_id = ?",
            (project_id,),
        )
        assert before is not None

        response = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"name": "after"},
        )
        assert response.status_code == 200

        after = db.fetchone(
            "SELECT updated_at, operation_logs FROM projects WHERE project_id = ?",
            (project_id,),
        )
        assert after is not None
        assert after["updated_at"] >= before["updated_at"]
        logs = json.loads(after["operation_logs"] or "[]")
        assert logs
        assert logs[-1]["operation"] == "update_project"

    def test_link_and_unlink_write_operation_logs_and_touch_updated_at(
        self, client: TestClient, db: Database
    ) -> None:
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Link Log Project"},
        )
        project_id = create_project_resp.json()["project_id"]

        now = datetime.now()
        db.insert(
            "papers",
            {
                "paper_id": "paper-link-log",
                "title": "Link Log Paper",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "PENDING",
                "extraction_fact_check_status": "PENDING",
                "analysis_fact_check_status": "PENDING",
                "created_at": now,
                "updated_at": now,
            },
        )

        before = db.fetchone(
            "SELECT updated_at FROM projects WHERE project_id = ?",
            (project_id,),
        )
        assert before is not None

        link_resp = client.post(f"/api/v1/projects/{project_id}/papers/paper-link-log")
        assert link_resp.status_code == 200

        after_link = db.fetchone(
            "SELECT updated_at, operation_logs FROM projects WHERE project_id = ?",
            (project_id,),
        )
        assert after_link is not None
        assert after_link["updated_at"] >= before["updated_at"]
        logs = json.loads(after_link["operation_logs"] or "[]")
        assert logs[-1]["operation"] == "link_paper"
        assert logs[-1]["detail"]["paper_id"] == "paper-link-log"

        unlink_resp = client.delete(
            f"/api/v1/projects/{project_id}/papers/paper-link-log"
        )
        assert unlink_resp.status_code == 200

        after_unlink = db.fetchone(
            "SELECT updated_at, operation_logs FROM projects WHERE project_id = ?",
            (project_id,),
        )
        assert after_unlink is not None
        logs_after_unlink = json.loads(after_unlink["operation_logs"] or "[]")
        assert logs_after_unlink[-1]["operation"] == "unlink_paper"
        assert logs_after_unlink[-1]["detail"]["paper_id"] == "paper-link-log"

    def test_project_search_delegates_to_librarian_with_project_scope(
        self, client: TestClient, db: Database
    ) -> None:
        """测试 project search 会强制使用路径中的 project_id 进行作用域搜索。"""
        p1_resp = client.post(
            "/api/v1/projects",
            json={"name": "Project Search P1"},
        )
        p2_resp = client.post(
            "/api/v1/projects",
            json={"name": "Project Search P2"},
        )
        p1 = p1_resp.json()["project_id"]
        p2 = p2_resp.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            p1,
            {
                "paper_id": "paper-search-in-p1",
                "title": "P1 Paper",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "year": 2024,
                "md_content": "Lyapunov stability design",
                "images_paths": json.dumps([], ensure_ascii=False),
                "quick_scan": json.dumps({"verdict": "推荐精读"}, ensure_ascii=False),
                "extraction_status": "COMPLETED",
                "extraction_fact_check_status": "PASSED",
                "analysis_fact_check_status": "PASSED",
                "created_at": now,
                "updated_at": now,
            },
        )
        _insert_linked_paper(
            db,
            p2,
            {
                "paper_id": "paper-search-in-p2",
                "title": "P2 Paper",
                "authors": json.dumps(["Bob"], ensure_ascii=False),
                "year": 2024,
                "md_content": "Lyapunov stability design",
                "images_paths": json.dumps([], ensure_ascii=False),
                "quick_scan": json.dumps({"verdict": "推荐精读"}, ensure_ascii=False),
                "extraction_status": "COMPLETED",
                "extraction_fact_check_status": "PASSED",
                "analysis_fact_check_status": "PASSED",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.post(
            f"/api/v1/projects/{p1}/search",
            json={
                "project_id": p2,
                "query_expr": "(md_content CONTAINS lyapunov)",
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["project_id"] == p1
        assert payload["total"] == 1
        assert payload["paper_ids"] == ["paper-search-in-p1"]

    def test_export_project_bundle_strips_citations_and_packs_files(
        self,
        client: TestClient,
        db: Database,
        tmp_path,
    ) -> None:
        create_resp = client.post("/api/v1/projects", json={"name": "Export Project"})
        project_id = create_resp.json()["project_id"]

        paper_dir = tmp_path / "paper-a"
        paper_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = paper_dir / "paper.pdf"
        img_path = paper_dir / "fig1.png"
        pdf_path.write_bytes(b"%PDF-1.4 mock")
        img_path.write_bytes(b"\x89PNG\r\n")

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-export-a",
                "title": "Export A",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "md_content": "",
                "raw_pdf_path": str(pdf_path),
                "images_paths": json.dumps([str(img_path)], ensure_ascii=False),
                "quick_scan": json.dumps(
                    {
                        "verdict": "ok",
                        "citations": [{"quote": "q1"}],
                    },
                    ensure_ascii=False,
                ),
                "synthesis_data": json.dumps(
                    {
                        "summary": "x",
                        "nested": {"citations": [{"quote": "q2"}]},
                    },
                    ensure_ascii=False,
                ),
                "analysis_report": json.dumps(
                    {
                        "findings": "y",
                        "citations": [{"quote": "q3"}],
                        "related_references": [
                            {"title": "Ref A", "reason": "worth following"}
                        ],
                    },
                    ensure_ascii=False,
                ),
                "extraction_status": "COMPLETED",
                "extraction_fact_check_status": "PASSED",
                "analysis_fact_check_status": "PASSED",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.post(
            f"/api/v1/projects/{project_id}/export",
            json={
                "fields": [
                    "paper_id",
                    "title",
                    "raw_pdf_path",
                    "quick_scan",
                    "synthesis_data",
                    "analysis_report",
                ],
                "citations_mode": "strip",
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/zip")

        zf = zipfile.ZipFile(io.BytesIO(response.content))
        names = zf.namelist()
        export_json_path = [
            name for name in names if name.endswith("/project_export.json")
        ]
        assert export_json_path
        packed_pdf = [
            name for name in names if name.endswith("/paper-export-a/paper.pdf")
        ]
        packed_img = [
            name for name in names if name.endswith("/paper-export-a/fig1.png")
        ]
        assert packed_pdf
        assert packed_img

        payload = json.loads(zf.read(export_json_path[0]).decode("utf-8"))
        assert payload["project"]["project_id"] == project_id
        assert payload["paper_count"] == 1
        assert payload["export_options"]["citations_mode"] == "strip"
        exported_paper = payload["papers"][0]
        assert sorted(exported_paper.keys()) == sorted(
            [
                "paper_id",
                "title",
                "raw_pdf_path",
                "quick_scan",
                "synthesis_data",
                "analysis_report",
            ]
        )
        assert "citations" not in json.dumps(
            {
                "quick_scan": exported_paper["quick_scan"],
                "synthesis_data": exported_paper["synthesis_data"],
                "analysis_report": exported_paper["analysis_report"],
            },
            ensure_ascii=False,
        )
        assert exported_paper["analysis_report"]["related_references"] == [
            {"title": "Ref A", "reason": "worth following"}
        ]

    def test_export_project_bundle_keeps_citations_when_requested(
        self,
        client: TestClient,
        db: Database,
    ) -> None:
        create_resp = client.post(
            "/api/v1/projects",
            json={"name": "Export Keep Citations"},
        )
        project_id = create_resp.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-export-b",
                "title": "Export B",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "quick_scan": json.dumps(
                    {"verdict": "ok", "citations": [{"quote": "q1"}]},
                    ensure_ascii=False,
                ),
                "extraction_status": "COMPLETED",
                "extraction_fact_check_status": "PASSED",
                "analysis_fact_check_status": "PASSED",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.post(
            f"/api/v1/projects/{project_id}/export",
            json={
                "fields": ["paper_id", "quick_scan"],
                "citations_mode": "keep",
            },
        )
        assert response.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        export_json_path = [
            name for name in zf.namelist() if name.endswith("/project_export.json")
        ]
        assert export_json_path
        payload = json.loads(zf.read(export_json_path[0]).decode("utf-8"))
        exported_paper = payload["papers"][0]
        assert "citations" in exported_paper["quick_scan"]
