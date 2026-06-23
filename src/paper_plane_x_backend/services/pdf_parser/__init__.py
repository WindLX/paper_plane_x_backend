"""PDF 解析器包.

提供可插拔的 PDF-to-Markdown 解析器抽象与两种内置实现：
- LocalMinerUParser: 本地部署的 MinerU 服务
- CloudMinerUParser: MinerU 官方云端精准解析 API
"""

from paper_plane_x_backend.services.pdf_parser.base import (
    PdfParser,
    PdfParserError,
    PdfParseResult,
)
from paper_plane_x_backend.services.pdf_parser.cloud_mineru import CloudMinerUParser
from paper_plane_x_backend.services.pdf_parser.factory import create_pdf_parser
from paper_plane_x_backend.services.pdf_parser.local_mineru import LocalMinerUParser

__all__ = [
    "CloudMinerUParser",
    "LocalMinerUParser",
    "PdfParseResult",
    "PdfParser",
    "PdfParserError",
    "create_pdf_parser",
]
