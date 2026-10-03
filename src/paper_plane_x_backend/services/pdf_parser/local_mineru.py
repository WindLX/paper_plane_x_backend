"""MinerU 4.x V1 document parsing adapter."""

import asyncio
import hashlib
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Literal, cast
from urllib.parse import unquote, urlparse

import httpx
from pydantic import BaseModel, ValidationError

from paper_plane_x_backend.services.pdf_parser.base import (
    PdfParserError,
    PdfParseResult,
)

logger = logging.getLogger(__name__)


class FileRef(BaseModel):
    id: str


class UploadResponse(BaseModel):
    id: str
    status: Literal["pending", "completed", "cancelled", "expired"]
    upload_url: str | None = None
    upload_method: Literal["PUT"] | None = None
    upload_headers: dict[str, str] | None = None
    file: FileRef | None = None


class OutputRef(BaseModel):
    file_id: str


class OutputFiles(BaseModel):
    zip: OutputRef | None = None


class JobError(BaseModel):
    code: str
    message: str


class JobFile(BaseModel):
    status: Literal["queued", "running", "completed", "failed"]
    output_files: OutputFiles | None = None
    error: JobError | None = None


class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "partial", "failed", "canceled"]
    files: list[JobFile]


class LocalMinerUParser:
    """Upload a PDF, await a V1 parse job, and download Markdown and images.

    ``output_dir`` belongs to PPX; paths on this host are never sent to MinerU.
    Standard is the server's document-quality tier, independent of its VLM engine.
    """

    def __init__(self, base_url: str, output_dir: str | Path = "./output") -> None:
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir)

    async def parse_pdf(
        self, file_path: Path, output_md_name: str, save_dir: Path
    ) -> PdfParseResult:
        if not file_path.is_file():
            raise PdfParserError(f"File not found: {file_path}")
        file_bytes = await asyncio.to_thread(file_path.read_bytes)
        digest = hashlib.sha256(file_bytes).hexdigest()
        try:
            # Includes cold startup and queued/in-flight work. Polling alone must
            # not allow an unavailable or stuck service to run without a deadline.
            async with (
                asyncio.timeout(1800),
                httpx.AsyncClient(
                    timeout=httpx.Timeout(600, connect=15), follow_redirects=True
                ) as client,
            ):
                response = await client.post(
                    f"{self.base_url}/v1/uploads",
                    json={
                        "filename": file_path.name,
                        "bytes": len(file_bytes),
                        "mime_type": "application/pdf",
                        "purpose": "parse",
                        "sha256sum": digest,
                    },
                )
                response.raise_for_status()
                upload = UploadResponse.model_validate(response.json())
                if upload.status == "pending":
                    if not upload.upload_url or upload.upload_method != "PUT":
                        raise PdfParserError("MinerU returned an invalid upload target")
                    upload_url = httpx.URL(self.base_url + "/").join(upload.upload_url)
                    base = httpx.URL(self.base_url)
                    if (upload_url.scheme, upload_url.host, upload_url.port) != (
                        base.scheme,
                        base.host,
                        base.port,
                    ):
                        raise PdfParserError(
                            "Local MinerU returned a different-origin upload target"
                        )
                    response = await client.put(
                        upload_url, content=file_bytes, headers=upload.upload_headers
                    )
                    response.raise_for_status()
                    response = await client.post(
                        f"{self.base_url}/v1/uploads/{upload.id}/complete",
                        json={"sha256sum": digest},
                    )
                    response.raise_for_status()
                    upload = UploadResponse.model_validate(response.json())
                if upload.status != "completed" or upload.file is None:
                    raise PdfParserError("MinerU upload did not complete")
                response = await client.post(
                    f"{self.base_url}/v1/parse/jobs",
                    json={
                        "files": [
                            {
                                "source": {
                                    "type": "file_id",
                                    "file_id": upload.file.id,
                                },
                                "page_range": "all",
                            }
                        ],
                        "tier": "standard",
                        "ocr_mode": "auto",
                        "output_formats": ["zip"],
                    },
                )
                response.raise_for_status()
                job = JobResponse.model_validate(response.json())
                logger.info("event=local_mineru.job_submitted job_id=%s", job.job_id)
                while job.status in ("queued", "running"):
                    await asyncio.sleep(2)
                    response = await client.get(
                        f"{self.base_url}/v1/parse/jobs/{job.job_id}"
                    )
                    response.raise_for_status()
                    job = JobResponse.model_validate(response.json())
                if (
                    job.status != "completed"
                    or len(job.files) != 1
                    or job.files[0].status != "completed"
                ):
                    errors = "; ".join(f.error.code for f in job.files if f.error)
                    raise PdfParserError(
                        f"MinerU job {job.job_id} ended as {job.status}: {errors}"
                    )
                outputs = job.files[0].output_files
                if outputs is None or outputs.zip is None:
                    raise PdfParserError(
                        f"MinerU job {job.job_id} is missing the artifact archive"
                    )
                response = await client.get(
                    f"{self.base_url}/v1/files/{outputs.zip.file_id}/content"
                )
                response.raise_for_status()
                return await asyncio.to_thread(
                    self._save_artifacts,
                    response.content,
                    output_md_name,
                    save_dir,
                )
        except TimeoutError as exc:
            raise PdfParserError(
                "MinerU parsing exceeded 1800 seconds; the remote job may still be running"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise PdfParserError(
                f"MinerU HTTP {exc.response.status_code} at {exc.request.url.path}"
            ) from exc
        except (
            httpx.RequestError,
            ValidationError,
            ValueError,
            OSError,
            zipfile.BadZipFile,
        ) as exc:
            raise PdfParserError(
                f"MinerU transport or artifact failure: {type(exc).__name__}"
            ) from exc

    def _save_artifacts(
        self, archive_bytes: bytes, output_md_name: str, save_dir: Path
    ) -> PdfParseResult:
        if Path(output_md_name).name != output_md_name:
            raise PdfParserError("Markdown filename must not include a directory")
        save_dir.mkdir(parents=True, exist_ok=True)
        image_dir = save_dir / "images"
        image_dir.mkdir(exist_ok=True)
        # Read only referenced image members. Never extract archive paths supplied
        # by the remote service into the local filesystem.
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            # V1's standalone Markdown embeds base64 images. The self-contained
            # ZIP's Markdown uses paths matching the packaged image members.
            try:
                md_content = archive.read("markdown.md").decode("utf-8")
            except KeyError as exc:
                raise PdfParserError("MinerU archive is missing markdown.md") from exc
            referenced = self._extract_referenced_image_names(md_content)
            for name in referenced:
                matches = [
                    item
                    for item in archive.infolist()
                    if not item.is_dir() and Path(item.filename).name == name
                ]
                if len(matches) != 1:
                    raise PdfParserError(
                        f"MinerU archive has missing or ambiguous image: {name}"
                    )
                (image_dir / name).write_bytes(archive.read(matches[0]))
        (save_dir / output_md_name).write_text(md_content, encoding="utf-8")
        self._prune_unreferenced_images(md_content, image_dir)
        return PdfParseResult(
            md_content=md_content,
            image_paths=self._get_image_paths(md_content, image_dir),
        )

    def _get_image_paths(self, md_content: str, image_dir: Path) -> list[Path]:
        if not image_dir.exists():
            return []

        referenced_names = self._extract_referenced_image_names(md_content)
        image_paths: list[Path] = []
        for file_name in sorted(referenced_names):
            candidate = image_dir / file_name
            if candidate.exists() and candidate.is_file():
                image_paths.append(candidate)
        return image_paths

    def _prune_unreferenced_images(self, md_content: str, image_dir: Path) -> None:
        if not image_dir.exists():
            return

        referenced_names = self._extract_referenced_image_names(md_content)
        removed_count = 0
        for candidate in image_dir.iterdir():
            if not candidate.is_file():
                continue
            if candidate.name not in referenced_names:
                candidate.unlink(missing_ok=True)
                removed_count += 1

        if removed_count:
            logger.info(
                "event=local_mineru.images_pruned removed_count=%s image_dir=%s",
                removed_count,
                image_dir,
            )

    def _extract_referenced_image_names(self, md_content: str) -> set[str]:
        references: set[str] = set()

        md_pattern = r"!\[[^\]]*\]\(([^)]+)\)"
        html_pattern = r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>"

        for raw_ref in cast(list[str], re.findall(md_pattern, md_content)):
            ref = raw_ref.strip()
            if " " in ref:
                ref = ref.split(" ", 1)[0]
            ref = ref.strip("<>'\"")
            parsed_path = Path(unquote(urlparse(ref).path))
            if parsed_path.name:
                references.add(parsed_path.name)

        for raw_ref in cast(
            list[str], re.findall(html_pattern, md_content, flags=re.IGNORECASE)
        ):
            ref = raw_ref.strip("<>'\"")
            parsed_path = Path(unquote(urlparse(ref).path))
            if parsed_path.name:
                references.add(parsed_path.name)

        return references
