"""Paper Markdown download API tests."""

from fastapi.testclient import TestClient

from paper_plane_x_backend.models import ExtractionStatus
from paper_plane_x_backend.services import Database
from paper_plane_x_backend.services.paper.repository import PaperRepository


def test_download_paper_markdown_returns_attachment(
    client: TestClient,
    db: Database,
) -> None:
    PaperRepository(db).create(
        paper_id="pap-markdown-1",
        md_content="# Parsed paper\n\n完整正文",
        extraction_status=ExtractionStatus.COMPLETED,
    )

    response = client.get("/api/v1/papers/pap-markdown-1/markdown")

    assert response.status_code == 200
    assert response.content == "# Parsed paper\n\n完整正文".encode()
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert (
        response.headers["content-disposition"]
        == "attachment; filename*=UTF-8''pap-markdown-1.md"
    )


def test_download_paper_markdown_returns_404_for_missing_paper(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/papers/missing/markdown")

    assert response.status_code == 404
    assert response.json()["detail"] == "Paper missing not found"


def test_download_paper_markdown_returns_409_when_not_parsed(
    client: TestClient,
    db: Database,
) -> None:
    PaperRepository(db).create(
        paper_id="pap-markdown-empty",
        md_content="",
    )

    response = client.get("/api/v1/papers/pap-markdown-empty/markdown")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Paper pap-markdown-empty has no parsed markdown content"
    )
