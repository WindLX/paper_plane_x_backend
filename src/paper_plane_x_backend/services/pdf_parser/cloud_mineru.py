"""MinerU 官方云端精准解析 API 实现."""

import asyncio
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

import httpx

from paper_plane_x_backend.services.pdf_parser.base import (
    PdfParserError,
    PdfParseResult,
)

logger = logging.getLogger(__name__)


class CloudMinerUParser:
    """MinerU 官方云解析器（精准解析 API）.

    流程：
      1. 通过 ``POST /api/v4/file-urls/batch`` 申请文件上传 URL。
      2. 使用返回的预签名 URL PUT 上传 PDF 文件。
      3. 轮询 ``GET /api/v4/extract-results/batch/{batch_id}`` 等待任务完成。
      4. 下载结果 zip 包并解压，返回 markdown 与图片路径。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://mineru.net",
        model_version: str = "pipeline",
        enable_formula: bool = True,
        enable_table: bool = True,
        is_ocr: bool = False,
        language: str = "ch",
        poll_interval: float = 3.0,
        poll_timeout: float = 600.0,
        request_timeout: float = 300.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_version = model_version
        self.enable_formula = enable_formula
        self.enable_table = enable_table
        self.is_ocr = is_ocr
        self.language = language
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.request_timeout = request_timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "*/*",
        }

    async def parse_pdf(
        self,
        file_path: Path,
        output_md_name: str,
        save_dir: Path,
    ) -> PdfParseResult:
        """通过 MinerU 云端 API 解析 PDF."""
        if not file_path.exists():
            logger.warning(
                "event=cloud_mineru.parse_file_not_found file_path=%s", file_path
            )
            raise PdfParserError(f"File not found: {file_path}")

        save_dir.mkdir(parents=True, exist_ok=True)
        batch_id, upload_url = await self._request_upload_url(file_path.name)
        await self._upload_file(file_path, upload_url)
        result = await self._poll_batch(batch_id)

        zip_url = result.get("full_zip_url")
        if not zip_url:
            raise PdfParserError(
                f"Cloud MinerU batch {batch_id} finished without full_zip_url"
            )

        zip_path = save_dir / f"{batch_id}.zip"
        await self._download_zip(zip_url, zip_path)
        md_content, image_paths = await self._extract_artifacts(
            zip_path, save_dir, output_md_name
        )
        return PdfParseResult(md_content=md_content, image_paths=image_paths)

    async def _request_upload_url(self, file_name: str) -> tuple[str, str]:
        url = f"{self.base_url}/api/v4/file-urls/batch"
        payload: dict[str, Any] = {
            "files": [
                {
                    "name": file_name,
                    "is_ocr": self.is_ocr,
                }
            ],
            "model_version": self.model_version,
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "language": self.language,
        }

        logger.info(
            "event=cloud_mineru.request_upload_url file_name=%s model=%s",
            file_name,
            self.model_version,
        )

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.post(
                url, headers=self._headers(), json=self._filter_none(payload)
            )

        self._raise_for_status(response)
        data = cast(dict[str, Any], response.json()).get("data", {})
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls")
        if not batch_id or not file_urls or not isinstance(file_urls, list):
            raise PdfParserError(
                "Invalid upload URL response: missing batch_id or urls"
            )
        first_url = cast(list[Any], file_urls)[0]
        return str(batch_id), str(first_url)

    async def _upload_file(self, file_path: Path, upload_url: str) -> None:
        file_bytes = await asyncio.to_thread(file_path.read_bytes)
        logger.info(
            "event=cloud_mineru.upload_file file=%s size=%s",
            file_path,
            len(file_bytes),
        )
        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.put(upload_url, content=file_bytes)

        if response.status_code not in (200, 201):
            raise PdfParserError(
                f"Failed to upload file to presigned URL: "
                f"HTTP {response.status_code}: {response.text}"
            )
        logger.info("event=cloud_mineru.upload_file_done file=%s", file_path)

    async def _poll_batch(self, batch_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/api/v4/extract-results/batch/{batch_id}"
        start = asyncio.get_event_loop().time()

        while True:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                response = await client.get(url, headers=self._headers())
            self._raise_for_status(response)

            data = cast(dict[str, Any], response.json())
            response_data = cast(dict[str, Any], data.get("data", {}))
            results = response_data.get("extract_result")
            if not isinstance(results, list) or not results:
                raise PdfParserError(
                    f"Invalid MinerU batch result response for batch {batch_id}: "
                    "missing extract_result"
                )
            task_data = cast(dict[str, Any], results[0])
            state = task_data.get("state")

            if state == "done":
                logger.info("event=cloud_mineru.task_done batch_id=%s", batch_id)
                return task_data

            if state == "failed":
                err_msg = task_data.get("err_msg", "unknown error")
                logger.error(
                    "event=cloud_mineru.task_failed batch_id=%s err_msg=%s",
                    batch_id,
                    err_msg,
                )
                raise PdfParserError(f"MinerU cloud task failed: {err_msg}")

            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > self.poll_timeout:
                raise PdfParserError(
                    f"MinerU cloud batch {batch_id} polling timeout "
                    f"after {self.poll_timeout}s"
                )

            progress = task_data.get("extract_progress", {})
            logger.info(
                "event=cloud_mineru.task_polling batch_id=%s state=%s progress=%s",
                batch_id,
                state,
                progress,
            )
            await asyncio.sleep(self.poll_interval)

    async def _download_zip(self, zip_url: str, dest: Path) -> None:
        logger.info("event=cloud_mineru.download_zip url=%s dest=%s", zip_url, dest)
        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.get(zip_url)

        if response.status_code != 200:
            raise PdfParserError(
                f"Failed to download result zip: HTTP {response.status_code}"
            )

        dest.write_bytes(response.content)
        logger.info(
            "event=cloud_mineru.download_zip_done dest=%s size=%s",
            dest,
            len(response.content),
        )

    async def _extract_artifacts(
        self, zip_path: Path, save_dir: Path, output_md_name: str
    ) -> tuple[str, list[Path]]:
        try:
            zip_bytes = await asyncio.to_thread(zip_path.read_bytes)
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(save_dir)
        except zipfile.BadZipFile as exc:
            raise PdfParserError(f"Invalid result zip file: {exc}") from exc
        except Exception as exc:
            raise PdfParserError(f"Failed to extract result zip: {exc}") from exc

        md_source = save_dir / "full.md"
        if not md_source.exists():
            raise PdfParserError(
                f"MinerU result zip does not contain full.md in {save_dir}"
            )

        md_dest = save_dir / output_md_name
        md_content = await asyncio.to_thread(md_source.read_text, encoding="utf-8")
        await asyncio.to_thread(md_dest.write_text, md_content, encoding="utf-8")

        image_dir = save_dir / "images"
        image_paths = self._collect_referenced_images(md_content, image_dir)
        return md_content, image_paths

    def _collect_referenced_images(
        self, md_content: str, image_dir: Path
    ) -> list[Path]:
        if not image_dir.exists():
            return []

        referenced: set[str] = set()
        md_pattern = r"!\[[^\]]*\]\(([^)]+)\)"
        html_pattern = r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>"

        for raw_ref in cast(list[str], re.findall(md_pattern, md_content)):
            ref = raw_ref.strip()
            if " " in ref:
                ref = ref.split(" ", 1)[0]
            ref = ref.strip("<>'\"")
            parsed_path = Path(unquote(str(urlparse(ref).path)))
            if parsed_path.name:
                referenced.add(parsed_path.name)

        for raw_ref in cast(
            list[str], re.findall(html_pattern, md_content, flags=re.IGNORECASE)
        ):
            ref = raw_ref.strip("<>'\"")
            parsed_path = Path(unquote(str(urlparse(ref).path)))
            if parsed_path.name:
                referenced.add(parsed_path.name)

        image_paths: list[Path] = []
        for file_name in sorted(referenced):
            candidate = image_dir / file_name
            if candidate.exists() and candidate.is_file():
                image_paths.append(candidate)
        return image_paths

    def _raise_for_status(self, response: httpx.Response) -> None:
        data: dict[str, Any] = {}
        try:
            data = cast(dict[str, Any], response.json())
        except Exception:
            pass

        if response.status_code >= 400 or data.get("code") != 0:
            msg = data.get("msg") or response.text or "unknown error"
            trace_id = data.get("trace_id", "")
            raise PdfParserError(
                f"MinerU cloud API error: HTTP {response.status_code}, "
                f"msg={msg}, trace_id={trace_id}"
            )

    @staticmethod
    def _filter_none(payload: dict[str, Any]) -> dict[str, Any]:
        """过滤掉请求体中为 None 的可选字段."""
        return {k: v for k, v in payload.items() if v is not None}


# 兼容旧导入
MinerUClient = CloudMinerUParser
MinerUOutput = PdfParseResult
