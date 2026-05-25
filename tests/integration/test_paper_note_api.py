import json
from datetime import datetime

from fastapi.testclient import TestClient

from paper_plane_x_backend.services import Database


def _insert_note_paper(db: Database, paper_id: str) -> None:
    now = datetime.now()
    db.insert(
        "papers",
        {
            "paper_id": paper_id,
            "title": "Note Paper",
            "authors": json.dumps(["Alice"], ensure_ascii=False),
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


def test_paper_agent_note_crud(client: TestClient, db: Database) -> None:
    _insert_note_paper(db, "paper-note-1")

    write_response = client.put(
        "/api/v1/papers/paper-note-1/agent-note",
        json={"content": "stable note"},
    )
    assert write_response.status_code == 200
    assert write_response.json()["agent_note"] == "stable note"

    get_response = client.get("/api/v1/papers/paper-note-1/agent-note")
    assert get_response.status_code == 200
    assert get_response.json()["agent_note"] == "stable note"

    delete_response = client.delete("/api/v1/papers/paper-note-1/agent-note")
    assert delete_response.status_code == 200
    assert delete_response.json()["agent_note"] in (None, "")
