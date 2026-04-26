"""Librarian 查询与投影路由。"""

import logging
from typing import NoReturn

from fastapi import APIRouter, HTTPException

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.schemas import (
    LibrarianGlobalFinderRequest,
    LibrarianGlobalFinderResponse,
    LibrarianGuideResponse,
    LibrarianMatrixRequest,
    LibrarianMatrixResponse,
    LibrarianProjectionRequest,
    LibrarianProjectionResponse,
    LibrarianUnifiedSearchRequest,
    LibrarianUnifiedSearchResponse,
)
from paper_plane_x_backend.services.librarian import (
    build_librarian_guide_payload,
    global_finder_by_project,
    matrix_fetch_by_paths,
)
from paper_plane_x_backend.services.librarian.query_parser import (
    parse_librarian_query_expr,
)
from paper_plane_x_backend.services.paper.repository import (
    PaperQueryRepository,
    PaperRepositoryError,
)

router = APIRouter(prefix="/librarian", tags=["librarian"])
logger = logging.getLogger(__name__)


def _raise_repo_error(exc: PaperRepositoryError) -> NoReturn:
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
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": exc.error_code,
            "message": exc.message,
        },
    )


@router.get(
    "/guide",
    response_model=LibrarianGuideResponse,
    summary="获取 Librarian 字段说明与查询示例",
)
def get_librarian_guide() -> LibrarianGuideResponse:
    return LibrarianGuideResponse.model_validate(build_librarian_guide_payload())


@router.post(
    "/projection",
    response_model=LibrarianProjectionResponse,
    summary="按路径获取单篇论文字段",
)
def project_paper_field(
    request: LibrarianProjectionRequest,
    db: DBDep,
) -> LibrarianProjectionResponse:
    repo = PaperQueryRepository(db)
    try:
        value = repo.fetch_by_path(
            paper_id=request.paper_id,
            field_path=request.field_path,
        )
    except PaperRepositoryError as exc:
        _raise_repo_error(exc)

    return LibrarianProjectionResponse(
        paper_id=request.paper_id,
        field_path=request.field_path,
        value=value,
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
    repo = PaperQueryRepository(db)
    try:
        query_group = (
            parse_librarian_query_expr(request.query_expr)
            if request.query_expr
            else None
        )
        paper_ids, total = repo.search_paper(
            project_id=request.project_id,
            paper_id=request.paper_id,
            query_group=query_group,
            limit=request.limit,
            offset=request.offset,
            sort_by=request.sort_by,
            sort_order=request.sort_order,
        )
    except PaperRepositoryError as exc:
        _raise_repo_error(exc)

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
def run_global_finder(
    request: LibrarianGlobalFinderRequest,
    db: DBDep,
) -> LibrarianGlobalFinderResponse:
    repo = PaperQueryRepository(db)
    try:
        payload = global_finder_by_project(
            repo=repo,
            project_id=request.project_id,
            top_tags_limit=settings.librarian.top_tags_limit,
        )
    except PaperRepositoryError as exc:
        _raise_repo_error(exc)

    return LibrarianGlobalFinderResponse.model_validate(payload)


@router.post(
    "/matrix",
    response_model=LibrarianMatrixResponse,
    summary="按路径批量对比多篇论文字段",
)
def matrix_project_papers(
    request: LibrarianMatrixRequest,
    db: DBDep,
) -> LibrarianMatrixResponse:
    repo = PaperQueryRepository(db)
    try:
        matrix = matrix_fetch_by_paths(
            repo=repo,
            paper_ids=request.paper_ids,
            field_paths=request.field_paths,
        )
    except PaperRepositoryError as exc:
        _raise_repo_error(exc)

    return LibrarianMatrixResponse(
        paper_ids=request.paper_ids,
        field_paths=request.field_paths,
        items=matrix,
    )
