"""Librarian 工具集合。"""

from typing import Any

from paper_plane_x_backend.core.agent_runtime import AgentExecutionError
from paper_plane_x_backend.core.agent_runtime.tooling import tool
from paper_plane_x_backend.core.query_parser import (
    LibrarianQueryError,
    parse_librarian_query_expr_or_fallback,
)
from paper_plane_x_backend.services.app_settings import get_app_settings_repo
from paper_plane_x_backend.services.database import get_db
from paper_plane_x_backend.services.librarian import (
    build_field_paths_guide,
    deep_dive,
    global_finder_by_project,
    matrix_fetch_by_paths,
)
from paper_plane_x_backend.services.paper.repository import (
    PaperQueryRepository,
    PaperRepository,
    PaperRepositoryError,
)
from paper_plane_x_backend.services.project.repository import ProjectRepository
from paper_plane_x_backend.utils.schema_utils import strip_citations_recursively


def _build_librarian_tool_shared_guides() -> dict[str, str]:
    """构造 ToolRegistry 共享的 Librarian 说明。"""
    return {
        "Librarian Field Paths": build_field_paths_guide(),
        "Librarian Query Rules": "\n".join(
            [
                "query_expr 使用括号、AND、OR 组织条件。",
                "文本字段统一使用 CONTAINS，例如 (meta.title CONTAINS transformer)。",
                '如果要检索的文本字段包含空格或特殊字符，请使用双引号括起来，例如 (meta.abstract CONTAINS "deep learning")。',
                "年份仅支持 year / meta.year 的 BETWEEN，例如 (meta.year BETWEEN [2020, 2025])。",
                "搜索会自动过滤 extraction / fact check 状态不合格的论文。",
            ]
        ),
    }


@tool(
    name="global_finder",
    description=(
        "聚合当前 project 下全部已关联论文的基础信息，返回项目级文献总览。"
        "适用场景：在开始检索、写作或对比前，先快速建立对整批文献的整体感觉。"
        "\n输入：无需显式输入 project_id；该参数会在运行时自动注入。"
        "\n输出：成功时返回 {project_id, papers, stats}；失败时返回 {project_id, error}。"
        "\n说明：stats 包含 paper_count、年份分布统计和热门标签统计。"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_librarian_tool_shared_guides(),
)
def global_finder(
    project_id: str | None = None,
) -> dict[str, Any]:
    repo = PaperQueryRepository(get_db())
    project_repo = ProjectRepository(get_db())
    try:
        return global_finder_by_project(
            paper_repo=repo,
            project_repo=project_repo,
            project_id=project_id or "",
            top_tags_limit=get_app_settings_repo().get().librarian.top_tags_limit,
        )
    except PaperRepositoryError as exc:
        return {
            "project_id": project_id,
            "error": exc.message,
        }


@tool(
    name="matrix_compare",
    description=(
        "跨多篇论文按 field_paths 读取结构化字段，返回二维矩阵。"
        "适用场景：横向比较多篇论文在 quick_scan、synthesis_data、analysis_report 等路径上的内容差异。"
        "\n输入：paper_ids, field_paths。"
        "\n输出：成功时返回 {paper_ids, field_paths, items}；失败时返回 {paper_ids, field_paths, error}。"
        "\n说明：field_paths 的完整规则见共享 guide；返回结果会递归剥离 citations 以减少上下文体积。"
    ),
    shared_guides=_build_librarian_tool_shared_guides(),
)
def matrix_compare(
    paper_ids: list[str],
    field_paths: list[str],
) -> dict[str, Any]:
    repo = PaperQueryRepository(get_db())
    try:
        matrix = strip_citations_recursively(
            matrix_fetch_by_paths(
                repo=repo,
                paper_ids=paper_ids,
                field_paths=field_paths,
            )
        )
    except PaperRepositoryError as exc:
        return {
            "paper_ids": paper_ids,
            "field_paths": field_paths,
            "error": exc.message,
        }
    return {
        "paper_ids": paper_ids,
        "field_paths": field_paths,
        "items": matrix,
    }


@tool(
    name="search_paper",
    description=(
        "在当前 project 作用域内执行统一条件搜索，返回命中的 paper_id 列表。"
        "适用场景：先筛出符合条件的论文集合，再交给 matrix_compare 或后续分析步骤。"
        "\n输入：query_expr，以及可选的 limit / offset。"
        "\n输出：成功时返回 {query_expr, limit, offset, total, paper_ids}；失败时返回 {query_expr, limit, offset, error}。"
        "\n说明：query_expr 的字段路径与语法规则见共享 guide；project_id 会在运行时自动注入，对 AI 不可见。"
    ),
    context_params={"project_id": "project_id"},
    shared_guides=_build_librarian_tool_shared_guides(),
)
def search_paper(
    query_expr: str,
    limit: int = 20,
    offset: int = 0,
    project_id: str | None = None,
) -> dict[str, Any]:
    repo = PaperQueryRepository(get_db())
    try:
        query_group = parse_librarian_query_expr_or_fallback(query_expr)
        paper_ids, total = repo.search_paper(
            project_id=project_id,
            paper_id=None,
            query_group=query_group,
            limit=limit,
            offset=offset,
        )
    except (PaperRepositoryError, LibrarianQueryError) as exc:
        return {
            "query_expr": query_expr,
            "limit": limit,
            "offset": offset,
            "error": exc.message,
        }

    return {
        "query_expr": query_expr,
        "limit": limit,
        "offset": offset,
        "total": total,
        "paper_ids": paper_ids,
    }


@tool(
    name="deep_dive",
    description=(
        "针对单篇论文的特定问题进行深度挖掘，返回结构化的分析结果。"
        "适用场景：对单篇论文进行深入理解，或在写作过程中需要从某篇论文中提取特定信息时。"
        "\n输入：paper_id, question。"
        "\n输出：成功时返回 {is_answered, answer, citations}；失败时返回 {paper_id, question, error}。"
        "\n说明：answer 的结构详见 DeepDiverAgentOutput 模型定义"
    ),
    context_params={"caller": "_caller_agent_name", "caller_id": "_caller_trace_id"},
)
async def deep_dive_tool(
    paper_id: str,
    question: str = "",
    caller: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    if not paper_id:
        return {
            "paper_id": paper_id,
            "question": question,
            "error": "paper_id is required",
        }
    try:
        result = await deep_dive(
            repo=PaperRepository(get_db()),
            paper_id=paper_id,
            question=question,
            caller=caller,
            caller_id=caller_id,
        )
    except (PaperRepositoryError, AgentExecutionError) as exc:
        return {
            "paper_id": paper_id,
            "question": question,
            "error": exc.message,
        }
    return {
        "paper_id": paper_id,
        "question": question,
        "answer": strip_citations_recursively(result["result"]),
    }


# TODO 返回值有问题
