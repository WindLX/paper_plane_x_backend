"""Librarian 编排服务。"""

from __future__ import annotations

import logging
from typing import Any, NoReturn, cast

from paper_plane_x_backend.agents.global_finder import GlobalFinderAgent
from paper_plane_x_backend.core.query_parser import (
    LibrarianQueryError,
    build_librarian_simple_query,
    parse_librarian_query_expr,
)
from paper_plane_x_backend.models import PaperSortKey, SortOrder
from paper_plane_x_backend.schemas.agent_io import (
    GlobalFinderAgentInput,
    GlobalFinderPaperSummary,
    GlobalFinderStats,
    QuickScan,
    TagCount,
    YearDistribution,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.librarian import (
    build_librarian_guide_payload,
    global_finder_by_project,
    matrix_fetch_by_paths,
)
from paper_plane_x_backend.services.paper.repository import (
    PaperQueryRepository,
    PaperRepository,
    PaperRepositoryError,
)
from paper_plane_x_backend.services.project.repository import (
    ProjectRepository as ProjectRepo,
)

logger = logging.getLogger(__name__)


def _coerce_int(value: object) -> int:
    return value if isinstance(value, int) else 0


class LibrarianDomainError(Exception):
    """Librarian 业务异常（由 Router 映射为 HTTP 错误）。"""

    def __init__(self, status_code: int, detail: object) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class LibrarianOrchestrator:
    """Librarian 业务编排入口。"""

    def __init__(self, db: Database) -> None:
        self.query_repo = PaperQueryRepository(db)
        self.paper_repo = PaperRepository(db)
        self.project_repo = ProjectRepo(db)

    def _raise_repo_error(
        self,
        exc: PaperRepositoryError | LibrarianQueryError,
    ) -> NoReturn:
        error_map = {
            "not_found": 404,
            "invalid_field": 422,
            "invalid_sort": 422,
            "invalid_operator": 422,
            "invalid_value": 422,
            "invalid_query_expr": 422,
            "invalid_query_group": 422,
            "invalid_fts_query": 400,
            "bad_request": 400,
        }
        status_code = error_map.get(exc.error_code, 400)
        logger.warning(
            "event=librarian.repository_error status=%s code=%s detail=%s",
            status_code,
            exc.error_code,
            exc.message,
        )
        raise LibrarianDomainError(
            status_code,
            {
                "code": exc.error_code,
                "message": exc.message,
            },
        )

    def build_guide(self) -> dict[str, object]:
        return build_librarian_guide_payload()

    def run_search(
        self,
        *,
        project_id: str | None,
        paper_id: str | None,
        simple_query: str | None,
        query_expr: str | None,
        limit: int,
        offset: int,
        sort_by: PaperSortKey,
        sort_order: SortOrder,
        only_completed: bool = True,
    ) -> tuple[list[str], int]:
        try:
            query_group = None
            if simple_query:
                query_group = build_librarian_simple_query(simple_query)
            elif query_expr:
                query_group = parse_librarian_query_expr(query_expr)
            return self.query_repo.search_paper(
                project_id=project_id,
                paper_id=paper_id,
                query_group=query_group,
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                sort_order=sort_order,
                only_completed=only_completed,
            )
        except (PaperRepositoryError, LibrarianQueryError) as exc:
            self._raise_repo_error(exc)
        raise LibrarianDomainError(500, "Failed to search papers")

    async def run_global_finder(
        self,
        *,
        project_id: str,
        top_tags_limit: int,
        caller: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            payload = global_finder_by_project(
                paper_repo=self.query_repo,
                project_repo=self.project_repo,
                project_id=project_id,
                top_tags_limit=top_tags_limit,
            )
        except PaperRepositoryError as exc:
            self._raise_repo_error(exc)

        agent_summary: str | None = cast(str | None, payload.get("agent_summary"))
        if not agent_summary or not agent_summary.strip():
            agent_summary = await self._generate_agent_summary(
                project_id=project_id,
                payload=payload,
                caller=caller,
                caller_id=caller_id,
            )
            payload["agent_summary"] = agent_summary

        return payload

    async def force_generate_agent_summary(
        self,
        *,
        project_id: str,
        top_tags_limit: int,
        caller: str | None = None,
        caller_id: str | None = None,
    ) -> str | None:
        """强制重新生成项目的 agent_summary，无论当前是否已存在。"""
        try:
            payload = global_finder_by_project(
                paper_repo=self.query_repo,
                project_repo=self.project_repo,
                project_id=project_id,
                top_tags_limit=top_tags_limit,
            )
        except PaperRepositoryError as exc:
            self._raise_repo_error(exc)

        agent_summary = await self._generate_agent_summary(
            project_id=project_id,
            payload=payload,
            caller=caller,
            caller_id=caller_id,
        )
        return agent_summary

    async def _generate_agent_summary(
        self,
        *,
        project_id: str,
        payload: dict[str, Any],
        caller: str | None,
        caller_id: str | None,
    ) -> str | None:
        """调用 GlobalFinderAgent 生成项目文献库总结并保存。"""
        project = self.project_repo.get(project_id)
        project_name = project.name if project else None

        papers_raw_obj = payload.get("papers", [])
        papers_raw: list[object] = (
            cast(list[object], papers_raw_obj)
            if isinstance(papers_raw_obj, list)
            else cast(list[object], [])
        )
        stats_raw_obj = payload.get("stats", {})
        stats_raw: dict[str, Any] = (
            cast(dict[str, Any], stats_raw_obj)
            if isinstance(stats_raw_obj, dict)
            else cast(dict[str, Any], {})
        )

        paper_summaries: list[GlobalFinderPaperSummary] = []
        for p in papers_raw:
            if not isinstance(p, dict):
                continue
            paper_dict = cast(dict[str, Any], p)
            qs_raw = paper_dict.get("quick_scan")
            qs_model = None
            if isinstance(qs_raw, dict):
                try:
                    qs_model = QuickScan.model_validate(qs_raw)
                except Exception:
                    qs_model = None
            paper_summaries.append(
                GlobalFinderPaperSummary(
                    paper_id=str(paper_dict.get("paper_id") or ""),
                    title=(
                        paper_dict.get("title")
                        if isinstance(paper_dict.get("title"), str)
                        else None
                    ),
                    authors=[
                        str(a)
                        for a in cast(list[object], paper_dict.get("authors", []))
                        if isinstance(a, str)
                    ],
                    year=(
                        paper_dict.get("year")
                        if isinstance(paper_dict.get("year"), int)
                        else None
                    ),
                    quick_scan=qs_model,
                )
            )

        year_dist_raw_obj = stats_raw.get("year_distribution", {})
        year_dist_raw = (
            cast(dict[str, Any], year_dist_raw_obj)
            if isinstance(year_dist_raw_obj, dict)
            else cast(dict[str, Any], {})
        )
        available_count: int = _coerce_int(year_dist_raw.get("available_count"))
        missing_count: int = _coerce_int(year_dist_raw.get("missing_count"))
        outlier_count: int = _coerce_int(year_dist_raw.get("outlier_count"))
        low_outlier_count: int = _coerce_int(year_dist_raw.get("low_outlier_count"))
        high_outlier_count: int = _coerce_int(year_dist_raw.get("high_outlier_count"))
        year_dist = YearDistribution(
            available_count=available_count,
            missing_count=missing_count,
            mean=(
                year_dist_raw.get("mean")
                if isinstance(year_dist_raw.get("mean"), (int, float))
                else None
            ),
            variance=(
                year_dist_raw.get("variance")
                if isinstance(year_dist_raw.get("variance"), (int, float))
                else None
            ),
            median=(
                year_dist_raw.get("median")
                if isinstance(year_dist_raw.get("median"), (int, float))
                else None
            ),
            mode_years=[
                year
                for year in cast(list[object], year_dist_raw.get("mode_years", []))
                if isinstance(year, int)
            ],
            q25=(
                year_dist_raw.get("q25")
                if isinstance(year_dist_raw.get("q25"), (int, float))
                else None
            ),
            q75=(
                year_dist_raw.get("q75")
                if isinstance(year_dist_raw.get("q75"), (int, float))
                else None
            ),
            outlier_count=outlier_count,
            low_outlier_count=low_outlier_count,
            high_outlier_count=high_outlier_count,
        )

        top_tags_raw_obj = stats_raw.get("top_tags", [])
        top_tags_raw = (
            cast(list[object], top_tags_raw_obj)
            if isinstance(top_tags_raw_obj, list)
            else cast(list[object], [])
        )
        top_tags = [
            TagCount(
                tag=str(tag_dict.get("tag", "")),
                count=(
                    tag_dict.get("count", 0)
                    if isinstance(tag_dict.get("count"), int)
                    else 0
                ),
            )
            for t in top_tags_raw
            if isinstance(t, dict)
            for tag_dict in [cast(dict[str, Any], t)]
        ]

        stats = GlobalFinderStats(
            paper_count=(
                stats_raw.get("paper_count", 0)
                if isinstance(stats_raw.get("paper_count"), int)
                else 0
            ),
            top_tags_limit=(
                stats_raw.get("top_tags_limit", 0)
                if isinstance(stats_raw.get("top_tags_limit"), int)
                else 0
            ),
            year_range=(
                stats_raw.get("year_range")
                if isinstance(stats_raw.get("year_range"), str)
                else None
            ),
            year_distribution=year_dist,
            top_tags=top_tags,
        )

        agent = GlobalFinderAgent(caller=caller, caller_id=caller_id)
        agent.append_user_message(
            GlobalFinderAgentInput(
                project_name=project_name,
                papers=paper_summaries,
                stats=stats,
            )
        )
        try:
            result = await agent.run()
        except Exception as exc:
            logger.warning(
                "event=global_finder.agent_failed project_id=%s error=%s",
                project_id,
                exc,
            )
            return None

        summary = result.agent_summary
        if summary:
            self.project_repo.set_agent_summary(project_id, summary)
            logger.info(
                "event=global_finder.agent_summary_generated project_id=%s trace_ids=%s",
                project_id,
                agent.trace_ids,
            )
        return summary

    def run_matrix(
        self,
        *,
        paper_ids: list[str],
        field_paths: list[str],
    ) -> dict[str, dict[str, Any]]:
        try:
            return matrix_fetch_by_paths(
                repo=self.query_repo,
                paper_ids=paper_ids,
                field_paths=field_paths,
            )
        except PaperRepositoryError as exc:
            self._raise_repo_error(exc)
        raise LibrarianDomainError(500, "Failed to fetch matrix")
