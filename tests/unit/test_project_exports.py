"""Synthetic export jobs: lifecycle, real progress, isolation and ZIP contents."""

import asyncio
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from paper_plane_x_backend.models.export_progress import ExportProgress
from paper_plane_x_backend.schemas.api.project import ProjectExportRequest
from paper_plane_x_backend.schemas.api.project_exports import (
    ProjectExportPhase,
    ProjectExportStatus,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.orchestrators.project import ProjectOrchestrator
from paper_plane_x_backend.services.project.activity import ProjectActivityStore
from paper_plane_x_backend.services.project.export_jobs import (
    ProjectExportError,
    ProjectExportManager,
    delete_project_exports,
)


@pytest.fixture
def workspace(db: Database, tmp_path: Path):
    orchestrator = ProjectOrchestrator(db)
    project = orchestrator.create_project(name="Synthetic project", description=None)
    orchestrator.file_manager.write_file(project.project_id, "/draft.md", "# Synthetic")
    orchestrator.file_manager.write_file(
        project.project_id, "/notes/idea.txt", "Synthetic note"
    )
    return project.project_id, ProjectExportManager(db, tmp_path / "exports")


def options() -> ProjectExportRequest:
    return ProjectExportRequest(
        fields=["paper_id", "title"], include_sandbox_files=True
    )


@pytest.mark.asyncio
async def test_worker_finishes_real_archive_and_download_remains_available(workspace):
    project_id, manager = workspace
    await manager.start()
    try:
        job = manager.submit(project_id, options())
        await asyncio.wait_for(manager._queue.join(), timeout=5)
        record = manager.repo.get(job.export_id, project_id)
        assert record is not None
        assert record.job.status == ProjectExportStatus.COMPLETED
        assert record.job.phase == ProjectExportPhase.READY
        assert record.job.total_files == record.job.processed_files == 3
        assert record.artifact_path is not None
        with zipfile.ZipFile(record.artifact_path) as archive:
            assert any(
                name.endswith("project_files/notes/idea.txt")
                for name in archive.namelist()
            )
            assert any(
                name.endswith("project_files/draft.md") for name in archive.namelist()
            )
        assert record.job.expires_at - record.job.finished_at == timedelta(hours=24)
        assert manager.repo.get(job.export_id, "other-project") is None
        activities, _ = ProjectActivityStore(manager.db).list(
            project_id, category="export"
        )
        assert len(activities) == 1
        assert activities[0].activity_id == job.export_id
    finally:
        await manager.stop()


def test_progress_tracks_entries_and_finalization_not_fake_percent(workspace):
    project_id, manager = workspace
    events: list[ExportProgress] = []
    path, _ = ProjectOrchestrator(manager.db).export_project_bundle(
        project_id=project_id,
        fields=["title"],
        citations_mode="keep",
        include_sandbox_files=True,
        output_path=manager.root / "probe.zip",
        on_progress=events.append,
    )
    assert Path(path).is_file()
    activities, _ = ProjectActivityStore(manager.db).list(project_id, category="export")
    assert len(activities) == 1
    assert activities[0].status == "completed"
    assert activities[0].object_name == "Synthetic project"
    assert events[0].phase == ProjectExportPhase.PREPARING
    packing = [event for event in events if event.phase == ProjectExportPhase.PACKING]
    assert all(event.total_files == 3 for event in packing)
    assert [event.processed_files for event in packing] == sorted(
        event.processed_files for event in packing
    )
    assert events[-1].phase == ProjectExportPhase.FINALIZING
    assert events[-1].processed_files == events[-1].total_files == 3


def test_duplicate_active_export_rejected_and_queued_cancel_is_immediate(workspace):
    project_id, manager = workspace
    job = manager.submit(project_id, options())
    with pytest.raises(ProjectExportError, match="active") as error:
        manager.submit(project_id, options())
    assert error.value.status_code == 409
    result = manager.repo.request_cancel(project_id, job.export_id)
    assert result.status == ProjectExportStatus.CANCELED
    manager._pack(job.export_id)
    assert not (manager.root / f"{job.export_id}.zip").exists()
    assert manager.submit(project_id, options()).export_id != job.export_id


def test_cancel_during_packing_removes_partial_file(workspace, monkeypatch):
    project_id, manager = workspace
    job = manager.submit(project_id, options())
    original = manager.repo.update_progress

    def progress(export_id: str, event: ExportProgress):
        original(export_id, event)
        if event.processed_files == 1:
            manager.repo.request_cancel(project_id, export_id)

    monkeypatch.setattr(manager.repo, "update_progress", progress)
    manager._pack(job.export_id)
    assert manager.repo.get(job.export_id).job.status == ProjectExportStatus.CANCELED
    assert not list(manager.root.glob("*.partial"))
    assert not list(manager.root.glob("*.zip"))


@pytest.mark.asyncio
async def test_restart_marks_inflight_failed_and_cleans_partial(workspace):
    project_id, manager = workspace
    job = manager.repo.create(project_id, options())
    manager.root.mkdir()
    partial = manager.root / f"{job.export_id}.partial"
    partial.write_bytes(b"synthetic partial")
    await manager.start()
    try:
        assert manager.repo.get(job.export_id).job.status == ProjectExportStatus.FAILED
        assert "restart" in manager.repo.get(job.export_id).job.error
        assert not partial.exists()
    finally:
        await manager.stop()


def test_expiry_and_project_delete_remove_only_owned_artifacts(workspace):
    project_id, manager = workspace
    job = manager.submit(project_id, options())
    manager._pack(job.export_id)
    record = manager.repo.get(job.export_id)
    manager.db.execute(
        "UPDATE project_exports SET expires_at=? WHERE export_id=?",
        (
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            job.export_id,
        ),
    )
    manager.clean_expired()
    assert manager.repo.get(job.export_id).job.status == ProjectExportStatus.EXPIRED
    assert not record.artifact_path.exists()
    next_job = manager.submit(project_id, options())
    manager._pack(next_job.export_id)
    unrelated = manager.root / "unrelated.txt"
    unrelated.write_text("keep")
    delete_project_exports(manager.db, project_id, manager.root)
    assert manager.repo.get(next_job.export_id) is None
    assert unrelated.exists()
    assert not list(manager.root.glob("exp-*.zip"))


def test_file_failure_is_visible_and_next_job_can_run(workspace, monkeypatch):
    project_id, manager = workspace
    job = manager.submit(project_id, options())

    def fail(*args, **kwargs):
        raise OSError("synthetic read failure")

    with monkeypatch.context() as patch:
        patch.setattr(ProjectOrchestrator, "export_project_bundle", fail)
        manager._pack(job.export_id)
    assert manager.repo.get(job.export_id).job.status == ProjectExportStatus.FAILED
    assert manager.repo.get(job.export_id).job.error == "synthetic read failure"
    next_job = manager.submit(project_id, options())
    manager._pack(next_job.export_id)
    assert (
        manager.repo.get(next_job.export_id).job.status == ProjectExportStatus.COMPLETED
    )
