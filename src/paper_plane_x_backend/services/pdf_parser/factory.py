"""PDF 解析器工厂."""

import logging
from pathlib import Path

from paper_plane_x_backend.models.app_settings import (
    AppSettings,
    CloudPdfParserConfig,
    LocalPdfParserConfig,
    PdfParserType,
)
from paper_plane_x_backend.services.pdf_parser.base import PdfParser, PdfParserError
from paper_plane_x_backend.services.pdf_parser.cloud_mineru import CloudMinerUParser
from paper_plane_x_backend.services.pdf_parser.local_mineru import LocalMinerUParser

logger = logging.getLogger(__name__)


def create_pdf_parser(settings: AppSettings) -> PdfParser:
    """根据 AppSettings 构造对应的 PDF 解析器实例."""
    config = settings.pdf_parser
    if config.type == PdfParserType.LOCAL_MINERU:
        local = config.local or LocalPdfParserConfig()
        return LocalMinerUParser(
            base_url=local.base_url,
            output_dir=local.output_dir,
        )

    if config.type == PdfParserType.CLOUD_MINERU:
        cloud = config.cloud or CloudPdfParserConfig()
        if not cloud.api_key:
            raise PdfParserError(
                "Cloud MinerU parser is selected but api_key is not configured"
            )
        return CloudMinerUParser(
            api_key=cloud.api_key,
            base_url=cloud.base_url,
            model_version=cloud.model_version,
            enable_formula=cloud.enable_formula,
            enable_table=cloud.enable_table,
            is_ocr=cloud.is_ocr,
            language=cloud.language,
        )

    raise PdfParserError(f"Unsupported pdf_parser type: {config.type}")


def build_default_pdf_parser() -> PdfParser:
    """使用当前应用设置构造默认 PDF 解析器."""
    from paper_plane_x_backend.services.app_settings import get_app_settings_repo

    return create_pdf_parser(get_app_settings_repo().get())


def get_pdf_parser_save_dir(settings: AppSettings, paper_id: str) -> Path:
    """根据解析器类型返回解析产物保存目录."""
    if settings.pdf_parser.type == PdfParserType.CLOUD_MINERU:
        return Path("./data/papers") / paper_id
    local = settings.pdf_parser.local or LocalPdfParserConfig()
    return local.output_dir / paper_id
