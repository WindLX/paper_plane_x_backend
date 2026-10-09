"""Durable ZIP jobs with one worker, real progress and bounded retention."""

import asyncio
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from paper_plane_x_backend.models.export_progress import ExportCanceled, ExportProgress
from paper_plane_x_backend.schemas.api.project import ProjectExportRequest
from paper_plane_x_backend.schemas.api.project_exports import (
    ProjectExportJob,
    ProjectExportPhase,
    ProjectExportStatus,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.orchestrators.project import ProjectOrchestrator
from paper_plane_x_backend.services.project.activity import ProjectActivityStore
from paper_plane_x_backend.services.project.files import ProjectFileManager
from paper_plane_x_backend.services.project.repository import ProjectRepository

logger = logging.getLogger(__name__)


class ProjectExportError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ExportRecord:
    job: ProjectExportJob
    options: ProjectExportRequest
    artifact_path: Path | None


class ProjectExportRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self, project_id: str, options: ProjectExportRequest
    ) -> ProjectExportJob:
        ProjectRepository(self.db).ensure_exists(project_id)
        job = ProjectExportJob(
            export_id=f"exp-{uuid4().hex}",
            project_id=project_id,
            status=ProjectExportStatus.QUEUED,
            phase=ProjectExportPhase.QUEUED,
            created_at=datetime.now(timezone.utc),
        )
        try:
            self.db.execute(
                """INSERT INTO project_exports
                (export_id, project_id, options, status, phase, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    job.export_id,
                    project_id,
                    options.model_dump_json(),
                    job.status.value,
                    job.phase.value,
                    job.created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            if self.active(project_id) is not None:
                raise ProjectExportError(
                    409, "This project already has an active export"
                ) from exc
            raise
        ProjectActivityStore(self.db).record(
            activity_id=job.export_id,
            project_id=project_id,
            category="export",
            event_type="project_exported",
            status="queued",
            detail={"export_id": job.export_id, "format": "zip"},
        )
        return job

    def get(self, export_id: str, project_id: str | None = None) -> ExportRecord | None:
        row = self.db.fetchone(
            "SELECT * FROM project_exports WHERE export_id = ?", (export_id,)
        )
        if row is None or (project_id is not None and row["project_id"] != project_id):
            return None
        return self._from_row(row)

    @staticmethod
    def _from_row(row: dict[str, Any]) -> ExportRecord:
        """Validate the untyped SQLite row at this repository boundary."""
        options = ProjectExportRequest.model_validate_json(row.pop("options"))
        path = row.pop("artifact_path")
        row["cancel_requested"] = bool(row["cancel_requested"])
        return ExportRecord(
            ProjectExportJob.model_validate(row), options, Path(path) if path else None
        )

    def list_jobs(self, project_id: str, limit: int = 20) -> list[ProjectExportJob]:
        rows = self.db.fetchall(
            "SELECT * FROM project_exports WHERE project_id = ? ORDER BY created_at DESC, export_id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._from_row(row).job for row in rows]

    def active(self, project_id: str) -> ProjectExportJob | None:
        row = self.db.fetchone(
            "SELECT export_id FROM project_exports WHERE project_id = ? AND status IN ('queued','running')",
            (project_id,),
        )
        record = self.get(row["export_id"]) if row else None
        return record.job if record is not None else None

    def update_progress(self, export_id: str, progress: ExportProgress) -> None:
        self.db.execute(
            """UPDATE project_exports SET status='running', phase=?, processed_files=?, total_files=?, current_file=? WHERE export_id=? AND status IN ('queued','running') AND cancel_requested=0""",
            (
                progress.phase.value,
                progress.processed_files,
                progress.total_files,
                progress.current_file,
                export_id,
            ),
        )
        ProjectActivityStore(self.db).update(
            export_id,
            status="running",
            detail={
                "export_id": export_id,
                "phase": progress.phase.value,
                "processed_files": progress.processed_files,
                "total_files": progress.total_files,
            },
        )

    def finish(
        self,
        export_id: str,
        status: ProjectExportStatus,
        *,
        path: Path | None = None,
        download_name: str | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.db.execute(
            """UPDATE project_exports SET status=?, phase=CASE WHEN ?='completed' THEN 'ready' ELSE phase END, current_file=NULL,
            artifact_path=?, download_name=?, file_size=?, error=?, finished_at=?, expires_at=? WHERE export_id=?""",
            (
                status.value,
                status.value,
                str(path) if path else None,
                download_name,
                path.stat().st_size if path else None,
                error,
                now.isoformat(),
                (now + timedelta(hours=24)).isoformat(),
                export_id,
            ),
        )
        activities = ProjectActivityStore(self.db)
        if status == ProjectExportStatus.COMPLETED:
            activities.complete(
                export_id,
                object_name=download_name,
                detail={"export_id": export_id, "download_name": download_name},
            )
        elif status == ProjectExportStatus.CANCELED:
            activities.fail(export_id, status="canceled")
        elif status == ProjectExportStatus.FAILED:
            activities.fail(export_id, error=error)

    def request_cancel(self, project_id: str, export_id: str) -> ProjectExportJob:
        record = self.get(export_id, project_id)
        if record is None:
            raise ProjectExportError(404, "Export not found")
        if record.job.status in (
            ProjectExportStatus.QUEUED,
            ProjectExportStatus.RUNNING,
        ):
            self.db.execute(
                "UPDATE project_exports SET cancel_requested=1 WHERE export_id=?",
                (export_id,),
            )
            record.job.cancel_requested = True
            if record.job.status == ProjectExportStatus.QUEUED:
                self.finish(export_id, ProjectExportStatus.CANCELED)
                updated = self.get(export_id, project_id)
                if updated is None:
                    raise ProjectExportError(404, "Export not found")
                return updated.job
        return record.job

    def fail_interrupted(self) -> None:
        interrupted = self.db.fetchall(
            "SELECT export_id FROM project_exports WHERE status IN ('queued','running')"
        )
        now = datetime.now(timezone.utc)
        self.db.execute(
            """UPDATE project_exports SET status='failed', error='Export interrupted by server restart; start a new export', finished_at=?, expires_at=?
            WHERE status IN ('queued','running')""",
            (now.isoformat(), (now + timedelta(hours=24)).isoformat()),
        )
        for record in interrupted:
            ProjectActivityStore(self.db).fail(
                record["export_id"],
                error="Export interrupted by server restart; start a new export",
            )

    def due_for_expiry(self, now: datetime) -> list[ExportRecord]:
        rows = self.db.fetchall(
            "SELECT * FROM project_exports WHERE status NOT IN ('queued','running','expired') AND expires_at <= ?",
            (now.isoformat(),),
        )
        return [self._from_row(row) for row in rows]

    def mark_expired(self, export_id: str) -> None:
        self.db.execute(
            "UPDATE project_exports SET status='expired', artifact_path=NULL WHERE export_id=?",
            (export_id,),
        )


class ProjectExportManager:
    """The application owns this worker; page navigation never owns its lifetime."""

    def __init__(
        self, db: Database, root: Path, file_manager: ProjectFileManager | None = None
    ) -> None:
        self.db = db
        self.repo = ProjectExportRepository(db)
        self.root = root
        self.file_manager = file_manager
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._stopping = threading.Event()

    async def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo.fail_interrupted()
        for partial in self.root.glob("exp-*.partial"):
            partial.unlink(missing_ok=True)
        self.clean_expired()
        self._stopping.clear()
        self._worker = asyncio.create_task(self._run(), name="project-export-worker")
        self._cleanup = asyncio.create_task(
            self._cleanup_loop(), name="project-export-cleanup"
        )

    async def stop(self) -> None:
        self._stopping.set()
        self._queue.put_nowait(None)
        if self._cleanup is not None:
            self._cleanup.cancel()
            try:
                await self._cleanup
            except asyncio.CancelledError:
                pass
        if self._worker is not None:
            await self._worker
        self.repo.fail_interrupted()

    def submit(
        self, project_id: str, options: ProjectExportRequest
    ) -> ProjectExportJob:
        job = self.repo.create(project_id, options)
        self._queue.put_nowait(job.export_id)
        return job

    def clean_expired(self) -> None:
        for record in self.repo.due_for_expiry(datetime.now(timezone.utc)):
            if record.artifact_path is not None:
                record.artifact_path.unlink(missing_ok=True)
            self.repo.mark_expired(record.job.export_id)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await asyncio.to_thread(self.clean_expired)
            except (OSError, sqlite3.Error):
                logger.exception("event=project.export_cleanup_failed")

    async def _run(self) -> None:
        while True:
            export_id = await self._queue.get()
            try:
                if export_id is None:
                    return
                if not self._stopping.is_set():
                    await asyncio.to_thread(self._pack, export_id)
            finally:
                self._queue.task_done()

    def _pack(self, export_id: str) -> None:
        record = self.repo.get(export_id)
        if record is None or record.job.status != ProjectExportStatus.QUEUED:
            return
        partial = self.root / f"{export_id}.partial"
        output = self.root / f"{export_id}.zip"

        def canceled() -> bool:
            current = self.repo.get(export_id)
            return (
                self._stopping.is_set()
                or current is None
                or current.job.cancel_requested
            )

        try:
            if canceled():
                raise ExportCanceled()
            _, name = ProjectOrchestrator(
                self.db, self.file_manager
            ).export_project_bundle(
                project_id=record.job.project_id,
                fields=record.options.fields,
                citations_mode=record.options.citations_mode,
                include_sandbox_files=record.options.include_sandbox_files,
                output_path=partial,
                activity_id=export_id,
                on_progress=lambda progress: self.repo.update_progress(
                    export_id, progress
                ),
                should_cancel=canceled,
            )
            if canceled():
                raise ExportCanceled()
            partial.replace(output)
            self.repo.finish(
                export_id,
                ProjectExportStatus.COMPLETED,
                path=output,
                download_name=name,
            )
        except ExportCanceled:
            partial.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
            interrupted = self._stopping.is_set()
            self.repo.finish(
                export_id,
                ProjectExportStatus.FAILED
                if interrupted
                else ProjectExportStatus.CANCELED,
                error="Export interrupted by server shutdown; start a new export"
                if interrupted
                else None,
            )
        except Exception as exc:
            # Job execution is a resource boundary: persist an explicit failure
            # instead of killing the worker and stranding all queued jobs.
            partial.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
            self.repo.finish(export_id, ProjectExportStatus.FAILED, error=str(exc))
            logger.exception("event=project.export_failed export_id=%s", export_id)


def delete_project_exports(db: Database, project_id: str, root: Path) -> None:
    """Mark cancellation before removing rows/files; an active worker checks it."""
    rows = db.fetchall(
        "SELECT export_id FROM project_exports WHERE project_id=?", (project_id,)
    )
    db.execute("DELETE FROM project_exports WHERE project_id=?", (project_id,))
    for row in rows:
        for extension in ("partial", "zip"):
            (root / f"{row['export_id']}.{extension}").unlink(missing_ok=True)
