"""Project sandbox file API schemas."""

from pydantic import BaseModel, ConfigDict, Field


class ProjectFileItem(BaseModel):
    """文件或目录项."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., description="文件/目录名称")
    is_dir: bool = Field(..., description="是否为目录")
    size: int | None = Field(default=None, description="文件大小（字节），目录为 null")


class ProjectFileListResponse(BaseModel):
    """文件列表响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[ProjectFileItem] = Field(..., description="文件/目录列表")


class ProjectFileContentResponse(BaseModel):
    """文件内容响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str = Field(..., description="文件相对路径")
    content: str = Field(..., description="文件内容")


class ProjectFileWriteRequest(BaseModel):
    """写入文件请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str = Field(..., min_length=1, description="相对路径，如 /notes/idea.md")
    content: str = Field(..., description="文件内容")
    is_dir: bool | None = Field(
        default=False,
        description="是否为目录，如果为 true 则 content 字段会被忽略",
    )


class ProjectFileWriteResponse(BaseModel):
    """写入文件响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str = Field(..., description="文件相对路径")
    bytes_written: int = Field(..., description="写入字节数")
    is_dir: bool = Field(..., description="是否为目录")


class ProjectFileDeleteResponse(BaseModel):
    """删除文件响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    removed: str = Field(..., description="被删除的文件/目录路径")


class ProjectFileExportRequest(BaseModel):
    """导出文件请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str = Field(..., min_length=1, description="相对路径，如 /notes/idea.md")
    format: str = Field(
        default="markdown",
        description="导出格式：markdown, docx, pdf, html",
    )
