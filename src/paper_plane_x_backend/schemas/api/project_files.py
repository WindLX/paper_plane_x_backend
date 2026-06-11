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
    content: str = Field(default="", description="文件内容；创建目录时可省略")
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


class ProjectFileReadLinesResponse(BaseModel):
    """按行读取文件响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str
    start_line: int
    end_line: int
    total_lines: int
    lines: list[dict[str, object]]


class ProjectFileFindResponse(BaseModel):
    """文件内查找响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str
    query: str
    total_matches: int
    matches: list[dict[str, object]]


class ProjectFileReplaceLinesRequest(BaseModel):
    """按行替换文件请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str = Field(..., min_length=1)
    start_line: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)
    new_text: str


class ProjectFileReplaceLinesResponse(BaseModel):
    """按行替换文件响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str
    start_line: int
    end_line: int
    lines_replaced: int
    bytes_written: int


class ProjectFileReplaceTextRequest(BaseModel):
    """按精确文本替换文件请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str = Field(..., min_length=1)
    old_text: str = Field(..., min_length=1)
    new_text: str
    replace_all: bool = False
    expected_occurrences: int = Field(default=1, ge=1)


class ProjectFileReplaceTextResponse(BaseModel):
    """按精确文本替换文件响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str
    replacements: int
    bytes_written: int


class ProjectFilePatchRequest(BaseModel):
    """基于锚点 patch 文件请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str = Field(..., min_length=1)
    action: str = Field(..., description="replace, insert_before, insert_after, delete")
    anchor_text: str = Field(..., min_length=1)
    content: str = ""
    expected_occurrences: int = Field(default=1, ge=1)


class ProjectFilePatchResponse(BaseModel):
    """基于锚点 patch 文件响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str
    action: str
    occurrences: int
    bytes_written: int


class ProjectFileExportRequest(BaseModel):
    """导出文件请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str = Field(..., min_length=1, description="相对路径，如 /notes/idea.md")
    format: str = Field(
        default="markdown",
        description="导出格式：markdown, docx, pdf, html",
    )
