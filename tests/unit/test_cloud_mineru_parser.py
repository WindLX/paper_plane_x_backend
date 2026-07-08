"""Cloud MinerU parser tests."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from paper_plane_x_backend.services.pdf_parser.cloud_mineru import CloudMinerUParser


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: dict[str, Any] | None = None,
        content: bytes = b"",
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.content = content
        self.text = text

    def json(self) -> dict[str, Any]:
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


class _FakeAsyncClient:
    calls: list[tuple[str, str]]
    zip_bytes: bytes

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        _ = args

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> _FakeResponse:
        _ = headers, json
        self.calls.append(("POST", url))
        return _FakeResponse(
            json_data={
                "code": 0,
                "msg": "ok",
                "data": {
                    "batch_id": "batch-1",
                    "file_urls": ["https://oss.example/upload"],
                },
            }
        )

    async def put(self, url: str, *, content: bytes) -> _FakeResponse:
        _ = content
        self.calls.append(("PUT", url))
        return _FakeResponse(status_code=200)

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        _ = headers
        self.calls.append(("GET", url))
        if url.endswith("/api/v4/extract-results/batch/batch-1"):
            return _FakeResponse(
                json_data={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "batch_id": "batch-1",
                        "extract_result": [
                            {
                                "file_name": "paper.pdf",
                                "state": "done",
                                "full_zip_url": "https://cdn.example/result.zip",
                            }
                        ],
                    },
                }
            )
        if url == "https://cdn.example/result.zip":
            return _FakeResponse(status_code=200, content=self.zip_bytes)
        raise AssertionError(f"unexpected GET {url}")


def _make_result_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("full.md", "# Parsed\n")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_cloud_mineru_file_upload_polls_batch_result_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    save_dir = tmp_path / "out"

    _FakeAsyncClient.calls = []
    _FakeAsyncClient.zip_bytes = _make_result_zip()
    monkeypatch.setattr(
        "paper_plane_x_backend.services.pdf_parser.cloud_mineru.httpx.AsyncClient",
        _FakeAsyncClient,
    )

    parser = CloudMinerUParser(api_key="token")
    result = await parser.parse_pdf(pdf_path, "paper.md", save_dir)

    assert result.md_content == "# Parsed\n"
    assert (save_dir / "paper.md").read_text(encoding="utf-8") == "# Parsed\n"
    assert ("GET", "https://mineru.net/api/v4/extract-results/batch/batch-1") in (
        _FakeAsyncClient.calls
    )
    assert ("GET", "https://mineru.net/api/v4/extract/task/batch-1") not in (
        _FakeAsyncClient.calls
    )
