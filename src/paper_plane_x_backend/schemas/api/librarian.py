"""Librarian API schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paper_plane_x_backend.models import PaperSortKey, SortOrder
from paper_plane_x_backend.schemas import QuickScan
from paper_plane_x_backend.services.librarian.query_parser import (
    parse_librarian_query_expr,
)


class LibrarianProjectionRequest(BaseModel):
    """单 paper 单路径精确投影请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_id: str = Field(..., min_length=1)
    field_path: str = Field(..., min_length=1)


class LibrarianProjectionResponse(BaseModel):
    """单 paper 单路径精确投影响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_id: str
    field_path: str
    value: Any | None = None


class LibrarianMatrixRequest(BaseModel):
    """多 paper 多路径矩阵投影请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_ids: list[str] = Field(..., min_length=1)
    field_paths: list[str] = Field(..., min_length=1)


class LibrarianMatrixResponse(BaseModel):
    """多 paper 多路径矩阵投影响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_ids: list[str]
    field_paths: list[str]
    items: dict[str, dict[str, Any | None]]


class LibrarianGlobalFinderRequest(BaseModel):
    """项目级文献总览请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str = Field(..., min_length=1, description="项目 ID")


class LibrarianGlobalFinderPaperSummary(BaseModel):
    """Global Finder 中的论文基础摘要。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_id: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    quick_scan: QuickScan | None = None


class LibrarianYearDistributionStats(BaseModel):
    """年份分布统计。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    available_count: int = 0
    missing_count: int = 0
    mean: float | None = None
    variance: float | None = None
    median: float | None = None
    mode_years: list[int] = Field(default_factory=list)
    q25: float | None = None
    q75: float | None = None
    outlier_count: int = 0
    low_outlier_count: int = 0
    high_outlier_count: int = 0


class LibrarianTagCount(BaseModel):
    """标签统计项。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    tag: str
    count: int


class LibrarianGlobalFinderStats(BaseModel):
    """Global Finder 统计信息。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_count: int
    top_tags_limit: int
    year_distribution: LibrarianYearDistributionStats
    top_tags: list[LibrarianTagCount] = Field(default_factory=list)


class LibrarianGlobalFinderResponse(BaseModel):
    """项目级文献总览响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str
    papers: list[LibrarianGlobalFinderPaperSummary] = Field(default_factory=list)
    stats: LibrarianGlobalFinderStats


class LibrarianUnifiedSearchRequest(BaseModel):
    """统一搜索请求。"""

    model_config = ConfigDict(extra="forbid")

    project_id: str | None = Field(default=None, description="项目作用域，可选")
    paper_id: str | None = Field(default=None, description="按论文 ID 精确搜索")
    query_expr: str | None = Field(
        default=None,
        description="条件表达式，例如 (meta.title CONTAINS xxx) AND (meta.year BETWEEN [2020, 2025])",
    )
    limit: int = Field(default=20, ge=1, le=100, description="返回条数")
    offset: int = Field(default=0, ge=0, description="偏移量")
    sort_by: PaperSortKey = Field(
        default=PaperSortKey.CREATED_AT, description="排序字段"
    )
    sort_order: SortOrder = Field(
        default=SortOrder.DESC, description="排序方向，asc 或 desc"
    )

    @model_validator(mode="after")
    def validate_query_expr(self) -> "LibrarianUnifiedSearchRequest":
        if self.query_expr:
            parse_librarian_query_expr(self.query_expr)
        return self


class LibrarianUnifiedSearchResponse(BaseModel):
    """统一搜索响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str | None = Field(default=None, description="项目作用域")
    limit: int = Field(..., description="返回条数")
    offset: int = Field(..., description="偏移量")
    total: int = Field(..., description="命中总数")
    paper_ids: list[str] = Field(..., description="命中论文 ID 列表")


class LibrarianGuideResponse(BaseModel):
    """Librarian 字段与用法说明."""

    model_config = ConfigDict(strict=True, extra="forbid")

    field_paths_guide: str
    global_finder_schema: dict[str, Any]
    query_schema: dict[str, Any]
    projection_schema: dict[str, Any]
    matrix_schema: dict[str, Any]
    query_examples: list[str]
    projection_examples: list[str]
    matrix_tips: list[str]
    project_query_tips: list[str]
    global_finder_tips: list[str]
