"""Librarian 编排服务。"""

from __future__ import annotations

import logging
from typing import Any, NoReturn

from paper_plane_x_backend.agents.global_finder import GlobalFinderAgent
from paper_plane_x_backend.core.query_parser import (
    LibrarianQueryError,
    parse_librarian_query_expr_or_fallback,
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
        query_expr: str | None,
        limit: int,
        offset: int,
        sort_by: PaperSortKey,
        sort_order: SortOrder,
    ) -> tuple[list[str], int]:
        try:
            query_group = (
                parse_librarian_query_expr_or_fallback(query_expr)
                if query_expr
                else None
            )
            return self.query_repo.search_paper(
                project_id=project_id,
                paper_id=paper_id,
                query_group=query_group,
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                sort_order=sort_order,
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

        agent_summary = payload.get("agent_summary")
        if agent_summary is None:
            agent_summary = await self._generate_agent_summary(
                project_id=project_id,
                payload=payload,
                caller=caller,
                caller_id=caller_id,
            )
            payload["agent_summary"] = agent_summary

        return payload

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

        papers_raw = payload.get("papers", [])
        stats_raw = payload.get("stats", {})

        paper_summaries: list[GlobalFinderPaperSummary] = []
        for p in papers_raw:
            if not isinstance(p, dict):
                continue
            qs_raw = p.get("quick_scan")
            qs_model = None
            if isinstance(qs_raw, dict):
                try:
                    qs_model = QuickScan.model_validate(qs_raw)
                except Exception:
                    qs_model = None
            paper_summaries.append(
                GlobalFinderPaperSummary(
                    paper_id=str(p.get("paper_id") or ""),
                    title=p.get("title") if isinstance(p.get("title"), str) else None,
                    authors=[
                        str(a) for a in p.get("authors", []) if isinstance(a, str)
                    ],
                    year=p.get("year") if isinstance(p.get("year"), int) else None,
                    quick_scan=qs_model,
                )
            )

        year_dist_raw = (
            stats_raw.get("year_distribution", {})
            if isinstance(stats_raw, dict)
            else {}
        )
        year_dist = YearDistribution(
            available_count=year_dist_raw.get("available_count", 0),
            missing_count=year_dist_raw.get("missing_count", 0),
            mean=year_dist_raw.get("mean"),
            variance=year_dist_raw.get("variance"),
            median=year_dist_raw.get("median"),
            mode_years=year_dist_raw.get("mode_years", []),
            q25=year_dist_raw.get("q25"),
            q75=year_dist_raw.get("q75"),
            outlier_count=year_dist_raw.get("outlier_count", 0),
            low_outlier_count=year_dist_raw.get("low_outlier_count", 0),
            high_outlier_count=year_dist_raw.get("high_outlier_count", 0),
        )

        top_tags_raw = (
            stats_raw.get("top_tags", []) if isinstance(stats_raw, dict) else []
        )
        top_tags = [
            TagCount(tag=t.get("tag", ""), count=t.get("count", 0))
            for t in top_tags_raw
            if isinstance(t, dict)
        ]

        stats = GlobalFinderStats(
            paper_count=(
                stats_raw.get("paper_count", 0) if isinstance(stats_raw, dict) else 0
            ),
            top_tags_limit=(
                stats_raw.get("top_tags_limit", 0) if isinstance(stats_raw, dict) else 0
            ),
            year_range=(
                stats_raw.get("year_range") if isinstance(stats_raw, dict) else None
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
