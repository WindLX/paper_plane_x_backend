"""Paper 解析服务.

封装 PDF 解析器调用与文件 I/O，将 PDF 转换为后续处理所需的输入。
"""

import base64
import logging
from pathlib import Path
from typing import Callable

from paper_plane_x_backend.models import Paper
from paper_plane_x_backend.services.app_settings import get_app_settings_repo
from paper_plane_x_backend.services.pdf_parser.base import PdfParser
from paper_plane_x_backend.services.pdf_parser.factory import (
    build_default_pdf_parser,
    get_pdf_parser_save_dir,
)

logger = logging.getLogger(__name__)


class PaperParserError(Exception):
    """PaperParser 异常."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PaperParser:
    """论文内容解析器."""

    def __init__(self, pdf_parser: PdfParser | None = None) -> None:
        self.pdf_parser = pdf_parser or build_default_pdf_parser()

    async def parse(self, pdf_path: Path, paper_id: str) -> tuple[str, list[Path]]:
        """使用配置的 PDF 解析器解析 PDF，返回 markdown 内容和图片路径列表."""
        app_settings = get_app_settings_repo().get()
        output_dir = get_pdf_parser_save_dir(app_settings, paper_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        result = await self.pdf_parser.parse_pdf(
            file_path=pdf_path,
            output_md_name=f"{paper_id}.md",
            save_dir=output_dir,
        )
        return result.md_content, result.image_paths

    async def prepare_inputs(
        self,
        paper_id: str,
        paper: Paper,
        pdf_path: Path | None,
        update_parse_result_callback: (
            Callable[[str, str, list[str]], object] | None
        ) = None,
    ) -> tuple[str, list[Path]]:
        """为 existing paper 准备闭环输入.

        若记录已有 md_content，直接使用；否则要求提供 pdf_path 重新解析。
        解析完成后可通过 callback 回写解析结果到数据库。
        """
        md_content = paper.md_content
        image_paths: list[Path] = [Path(p) for p in paper.images_paths]

        if md_content:
            return md_content, image_paths

        if pdf_path is None:
            raise PaperParserError(
                "Paper has no markdown content and no PDF path provided"
            )

        md_content, image_paths = await self.parse(pdf_path, paper_id)
        if update_parse_result_callback is not None:
            update_parse_result_callback(
                paper_id,
                md_content,
                [str(p) for p in image_paths],
            )
        return md_content, image_paths

    @staticmethod
    def load_images_base64(image_paths: list[Path]) -> list[str]:
        """将图片加载为 base64 编码.

        Args:
            image_paths: 图片路径列表

        Returns:
            list[str]: base64 编码的图片列表
        """
        images_base64: list[str] = []
        for img_path in image_paths:
            try:
                with open(img_path, "rb") as f:
                    img_data = f.read()
                    ext = img_path.suffix.lower()
                    mime_type = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".webp": "image/webp",
                    }.get(ext, "image/png")

                    b64_data = base64.b64encode(img_data).decode("utf-8")
                    images_base64.append(f"data:{mime_type};base64,{b64_data}")
            except Exception as e:
                logger.warning(
                    "event=paper.image_load_failed image_path=%s error=%s",
                    img_path,
                    e,
                )

        return images_base64
