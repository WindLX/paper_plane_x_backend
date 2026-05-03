from pydantic import BaseModel, Field

from .base import CitedText
from .data_processor import QuickScan


class DeepDiverAgentInput(BaseModel):
    md_content: str = Field(..., description="原始 Markdown 文本内容")
    images: list[str] = Field(
        default_factory=list,
        description="原始 Markdown 中提取的图片数据列表，元素是 base64 编码的图片数据",
    )
    question: str = Field(
        ..., description="用户/上游 Agent 提出的具体问题，要求基于论文内容进行回答"
    )


class DeepDiverAgentOutput(BaseModel):
    is_answered: bool = Field(
        ...,
        description="论文原文中是否真正包含了能回答该问题的信息？如果是，填 true；如果原文未提及，填 false。",
    )
    answer: CitedText = Field(
        ...,
        description="对问题的直接、精确解答。如果 is_answered 为 false，请简要说明原文为何无法回答。",
    )


class QueryBuilderAgentInput(BaseModel):
    """QueryBuilder Agent 输入：用户自然语言查询。"""

    query: str = Field(
        ...,
        description="用户输入的自然语言查询描述，例如：'我想查询最近五年关于 transformer 的论文'",
    )
    project_context: str | None = Field(
        default=None,
        description="可选的项目上下文信息，如项目名、当前关注的领域等，帮助生成更精准的查询。",
    )


class QueryBuilderAgentOutput(BaseModel):
    """QueryBuilder Agent 输出：DSL 查询表达式。"""

    query_expr: str = Field(
        ...,
        description="生成的 DSL 条件表达式字符串，可直接用于 Librarian 统一搜索 API。例如：(meta.title CONTAINS transformer) AND (meta.year BETWEEN [2021, 2026])",
    )
    explanation: str = Field(
        ...,
        description="对生成查询的简要中文说明，帮助用户理解查询逻辑。",
    )


class YearDistribution(BaseModel):
    """年份分布统计。"""

    available_count: int = Field(..., description="有年份信息的论文数")
    missing_count: int = Field(..., description="无年份信息的论文数")
    mean: float | None = Field(default=None, description="平均年份")
    variance: float | None = Field(default=None, description="年份方差")
    median: float | None = Field(default=None, description="中位数年份")
    mode_years: list[int] = Field(default_factory=list, description="众数年份")
    q25: float | None = Field(default=None, description="25%分位数")
    q75: float | None = Field(default=None, description="75%分位数")
    outlier_count: int = Field(default=0, description="异常值数量")
    low_outlier_count: int = Field(default=0, description="低异常值数量")
    high_outlier_count: int = Field(default=0, description="高异常值数量")


class TagCount(BaseModel):
    """标签统计项。"""

    tag: str = Field(..., description="标签名称")
    count: int = Field(..., description="标签出现次数")


class GlobalFinderPaperSummary(BaseModel):
    """Global Finder 中的论文基础摘要。"""

    paper_id: str = Field(..., description="论文 ID")
    title: str | None = Field(default=None, description="论文标题")
    authors: list[str] = Field(default_factory=list[str], description="作者列表")
    year: int | None = Field(default=None, description="论文年份")
    quick_scan: QuickScan | None = Field(default=None, description="快速扫描结果")


class GlobalFinderStats(BaseModel):
    """Global Finder 统计信息。"""

    paper_count: int = Field(..., description="论文总数")
    top_tags_limit: int = Field(..., description="Top 标签限制数量")
    year_range: str | None = Field(
        default=None, description="论文年份范围，例如 2010-2023"
    )
    year_distribution: YearDistribution = Field(..., description="论文年份分布统计")
    top_tags: list[TagCount] = Field(
        default_factory=list[TagCount], description="Top 标签统计列表"
    )


class GlobalFinderAgentInput(BaseModel):
    """GlobalFinder Agent 输入：项目文献库聚合信息。"""

    project_name: str | None = Field(
        default=None,
        description="项目名称",
    )
    papers: list[GlobalFinderPaperSummary] = Field(
        default_factory=list[GlobalFinderPaperSummary],
        description="项目下的论文基础摘要列表",
    )
    stats: GlobalFinderStats = Field(..., description="全局查找统计信息")


class GlobalFinderAgentOutput(BaseModel):
    """GlobalFinder Agent 输出：项目文献库整体总结。"""

    agent_summary: str = Field(
        ...,
        description="对项目文献库的整体中文总结，不超过500字。",
    )
