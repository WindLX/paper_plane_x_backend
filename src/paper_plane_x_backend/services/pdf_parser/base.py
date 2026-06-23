"""PDF 解析器抽象."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class PdfParseResult(BaseModel):
    """PDF 解析产物."""

    md_content: str = Field(..., description="Markdown 文本内容")
    image_paths: list[Path] = Field(
        default_factory=list[Path], description="解析产物中引用到的图片文件路径"
    )


@runtime_checkable
class PdfParser(Protocol):
    """PDF-to-Markdown 解析器协议.

    所有具体解析器必须实现此接口，以便 `PaperParser` 和数据处理流水线无感切换。
    """

    async def parse_pdf(
        self, file_path: Path, output_md_name: str, save_dir: Path
    ) -> PdfParseResult:
        """解析单个 PDF 文件.

        Args:
            file_path: 本地 PDF 文件路径。
            output_md_name: 期望生成的 markdown 文件名。
            save_dir: 解析产物保存目录（实现类可在此目录下创建 images/ 等子目录）。

        Returns:
            PdfParseResult: Markdown 内容与引用到的图片路径。
        """
        ...


class PdfParserError(Exception):
    """PDF 解析器通用异常."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
