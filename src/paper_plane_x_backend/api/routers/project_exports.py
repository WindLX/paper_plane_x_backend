"""Project ZIP job routes; file serving never reveals local artifact paths."""

from datetime import datetime, timezone
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.schemas.api.project import ProjectExportRequest
from paper_plane_x_backend.schemas.api.project_exports import (
    ProjectExportJob,
    ProjectExportJobListResponse,
    ProjectExportStatus,
)
from paper_plane_x_backend.services.project.export_jobs import (
    ProjectExportError,
    ProjectExportManager,
)
from paper_plane_x_backend.services.project.repository import (
    ProjectRepository,
    ProjectRepositoryError,
)

router = APIRouter(prefix="/projects/{project_id}/exports", tags=["project-exports"])


def get_project_export_manager(request: Request) -> ProjectExportManager:
    # Starlette app.state is untyped; the application's lifespan owns this value.
    return cast(ProjectExportManager, request.app.state.project_exports)


ExportManagerDep = Annotated[ProjectExportManager, Depends(get_project_export_manager)]


def _ensure_project(db: DBDep, project_id: str) -> None:
    try:
        ProjectRepository(db).ensure_exists(project_id)
    except ProjectRepositoryError as exc:
        raise HTTPException(404, exc.message) from exc


@router.post("", response_model=ProjectExportJob, status_code=202)
async def create_export(
    project_id: str, request: ProjectExportRequest, db: DBDep, manager: ExportManagerDep
) -> ProjectExportJob:
    _ensure_project(db, project_id)
    try:
        return manager.submit(project_id, request)
    except ProjectExportError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("", response_model=ProjectExportJobListResponse)
def list_exports(
    project_id: str, db: DBDep, manager: ExportManagerDep
) -> ProjectExportJobListResponse:
    _ensure_project(db, project_id)
    manager.clean_expired()
    return ProjectExportJobListResponse(items=manager.repo.list_jobs(project_id))


@router.get("/{export_id}", response_model=ProjectExportJob)
def get_export(
    project_id: str, export_id: str, db: DBDep, manager: ExportManagerDep
) -> ProjectExportJob:
    _ensure_project(db, project_id)
    manager.clean_expired()
    record = manager.repo.get(export_id, project_id)
    if record is None:
        raise HTTPException(404, "Export not found")
    return record.job


@router.post("/{export_id}/cancel", response_model=ProjectExportJob)
def cancel_export(
    project_id: str, export_id: str, db: DBDep, manager: ExportManagerDep
) -> ProjectExportJob:
    _ensure_project(db, project_id)
    try:
        return manager.repo.request_cancel(project_id, export_id)
    except ProjectExportError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/{export_id}/download")
def download_export(
    project_id: str, export_id: str, db: DBDep, manager: ExportManagerDep
) -> FileResponse:
    _ensure_project(db, project_id)
    record = manager.repo.get(export_id, project_id)
    if record is None:
        raise HTTPException(404, "Export not found")
    job = record.job
    if job.status == ProjectExportStatus.EXPIRED or (
        job.expires_at is not None and job.expires_at <= datetime.now(timezone.utc)
    ):
        raise HTTPException(410, "Export expired; start a new export")
    if job.status != ProjectExportStatus.COMPLETED:
        raise HTTPException(409, "Export is not ready for download")
    if record.artifact_path is None or not record.artifact_path.is_file():
        raise HTTPException(410, "Export file no longer exists; start a new export")
    return FileResponse(
        record.artifact_path, filename=job.download_name, media_type="application/zip"
    )
