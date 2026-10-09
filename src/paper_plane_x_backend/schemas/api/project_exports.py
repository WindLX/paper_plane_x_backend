"""Persistent project export jobs, separate from paper processing tasks."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ProjectExportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    EXPIRED = "expired"


class ProjectExportPhase(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    PACKING = "packing"
    FINALIZING = "finalizing"
    READY = "ready"


class ProjectExportJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: str
    project_id: str
    status: ProjectExportStatus
    phase: ProjectExportPhase
    processed_files: int = 0
    total_files: int | None = None
    current_file: str | None = None
    error: str | None = None
    download_name: str | None = None
    file_size: int | None = None
    created_at: datetime
    finished_at: datetime | None = None
    expires_at: datetime | None = None
    cancel_requested: bool = False


class ProjectExportJobListResponse(BaseModel):
    items: list[ProjectExportJob]
