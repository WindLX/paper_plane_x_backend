"""Progress contract shared by synchronous and background ZIP exports."""

from dataclasses import dataclass

from paper_plane_x_backend.schemas.api.project_exports import ProjectExportPhase


@dataclass(frozen=True)
class ExportProgress:
    phase: ProjectExportPhase
    processed_files: int = 0
    total_files: int | None = None
    current_file: str | None = None


class ExportCanceled(Exception):
    """The caller requested that packing stop and partial output be removed."""
