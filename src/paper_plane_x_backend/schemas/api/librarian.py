"""Librarian API schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from paper_plane_x_backend.models import PaperSortKey, SortOrder
from paper_plane_x_backend.schemas.agent_io import (
    GlobalFinderPaperSummary,
    GlobalFinderStats,
)


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


class LibrarianGlobalFinderResponse(BaseModel):
    """项目级文献总览响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str
    papers: list[GlobalFinderPaperSummary] = Field(
        default_factory=list[GlobalFinderPaperSummary],
        description="项目下的论文基础摘要列表",
    )
    stats: GlobalFinderStats = Field(..., description="全局查找统计信息")
    agent_summary: str | None = Field(default=None)


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

    # query_expr 不再在 schema 层强制验证语法合法性；
    # 运行时若 DSL 解析失败会自动退化为简单模式搜索（全字段 CONTAINS）。


class LibrarianUnifiedSearchResponse(BaseModel):
    """统一搜索响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str | None = Field(default=None, description="项目作用域")
    limit: int = Field(..., description="返回条数")
    offset: int = Field(..., description="偏移量")
    total: int = Field(..., description="命中总数")
    paper_ids: list[str] = Field(..., description="命中论文 ID 列表")


class LibrarianQueryBuilderRequest(BaseModel):
    """自然语言转 DSL 查询请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    query: str = Field(
        ...,
        min_length=1,
        description="用户输入的自然语言查询描述",
    )
    project_context: str | None = Field(
        default=None,
        description="可选的项目上下文信息",
    )


class LibrarianQueryBuilderResponse(BaseModel):
    """自然语言转 DSL 查询响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    query_expr: str = Field(
        ...,
        description="生成的 DSL 条件表达式字符串",
    )
    explanation: str = Field(
        ...,
        description="对生成查询的简要说明",
    )


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
