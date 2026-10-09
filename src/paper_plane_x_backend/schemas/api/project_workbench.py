"""Project workbench API schemas (activities + readonly overview)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from paper_plane_x_backend.schemas.agent_io import YearDistribution

ActivityCategory = Literal["project", "paper", "file", "task", "agent", "export"]
ActivityStatus = Literal["info", "queued", "running", "completed", "failed", "canceled"]

# The shared contract names the year distribution shape used by the existing
# Librarian global finder response; it is the same model under a stable alias.
LibrarianGlobalFinderYearDistribution = YearDistribution


class ActivityResponse(BaseModel):
    """Single project activity."""

    model_config = ConfigDict(strict=True, extra="forbid")

    activity_id: str = Field(..., description="活动 ID")
    project_id: str = Field(..., description="项目 ID")
    category: ActivityCategory = Field(..., description="活动分类")
    event_type: str = Field(..., description="事件代码（前端拼接人类可读摘要）")
    status: ActivityStatus = Field(..., description="活动状态")
    object_name: str | None = Field(default=None, description="对象名称")
    paper_id: str | None = Field(default=None, description="关联论文 ID")
    file_path: str | None = Field(default=None, description="关联文件路径")
    task_id: str | None = Field(default=None, description="关联任务 ID")
    trace_ids: list[str] = Field(default_factory=list[str], description="关联 trace ID")
    created_at: str = Field(..., description="创建时间 (ISO 8601)")
    updated_at: str = Field(..., description="更新时间 (ISO 8601)")
    started_at: str | None = Field(default=None, description="开始时间 (ISO 8601)")
    finished_at: str | None = Field(default=None, description="结束时间 (ISO 8601)")
    error: str | None = Field(default=None, description="错误信息")
    retry_of_task_id: str | None = Field(default=None, description="重试来源任务 ID")
    task_exists: bool = Field(default=False, description="关联任务是否仍然存在")
    detail: dict[str, Any] = Field(
        default_factory=dict[str, Any], description="附加明细"
    )


class ActivityListResponse(BaseModel):
    """Paginated project activities."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[ActivityResponse] = Field(..., description="活动列表")
    total: int = Field(..., description="过滤后总数")
    offset: int = Field(..., description="偏移量")
    limit: int = Field(..., description="每页数量")


class ProjectOverviewStats(BaseModel):
    """Aggregate counters shown on the project overview."""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_count: int = Field(..., description="项目论文总数")
    parsed_count: int = Field(..., description="已解析（有 Markdown）论文数")
    active_task_count: int = Field(..., description="排队/运行/取消中的任务数")
    attention_count: int = Field(..., description="需要关注的条数")


class ProjectAttentionItem(BaseModel):
    """One item needing attention."""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_id: str = Field(..., description="论文 ID")
    title: str | None = Field(default=None, description="论文标题")
    stage: str = Field(..., description="关注阶段代码")
    error: str | None = Field(default=None, description="错误信息")
    task_id: str | None = Field(default=None, description="关联任务 ID")


class ProjectRecentPaper(BaseModel):
    """Recently updated project paper."""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_id: str = Field(..., description="论文 ID")
    title: str | None = Field(default=None, description="论文标题")
    updated_at: str | None = Field(default=None, description="更新时间 (ISO 8601)")


class ProjectRecentFile(BaseModel):
    """Recently modified project sandbox file."""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_path: str = Field(..., description="项目内相对路径")
    name: str = Field(..., description="文件名")
    kind: Literal["text", "image"] = Field(..., description="文件类型")
    size: int = Field(..., description="文件字节数")
    updated_at: str | None = Field(default=None, description="修改时间 (ISO 8601)")


class ProjectTopTag(BaseModel):
    """Tag frequency item."""

    model_config = ConfigDict(strict=True, extra="forbid")

    tag: str = Field(..., description="标签")
    count: int = Field(..., description="出现次数")


class ProjectOverviewResponse(BaseModel):
    """Readonly project workbench overview."""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str = Field(..., description="项目 ID")
    agent_summary: str | None = Field(default=None, description="Agent 生成的项目总结")
    stats: ProjectOverviewStats = Field(..., description="聚合统计")
    attention_items: list[ProjectAttentionItem] = Field(
        default_factory=list[ProjectAttentionItem], description="需要关注的事项"
    )
    recent_papers: list[ProjectRecentPaper] = Field(
        default_factory=list[ProjectRecentPaper],
        description="最近更新的论文（最多 5 条）",
    )
    recent_files: list[ProjectRecentFile] = Field(
        default_factory=list[ProjectRecentFile],
        description="最近修改的沙箱文件（最多 5 条）",
    )
    recent_activities: list[ActivityResponse] = Field(
        default_factory=list[ActivityResponse], description="最近活动（最多 5 条）"
    )
    top_tags: list[ProjectTopTag] = Field(
        default_factory=list[ProjectTopTag], description="热门标签"
    )
    year_distribution: LibrarianGlobalFinderYearDistribution = Field(
        ..., description="论文年份分布统计"
    )
    year_range: str | None = Field(default=None, description="年份范围")
    section_errors: dict[str, str] = Field(
        default_factory=dict[str, str], description="局部聚合失败信息"
    )


__all__ = [
    "ActivityCategory",
    "ActivityListResponse",
    "ActivityResponse",
    "ActivityStatus",
    "LibrarianGlobalFinderYearDistribution",
    "ProjectAttentionItem",
    "ProjectOverviewResponse",
    "ProjectOverviewStats",
    "ProjectRecentFile",
    "ProjectRecentPaper",
    "ProjectTopTag",
]
