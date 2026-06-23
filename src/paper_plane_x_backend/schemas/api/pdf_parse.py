"""PDF 解析 API 请求/响应模型."""

from pydantic import BaseModel, ConfigDict, Field


class PdfParseImage(BaseModel):
    """解析产物中的单张图片（base64 内联）."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., description="图片文件名（如 images/fig_001.png）")
    mime_type: str = Field(..., description="图片 MIME 类型")
    base64: str = Field(..., description="base64 编码的图片内容")


class PdfParseResponse(BaseModel):
    """PDF 解析响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    md_content: str = Field(..., description="Markdown 文本内容")
    images: list[PdfParseImage] = Field(
        default_factory=list[PdfParseImage], description="解析产物中引用到的图片"
    )
    parser_type: str = Field(..., description="实际使用的解析器类型，如 local_mineru / cloud_mineru")
