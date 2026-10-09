"""Project workbench routes: activity log + readonly overview."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.schemas.api.project_workbench import (
    ActivityCategory,
    ActivityListResponse,
    ActivityResponse,
    ActivityStatus,
    ProjectOverviewResponse,
)
from paper_plane_x_backend.services.app_settings import get_app_settings_repo
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.project.activity import ProjectActivityStore
from paper_plane_x_backend.services.project.overview import ProjectOverviewService
from paper_plane_x_backend.services.project.repository import (
    ProjectRepository,
    ProjectRepositoryError,
)

router = APIRouter(prefix="/projects", tags=["project_workbench"])
logger = logging.getLogger(__name__)


def _ensure_project_exists(db: Database, project_id: str) -> None:
    try:
        ProjectRepository(db).ensure_exists(project_id)
    except ProjectRepositoryError as exc:
        logger.warning(
            "event=project_workbench.project_not_found project_id=%s", project_id
        )
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc


@router.get(
    "/{project_id}/activities",
    response_model=ActivityListResponse,
    summary="列出项目活动",
    responses={404: {"description": "项目不存在"}},
)
def list_project_activities(
    project_id: str,
    db: DBDep,
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    category: ActivityCategory | None = Query(default=None, description="活动分类"),
    status: ActivityStatus | None = Query(default=None, description="活动状态"),
    created_at_from: datetime | None = Query(
        default=None, description="创建时间下界 (含)"
    ),
    created_at_to: datetime | None = Query(
        default=None, description="创建时间上界 (含)"
    ),
    keyword: str | None = Query(default=None, description="关键词"),
) -> ActivityListResponse:
    """Return newest-first project activities with filtering and pagination."""
    _ensure_project_exists(db, project_id)
    store = ProjectActivityStore(db)
    records, total = store.list(
        project_id,
        offset=offset,
        limit=limit,
        category=category,
        status=status,
        created_at_from=created_at_from,
        created_at_to=created_at_to,
        keyword=keyword,
    )
    return ActivityListResponse(
        items=[
            ActivityResponse.model_validate(record.to_payload()) for record in records
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{project_id}/overview",
    response_model=ProjectOverviewResponse,
    summary="项目只读总览",
    responses={404: {"description": "项目不存在"}},
)
def get_project_overview(
    project_id: str,
    db: DBDep,
) -> ProjectOverviewResponse:
    """Aggregate the readonly project overview without any model call."""
    _ensure_project_exists(db, project_id)
    top_tags_limit = get_app_settings_repo().get().librarian.top_tags_limit
    service = ProjectOverviewService(db, top_tags_limit=top_tags_limit)
    return ProjectOverviewResponse.model_validate(service.build(project_id))


__all__ = ["router"]
