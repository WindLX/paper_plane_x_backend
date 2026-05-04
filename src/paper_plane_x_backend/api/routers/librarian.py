"""Librarian 查询与投影路由。"""

import logging
from typing import NoReturn

from fastapi import APIRouter, HTTPException

from paper_plane_x_backend.agents.query_builder import QueryBuilderAgent
from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.core.query_parser import (
    LibrarianQueryError,
    parse_librarian_query_expr,
)
from paper_plane_x_backend.schemas.agent_io.librarian import QueryBuilderAgentInput
from paper_plane_x_backend.schemas.api import (
    LibrarianAgentSummaryResponse,
    LibrarianGlobalFinderRequest,
    LibrarianGlobalFinderResponse,
    LibrarianQueryBuilderRequest,
    LibrarianQueryBuilderResponse,
    LibrarianUnifiedSearchRequest,
    LibrarianUnifiedSearchResponse,
)
from paper_plane_x_backend.services.app_settings import get_app_settings_repo
from paper_plane_x_backend.services.orchestrators.librarian import (
    LibrarianDomainError,
    LibrarianOrchestrator,
)

router = APIRouter(prefix="/librarian", tags=["librarian"])
logger = logging.getLogger(__name__)


def _build_orchestrator(db: DBDep) -> LibrarianOrchestrator:
    return LibrarianOrchestrator(db)


def _raise_as_http(exc: LibrarianDomainError) -> NoReturn:
    logger.warning(
        "event=librarian.domain_error status=%s detail=%s",
        exc.status_code,
        exc.detail,
    )
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.detail,
    )


@router.post(
    "/search",
    response_model=LibrarianUnifiedSearchResponse,
    summary="统一条件搜索",
)
def run_search_paper(
    request: LibrarianUnifiedSearchRequest,
    db: DBDep,
) -> LibrarianUnifiedSearchResponse:
    orchestrator = _build_orchestrator(db)
    try:
        paper_ids, total = orchestrator.run_search(
            project_id=request.project_id,
            paper_id=request.paper_id,
            query_expr=request.query_expr,
            limit=request.limit,
            offset=request.offset,
            sort_by=request.sort_by,
            sort_order=request.sort_order,
        )
    except LibrarianDomainError as exc:
        _raise_as_http(exc)

    return LibrarianUnifiedSearchResponse(
        project_id=request.project_id,
        limit=request.limit,
        offset=request.offset,
        total=total,
        paper_ids=paper_ids,
    )


@router.post(
    "/global-finder",
    response_model=LibrarianGlobalFinderResponse,
    summary="按项目生成文献全局总览",
)
async def run_global_finder(
    request: LibrarianGlobalFinderRequest,
    db: DBDep,
) -> LibrarianGlobalFinderResponse:
    orchestrator = _build_orchestrator(db)
    try:
        payload = await orchestrator.run_global_finder(
            project_id=request.project_id,
            top_tags_limit=get_app_settings_repo().get().librarian.top_tags_limit,
            caller="api",
            caller_id=None,
        )
    except LibrarianDomainError as exc:
        _raise_as_http(exc)

    return LibrarianGlobalFinderResponse.model_validate(payload)


@router.post(
    "/global-finder/agent-summary",
    response_model=LibrarianAgentSummaryResponse,
    summary="强制重新生成项目文献总结",
)
async def force_global_finder_agent_summary(
    request: LibrarianGlobalFinderRequest,
    db: DBDep,
) -> LibrarianAgentSummaryResponse:
    orchestrator = _build_orchestrator(db)
    try:
        agent_summary = await orchestrator.force_generate_agent_summary(
            project_id=request.project_id,
            top_tags_limit=get_app_settings_repo().get().librarian.top_tags_limit,
            caller="api",
            caller_id=None,
        )
    except LibrarianDomainError as exc:
        _raise_as_http(exc)

    return LibrarianAgentSummaryResponse(
        project_id=request.project_id,
        agent_summary=agent_summary,
    )


@router.post(
    "/query-builder",
    response_model=LibrarianQueryBuilderResponse,
    summary="自然语言转 DSL 查询表达式",
)
async def run_query_builder(
    request: LibrarianQueryBuilderRequest,
) -> LibrarianQueryBuilderResponse:
    """将用户自然语言查询转换为 Librarian DSL 条件表达式。"""
    agent = QueryBuilderAgent()
    agent.append_user_message(
        QueryBuilderAgentInput(
            query=request.query,
            project_context=request.project_context,
        )
    )
    try:
        result = await agent.run()
    except Exception as exc:
        logger.exception("event=query_builder.failed query=%s", request.query)
        raise HTTPException(
            status_code=500,
            detail=f"Query builder failed: {exc}",
        ) from exc

    # 验证生成的 query_expr 语法合法性
    try:
        parse_librarian_query_expr(result.query_expr)
    except LibrarianQueryError as exc:
        logger.warning(
            "event=query_builder.invalid_expr query=%s expr=%s error=%s",
            request.query,
            result.query_expr,
            exc.message,
        )
        raise HTTPException(
            status_code=422,
            detail=f"Generated invalid query_expr: {exc.message}",
        ) from exc

    return LibrarianQueryBuilderResponse(
        query_expr=result.query_expr,
        explanation=result.explanation,
    )
