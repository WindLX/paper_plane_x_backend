"""MinerU V1 contract tests without network or model dependencies."""

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from paper_plane_x_backend.services.pdf_parser import local_mineru
from paper_plane_x_backend.services.pdf_parser.base import PdfParserError
from paper_plane_x_backend.services.pdf_parser.local_mineru import LocalMinerUParser


def archive_bytes(md_content: str = "# Paper\n![figure](images/fig.png)") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("markdown.md", md_content)
        archive.writestr("images/fig.png", b"image")
        archive.writestr("../outside.txt", b"unsafe")
    return buffer.getvalue()


@pytest.mark.parametrize("cached", [False, True])
async def test_v1_upload_poll_download_all_pages(tmp_path, monkeypatch, cached):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    calls = []
    upload = {"id": "up-1", "status": "completed", "file": {"id": "file-1"}}
    job = {
        "job_id": "job-1",
        "status": "completed",
        "files": [
            {
                "status": "completed",
                "output_files": {
                    "markdown": {"file_id": "md-1"},
                    "zip": {"file_id": "zip-1"},
                },
            }
        ],
    }

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/uploads":
            assert json.loads(request.content)["bytes"] == len(pdf.read_bytes())
            return httpx.Response(
                200,
                json=upload
                if cached
                else {
                    "id": "up-1",
                    "status": "pending",
                    "upload_url": "/v1/uploads/up-1/content",
                    "upload_method": "PUT",
                },
            )
        if request.method == "PUT":
            assert request.content == pdf.read_bytes()
            return httpx.Response(200)
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json=upload)
        if request.method == "POST" and request.url.path == "/v1/parse/jobs":
            payload = json.loads(request.content)
            assert payload["files"][0]["page_range"] == "all"
            assert payload["tier"] == "standard"
            assert payload["output_formats"] == ["zip"]
            return httpx.Response(
                202,
                json={
                    "job_id": "job-1",
                    "status": "queued",
                    "files": [{"status": "queued"}],
                },
            )
        if request.url.path == "/v1/parse/jobs/job-1":
            return httpx.Response(200, json=job)
        if request.url.path == "/v1/files/md-1/content":
            return httpx.Response(200, content=b"# Paper\n![figure](images/fig.png)")
        if request.url.path == "/v1/files/zip-1/content":
            return httpx.Response(200, content=archive_bytes())
        raise AssertionError(str(request.url))

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        local_mineru.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    result = await LocalMinerUParser("http://mineru").parse_pdf(
        pdf, "paper.md", tmp_path / "out"
    )
    assert result.md_content.startswith("# Paper")
    assert result.image_paths == [tmp_path / "out/images/fig.png"]
    assert result.image_paths[0].read_bytes() == b"image"
    assert not (tmp_path / "outside.txt").exists()
    assert (("PUT", "/v1/uploads/up-1/content") in calls) is (not cached)
    assert ("GET", "/v1/files/md-1/content") not in calls


@pytest.mark.parametrize("status", ["failed", "partial", "canceled"])
async def test_job_terminal_errors_are_not_success(tmp_path, monkeypatch, status):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")

    def handle(request):
        if request.url.path == "/v1/uploads":
            return httpx.Response(
                200, json={"id": "up", "status": "completed", "file": {"id": "file"}}
            )
        return httpx.Response(
            200,
            json={
                "job_id": "job",
                "status": status,
                "files": [
                    {
                        "status": "failed",
                        "error": {
                            "code": "parse_error",
                            "message": "private document body",
                        },
                    }
                ],
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        local_mineru.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    with pytest.raises(PdfParserError, match=status) as error:
        await LocalMinerUParser("http://mineru").parse_pdf(pdf, "paper.md", tmp_path)
    assert "private document body" not in str(error.value)


async def test_invalid_protocol_and_http_errors(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    real_client = httpx.AsyncClient
    for response, message in [
        (httpx.Response(404), "HTTP 404"),
        (httpx.Response(200, json={}), "ValidationError"),
    ]:
        monkeypatch.setattr(
            local_mineru.httpx,
            "AsyncClient",
            lambda **kw: real_client(
                transport=httpx.MockTransport(lambda req: response), **kw
            ),
        )
        with pytest.raises(PdfParserError, match=message):
            await LocalMinerUParser("http://mineru").parse_pdf(
                pdf, "paper.md", tmp_path
            )


def test_missing_images_fail_before_publishing_markdown(tmp_path: Path):
    parser = LocalMinerUParser("http://mineru")
    with pytest.raises(PdfParserError, match="missing or ambiguous"):
        parser._save_artifacts(
            archive_bytes("![x](images/missing.png)"), "paper.md", tmp_path
        )
    assert not (tmp_path / "paper.md").exists()


async def test_overall_deadline_reports_remote_job_may_still_run(tmp_path, monkeypatch):
    import asyncio

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    original_timeout = asyncio.timeout
    real_client = httpx.AsyncClient

    async def handle(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        local_mineru.asyncio, "timeout", lambda seconds: original_timeout(0.01)
    )
    monkeypatch.setattr(
        local_mineru.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    with pytest.raises(PdfParserError, match="remote job may still be running"):
        await LocalMinerUParser("http://mineru").parse_pdf(pdf, "paper.md", tmp_path)


async def test_upload_target_must_stay_on_local_service(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    real_client = httpx.AsyncClient
    calls = []

    def handle(request):
        calls.append(request.url)
        return httpx.Response(
            200,
            json={
                "id": "up",
                "status": "pending",
                "upload_url": "http://other-service/upload",
                "upload_method": "PUT",
            },
        )

    monkeypatch.setattr(
        local_mineru.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    with pytest.raises(PdfParserError, match="different-origin"):
        await LocalMinerUParser("http://mineru").parse_pdf(pdf, "paper.md", tmp_path)
    assert len(calls) == 1
