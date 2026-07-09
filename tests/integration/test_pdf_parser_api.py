"""PDF 解析 Router 集成测试."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paper_plane_x_backend.api.routers import pdf_parser as pdf_parser_router
from paper_plane_x_backend.services.pdf_parser.base import (
    PdfParser,
    PdfParserError,
    PdfParseResult,
)
from paper_plane_x_backend.services.pdf_parser.factory import build_default_pdf_parser


class _FakePdfParser:
    """返回固定结果的假解析器."""

    def __init__(
        self, md_content: str = "# parsed", image_paths: list[Path] | None = None
    ):
        self.md_content = md_content
        self.image_paths = image_paths or []

    async def parse_pdf(
        self, file_path: Path, output_md_name: str, save_dir: Path
    ) -> PdfParseResult:
        _ = file_path, output_md_name, save_dir
        return PdfParseResult(md_content=self.md_content, image_paths=self.image_paths)


class _FailingPdfParser:
    """总是失败的假解析器."""

    async def parse_pdf(
        self, file_path: Path, output_md_name: str, save_dir: Path
    ) -> PdfParseResult:
        _ = file_path, output_md_name, save_dir
        raise PdfParserError("mock parse failure")


@pytest.fixture
def fake_parser() -> PdfParser:
    return _FakePdfParser()  # type: ignore[return-value]


def _upload_pdf(
    client: TestClient, pdf_bytes: bytes, output_md_name: str | None = None
):
    files = {"pdf_file": ("test.pdf", pdf_bytes, "application/pdf")}
    data: dict[str, str] = {}
    if output_md_name:
        data["output_md_name"] = output_md_name
    return client.post("/api/v1/parse/pdf", data=data, files=files)


def test_parse_pdf_success(client: TestClient, tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"fake-image")

    pdf_parser_router.build_default_pdf_parser = lambda: _FakePdfParser(  # type: ignore[method-assign]
        md_content="# Hello",
        image_paths=[img],
    )

    try:
        response = _upload_pdf(client, b"%PDF-1.4 fake pdf bytes")
        assert response.status_code == 200
        data = response.json()
        assert data["md_content"] == "# Hello"
        assert data["parser_type"] in ("local_mineru", "cloud_mineru")
        assert len(data["images"]) == 1
        assert data["images"][0]["name"] == "x.png"
        assert data["images"][0]["mime_type"] == "image/png"
        assert data["images"][0]["base64"]
    finally:
        pdf_parser_router.build_default_pdf_parser = build_default_pdf_parser  # type: ignore[method-assign]


def test_parse_pdf_custom_output_name(client: TestClient) -> None:
    captured: dict[str, str] = {}

    class _CaptureParser:
        async def parse_pdf(
            self, file_path: Path, output_md_name: str, save_dir: Path
        ) -> PdfParseResult:
            captured["output_md_name"] = output_md_name
            return PdfParseResult(md_content="# captured", image_paths=[])

    pdf_parser_router.build_default_pdf_parser = lambda: _CaptureParser()  # type: ignore[method-assign]
    try:
        response = _upload_pdf(client, b"%PDF", output_md_name="custom.md")
        assert response.status_code == 200
        assert captured["output_md_name"] == "custom.md"
    finally:
        pdf_parser_router.build_default_pdf_parser = build_default_pdf_parser  # type: ignore[method-assign]


def test_parse_pdf_default_output_name(client: TestClient) -> None:
    captured: dict[str, str] = {}

    class _CaptureParser:
        async def parse_pdf(
            self, file_path: Path, output_md_name: str, save_dir: Path
        ) -> PdfParseResult:
            captured["output_md_name"] = output_md_name
            return PdfParseResult(md_content="# captured", image_paths=[])

    pdf_parser_router.build_default_pdf_parser = lambda: _CaptureParser()  # type: ignore[method-assign]
    try:
        response = _upload_pdf(client, b"%PDF")
        assert response.status_code == 200
        assert captured["output_md_name"] == "test.md"
    finally:
        pdf_parser_router.build_default_pdf_parser = build_default_pdf_parser  # type: ignore[method-assign]


def test_parse_pdf_rejects_non_pdf(client: TestClient) -> None:
    files = {"pdf_file": ("test.txt", b"not a pdf", "text/plain")}
    response = client.post("/api/v1/parse/pdf", files=files)
    assert response.status_code == 422


def test_parse_pdf_returns_422_on_parser_error(client: TestClient) -> None:
    pdf_parser_router.build_default_pdf_parser = lambda: _FailingPdfParser()  # type: ignore[method-assign]
    try:
        response = _upload_pdf(client, b"%PDF")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "mock parse failure" in detail
    finally:
        pdf_parser_router.build_default_pdf_parser = build_default_pdf_parser  # type: ignore[method-assign]


def test_parse_pdf_cloud_missing_api_key_returns_422(client: TestClient) -> None:
    """当后端配置为 cloud 且未配置 api_key 时，接口应返回 422."""
    from paper_plane_x_backend.services.app_settings import get_app_settings_repo

    repo = get_app_settings_repo()
    original_type = repo.get().pdf_parser.type

    # 切换到 cloud 并不填 api_key
    repo.update_pdf_parser({"type": "cloud_mineru"})
    repo.update_pdf_parser({"cloud": {"api_key": None}})

    try:
        response = _upload_pdf(client, b"%PDF")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "api_key" in detail.lower()
    finally:
        # 恢复配置
        repo.update_pdf_parser({"type": original_type.value})
