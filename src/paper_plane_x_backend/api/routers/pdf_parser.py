"""独立 PDF 解析 Router（不入库）."""

import base64
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from paper_plane_x_backend.config import server_config
from paper_plane_x_backend.schemas.api import PdfParseImage, PdfParseResponse
from paper_plane_x_backend.services.app_settings import get_app_settings_repo
from paper_plane_x_backend.services.pdf_parser.base import (
    PdfParserError,
    PdfParseResult,
)
from paper_plane_x_backend.services.pdf_parser.factory import build_default_pdf_parser

router = APIRouter(prefix="/parse", tags=["parse"])
logger = logging.getLogger(__name__)


def _get_mime_type(image_path: Path) -> str:
    """根据扩展名推断图片 MIME 类型."""
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(image_path.suffix.lower(), "image/png")


def _build_response(result: PdfParseResult, parser_type: str) -> PdfParseResponse:
    """将解析结果和 base64 图片包装为响应."""
    images: list[PdfParseImage] = []
    for img_path in result.image_paths:
        try:
            img_bytes = img_path.read_bytes()
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            images.append(
                PdfParseImage(
                    name=img_path.name,
                    mime_type=_get_mime_type(img_path),
                    base64=b64,
                )
            )
        except Exception as e:
            logger.warning(
                "event=parse.image_read_failed image_path=%s error=%s",
                img_path,
                e,
            )

    return PdfParseResponse(
        md_content=result.md_content,
        images=images,
        parser_type=parser_type,
    )


@router.post(
    "/pdf",
    response_model=PdfParseResponse,
    summary="解析 PDF 为 Markdown（不入库）",
    responses={
        422: {"description": "解析失败或配置错误"},
    },
)
async def parse_pdf(
    pdf_file: UploadFile = File(..., description="待解析的 PDF 文件"),
    output_md_name: str | None = Form(
        default=None, description="生成的 Markdown 文件名，默认使用 PDF 文件名"
    ),
) -> PdfParseResponse:
    """接收上传的 PDF，调用当前配置的解析器，返回 Markdown 与 base64 图片。

    该接口不写入数据库，解析产物在响应完成后清理。
    """
    original_name = pdf_file.filename or "uploaded.pdf"
    if not original_name.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only PDF files are supported",
        )

    if output_md_name is None:
        output_md_name = f"{Path(original_name).stem}.md"

    logger.info(
        "event=parse.pdf_request_received file=%s output_md_name=%s",
        original_name,
        output_md_name,
    )

    parser_type = get_app_settings_repo().get().pdf_parser.type.value
    temp_dir_path: Path | None = None

    try:
        with tempfile.TemporaryDirectory(
            prefix="ppx-parse-", dir=server_config.data_dir
        ) as temp_dir:
            temp_dir_path = Path(temp_dir)
            upload_path = temp_dir_path / original_name
            upload_path.write_bytes(await pdf_file.read())

            pdf_parser = build_default_pdf_parser()
            result = await pdf_parser.parse_pdf(
                file_path=upload_path,
                output_md_name=output_md_name,
                save_dir=temp_dir_path,
            )

            logger.info(
                "event=parse.pdf_succeeded file=%s parser_type=%s "
                "md_length=%s image_count=%s",
                original_name,
                parser_type,
                len(result.md_content),
                len(result.image_paths),
            )
            return _build_response(result, parser_type=parser_type)

    except PdfParserError as exc:
        logger.warning(
            "event=parse.pdf_failed file=%s parser_type=%s error=%s",
            original_name,
            parser_type,
            exc.message,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.message,
        ) from exc
    except Exception as exc:
        logger.exception(
            "event=parse.pdf_unexpected_error file=%s parser_type=%s",
            original_name,
            parser_type,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse PDF: {exc}",
        ) from exc
    finally:
        if temp_dir_path is not None and temp_dir_path.exists():
            _cleanup_temp_dir(temp_dir_path)


def _cleanup_temp_dir(temp_dir: Path) -> None:
    """递归清理临时目录."""
    import shutil

    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.debug("event=parse.temp_dir_cleaned path=%s", temp_dir)
    except Exception as e:
        logger.warning(
            "event=parse.temp_dir_cleanup_failed path=%s error=%s",
            temp_dir,
            e,
        )
