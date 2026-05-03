"""Project API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreateRequest(BaseModel):
    """创建项目请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=200, description="项目名称")
    description: str | None = Field(default=None, description="项目描述")
    agent_summary: str | None = Field(default=None, description="Agent 生成的项目总结")


class ProjectUpdateRequest(BaseModel):
    """更新项目请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(
        default=None, min_length=1, max_length=200, description="项目名称"
    )
    description: str | None = Field(default=None, description="项目描述")
    agent_summary: str | None = Field(default=None, description="Agent 生成的项目总结")


class ProjectResponse(BaseModel):
    """项目响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str = Field(..., description="项目 ID")
    name: str = Field(..., description="项目名称")
    description: str | None = Field(default=None, description="项目描述")
    agent_summary: str | None = Field(default=None, description="Agent 生成的项目总结")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    operation_logs: list[dict[str, Any]] = Field(
        default_factory=list, description="项目操作日志"
    )


class ProjectListResponse(BaseModel):
    """项目列表响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[ProjectResponse] = Field(..., description="项目列表")
    total: int = Field(..., description="总数")
    offset: int = Field(..., description="偏移量")
    limit: int = Field(..., description="每页数量")


PaperExportField = Literal[
    "paper_id",
    "project_ids",
    "title",
    "authors",
    "year",
    "publication",
    "doi",
    "custom_meta",
    "raw_pdf_path",
    "raw_pdf_sha256",
    "images_paths",
    "extraction_status",
    "extraction_fact_check_status",
    "analysis_fact_check_status",
    "extraction_retry_count",
    "analysis_retry_count",
    "created_at",
    "updated_at",
    "quick_scan",
    "synthesis_data",
    "analysis_report",
    "extraction_fact_check_result",
    "analysis_fact_check_result",
]


class ProjectExportRequest(BaseModel):
    """导出项目请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    fields: list[PaperExportField] = Field(
        default_factory=lambda: [
            "paper_id",
            "project_ids",
            "title",
            "authors",
            "year",
            "publication",
            "doi",
            "custom_meta",
            "raw_pdf_path",
            "raw_pdf_sha256",
            "images_paths",
            "extraction_status",
            "extraction_fact_check_status",
            "analysis_fact_check_status",
            "extraction_retry_count",
            "analysis_retry_count",
            "created_at",
            "updated_at",
            "quick_scan",
            "synthesis_data",
            "analysis_report",
            "extraction_fact_check_result",
            "analysis_fact_check_result",
        ],
        description="需要导出的 PaperDetailResponse 字段列表",
    )
    citations_mode: Literal["keep", "strip"] = Field(
        default="keep",
        description=(
            "对于 quick_scan / synthesis_data / analysis_report："
            "keep=保留 citations；strip=递归移除 citations"
        ),
    )
