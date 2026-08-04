"""Original paper PDF API tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from paper_plane_x_backend.services import Database
from paper_plane_x_backend.services.paper.repository import PaperRepository

PDF_BYTES = b"%PDF-1.7\noriginal-paper-content\n%%EOF\n"


def _create_paper_with_pdf(db: Database, tmp_path: Path, paper_id: str) -> Path:
    pdf_path = tmp_path / "original.pdf"
    pdf_path.write_bytes(PDF_BYTES)
    PaperRepository(db).create(paper_id=paper_id, raw_pdf_path=str(pdf_path))
    return pdf_path


def test_get_paper_pdf_returns_inline_original_file(
    client: TestClient,
    db: Database,
    tmp_path: Path,
) -> None:
    _create_paper_with_pdf(db, tmp_path, "pap-pdf-1")

    response = client.get("/api/v1/papers/pap-pdf-1/pdf")

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'inline; filename="pap-pdf-1.pdf"'
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_get_paper_pdf_supports_attachment_and_range(
    client: TestClient,
    db: Database,
    tmp_path: Path,
) -> None:
    _create_paper_with_pdf(db, tmp_path, "pap-pdf-range")

    attachment = client.get("/api/v1/papers/pap-pdf-range/pdf?download=true")
    partial = client.get(
        "/api/v1/papers/pap-pdf-range/pdf",
        headers={"Range": "bytes=0-7"},
    )

    assert attachment.status_code == 200
    assert attachment.headers["content-disposition"] == (
        'attachment; filename="pap-pdf-range.pdf"'
    )
    assert partial.status_code == 206
    assert partial.content == PDF_BYTES[:8]
    assert partial.headers["content-range"] == f"bytes 0-7/{len(PDF_BYTES)}"


def test_get_paper_pdf_returns_404_for_missing_paper(client: TestClient) -> None:
    response = client.get("/api/v1/papers/missing/pdf")

    assert response.status_code == 404
    assert response.json()["detail"] == "Paper missing not found"


def test_get_paper_pdf_returns_409_without_stored_path(
    client: TestClient,
    db: Database,
) -> None:
    PaperRepository(db).create(paper_id="pap-no-pdf")

    response = client.get("/api/v1/papers/pap-no-pdf/pdf")

    assert response.status_code == 409
    assert response.json()["detail"] == "Paper pap-no-pdf has no original PDF file"


def test_get_paper_pdf_returns_409_when_file_is_missing(
    client: TestClient,
    db: Database,
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.pdf"
    PaperRepository(db).create(
        paper_id="pap-missing-file",
        raw_pdf_path=str(missing_path),
    )

    response = client.get("/api/v1/papers/pap-missing-file/pdf")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Paper pap-missing-file original PDF file is unavailable"
    )
