"""Project activity store tests."""

import json
from datetime import datetime, timedelta

import pytest

from paper_plane_x_backend.models import DataProcessTaskStatus, Project
from paper_plane_x_backend.services import Database
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessTaskState,
)
from paper_plane_x_backend.services.data_process_tasks.stores import (
    DataProcessTaskStateStore,
)
from paper_plane_x_backend.services.project.activity import (
    ProjectActivityStore,
    build_operation_log_activity_id,
    migrate_legacy_operation_logs,
    pending_activity,
)
from paper_plane_x_backend.services.project.repository import ProjectRepository


def _create_project(db: Database, project_id: str) -> None:
    now = datetime(2025, 1, 1)
    ProjectRepository(db).create(
        Project(
            project_id=project_id,
            name=f"Project {project_id}",
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
    )


def _insert_paper(db: Database, paper_id: str, project_ids: list[str]) -> None:
    now = datetime.now()
    db.insert(
        "papers",
        {
            "paper_id": paper_id,
            "title": f"Paper {paper_id}",
            "authors": "[]",
            "extraction_status": "COMPLETED",
            "extraction_fact_check_status": "PASSED",
            "analysis_fact_check_status": "PASSED",
            "created_at": now,
            "updated_at": now,
        },
    )
    for project_id in project_ids:
        db.execute(
            "INSERT INTO paper_projects (paper_id, project_id) VALUES (?, ?)",
            (paper_id, project_id),
        )


def _task_state(
    task_id: str,
    paper_id: str,
    status: DataProcessTaskStatus,
    *,
    created_at: datetime | None = None,
    retry_of_task_id: str | None = None,
) -> DataProcessTaskState:
    return DataProcessTaskState(
        task_id=task_id,
        paper_id=paper_id,
        payload={},
        status=status,
        created_at=created_at or datetime.now(),
        retry_of_task_id=retry_of_task_id,
    )


class TestProjectActivityStore:
    def test_complete_preserves_object_name(self, db: Database) -> None:
        _create_project(db, "p-name")
        store = ProjectActivityStore(db)
        activity_id = store.record_pending(
            project_id="p-name",
            category="export",
            event_type="project_exported",
            object_name="Research ZIP",
        )
        store.complete(activity_id)
        items, _ = store.list("p-name")
        assert (
            next(item for item in items if item.activity_id == activity_id).object_name
            == "Research ZIP"
        )

    def test_record_and_list_filters(self, db: Database) -> None:
        _create_project(db, "p-list")
        _create_project(db, "other")
        store = ProjectActivityStore(db)
        base = datetime(2026, 1, 1, 12, 0, 0)
        store.record(
            project_id="p-list",
            category="project",
            event_type="project_updated",
            created_at=base,
        )
        store.record(
            project_id="p-list",
            category="task",
            event_type="task_failed",
            status="failed",
            task_id="t-1",
            error="boom",
            created_at=base + timedelta(minutes=1),
        )
        store.record(
            project_id="p-list",
            category="file",
            event_type="file_written",
            object_name="notes.md",
            file_path="/notes.md",
            created_at=base + timedelta(minutes=2),
        )
        store.record(
            project_id="other",
            category="project",
            event_type="project_updated",
            created_at=base + timedelta(minutes=3),
        )

        records, total = store.list("p-list")
        assert total == 4
        assert [r.event_type for r in records] == [
            "file_written",
            "task_failed",
            "project_updated",
            "project_created",
        ]

        task_records, task_total = store.list("p-list", category="task")
        assert task_total == 1
        assert task_records[0].task_id == "t-1"
        assert task_records[0].status == "failed"

        failed_records, failed_total = store.list("p-list", status="failed")
        assert failed_total == 1
        assert failed_records[0].category == "task"

        ranged_records, ranged_total = store.list(
            "p-list",
            created_at_from=base + timedelta(minutes=1),
            created_at_to=base + timedelta(minutes=1),
        )
        assert ranged_total == 1
        assert ranged_records[0].event_type == "task_failed"

        keyword_records, keyword_total = store.list("p-list", keyword="notes.md")
        assert keyword_total == 1
        assert keyword_records[0].file_path == "/notes.md"

        paged, paged_total = store.list("p-list", offset=1, limit=1)
        assert paged_total == 4
        assert len(paged) == 1
        assert paged[0].event_type == "task_failed"

    def test_update_settles_pending_activity(self, db: Database) -> None:
        _create_project(db, "p-pending")
        store = ProjectActivityStore(db)
        activity_id = store.record_pending(
            project_id="p-pending",
            category="agent",
            event_type="agent_summary",
            object_name="GlobalFinderAgent",
        )
        running = store.list("p-pending")[0][0]
        assert running.status == "running"
        assert running.started_at is not None

        store.complete(activity_id, trace_ids=["trace-1"])
        completed = store.list("p-pending")[0][0]
        assert completed.status == "completed"
        assert completed.finished_at is not None
        assert completed.trace_ids == ["trace-1"]

    async def test_pending_activity_success_and_failure(self, db: Database) -> None:
        _create_project(db, "p-scope")
        store = ProjectActivityStore(db)

        async with pending_activity(
            store,
            project_id="p-scope",
            category="export",
            event_type="project_exported",
        ):
            pass

        with pytest.raises(RuntimeError):
            async with pending_activity(
                store,
                project_id="p-scope",
                category="export",
                event_type="project_exported",
            ):
                raise RuntimeError("export boom")

        records, total = store.list("p-scope", category="export")
        assert total == 2
        statuses = {r.status for r in records}
        assert statuses == {"completed", "failed"}
        failed = next(r for r in records if r.status == "failed")
        assert failed.error == "export boom"

    def test_operation_log_migration_is_deterministic_and_idempotent(
        self, db: Database
    ) -> None:
        now = datetime.now()
        timestamps = [(now + timedelta(seconds=i)).isoformat() for i in range(3)]
        entries = [
            {
                "operation": "link_paper",
                "timestamp": timestamps[0],
                "detail": {"paper_id": "paper-1"},
            },
            {
                "operation": "update_project",
                "timestamp": timestamps[1],
                "detail": {"changed_fields": ["name"]},
            },
            {
                "operation": "unknown_legacy_operation",
                "timestamp": timestamps[2],
                "detail": {},
            },
        ]
        db.insert(
            "projects",
            {
                "project_id": "p-migrate",
                "name": "Migrate",
                "created_at": now,
                "updated_at": now,
                "operation_logs": json.dumps(entries),
            },
        )
        store = ProjectActivityStore(db)

        assert store.migrate_operation_logs("p-migrate") == 2
        assert store.migrate_operation_logs("p-migrate") == 0

        records, total = store.list("p-migrate")
        assert total == 2
        assert {r.category for r in records} == {"paper", "project"}
        assert all(r.category != "task" for r in records)
        assert {r.activity_id for r in records} == {
            build_operation_log_activity_id(
                "p-migrate", 0, "link_paper", timestamps[0]
            ),
            build_operation_log_activity_id(
                "p-migrate", 1, "update_project", timestamps[1]
            ),
        }

    def test_module_migration_migrates_every_project_once(self, db: Database) -> None:
        now = datetime.now()
        entry = json.dumps(
            [
                {
                    "operation": "link_paper",
                    "timestamp": now.isoformat(),
                    "detail": {"paper_id": "paper-all"},
                }
            ]
        )
        for project_id in ("p-all-a", "p-all-b"):
            db.insert(
                "projects",
                {
                    "project_id": project_id,
                    "name": project_id,
                    "created_at": now,
                    "updated_at": now,
                    "operation_logs": entry,
                },
            )

        assert migrate_legacy_operation_logs(db) == 2
        assert migrate_legacy_operation_logs(db) == 0
        store = ProjectActivityStore(db)
        assert store.list("p-all-a", category="paper")[1] == 1
        assert store.list("p-all-b", category="paper")[1] == 1

    def test_migration_skips_missing_or_invalid_timestamp(self, db: Database) -> None:
        now = datetime.now()
        entries = [
            {
                "operation": "link_paper",
                "timestamp": None,
                "detail": {"paper_id": "paper-skip"},
            },
            {
                "operation": "link_paper",
                "timestamp": "not-a-timestamp",
                "detail": {"paper_id": "paper-skip"},
            },
            {
                "operation": "link_paper",
                "timestamp": now.isoformat(),
                "detail": {"paper_id": "paper-skip"},
            },
        ]
        db.insert(
            "projects",
            {
                "project_id": "p-skip",
                "name": "Skip",
                "created_at": now,
                "updated_at": now,
                "operation_logs": json.dumps(entries),
            },
        )

        assert ProjectActivityStore(db).migrate_operation_logs("p-skip") == 1
        records, total = ProjectActivityStore(db).list("p-skip")
        assert total == 1
        assert records[0].created_at == now

    def test_repository_update_operation_logs_emits_exactly_once(
        self, db: Database
    ) -> None:
        _create_project(db, "p-emit")
        repo = ProjectRepository(db)
        store = ProjectActivityStore(db)

        repo.update_operation_logs("p-emit", "link_paper", {"paper_id": "paper-1"})
        records, total = store.list("p-emit")
        assert total == 2
        entry = repo.get_operation_logs("p-emit")[0]
        expected_id = build_operation_log_activity_id(
            "p-emit", 0, "link_paper", entry["timestamp"]
        )
        assert records[0].activity_id == expected_id
        assert records[0].paper_id == "paper-1"

        # Migration must not duplicate an entry already emitted live.
        assert store.migrate_operation_logs("p-emit") == 0
        assert store.list("p-emit")[1] == 2

        repo.update_operation_logs("p-emit", "unlink_paper", {"paper_id": "paper-1"})
        records, total = store.list("p-emit")
        assert total == 3
        assert records[0].event_type == "paper_unlinked"

    def test_repository_summary_change_emits_event(self, db: Database) -> None:
        _create_project(db, "p-summary")
        repo = ProjectRepository(db)
        store = ProjectActivityStore(db)

        repo.set_agent_summary("p-summary", "summary body")
        repo.delete_agent_summary("p-summary")

        records, total = store.list("p-summary", category="project")
        assert total == 3
        assert {r.event_type for r in records} == {
            "summary_updated",
            "summary_cleared",
            "project_created",
        }

    def test_task_projection_keeps_recorded_join(self, db: Database) -> None:
        _create_project(db, "p-task")
        _insert_paper(db, "paper-task", ["p-task"])
        store = ProjectActivityStore(db)
        created_at = datetime(2026, 2, 1, 9, 0, 0)

        store.record_task_state(
            _task_state(
                "task-1",
                "paper-task",
                DataProcessTaskStatus.RUNNING,
                created_at=created_at,
            ),
            project_ids=["p-task"],
        )
        first = store.list("p-task", category="task")[0][0]
        assert first.status == "running"
        assert first.task_exists is True
        assert first.created_at == created_at

        # Later update after the paper was unlinked: same row, same created_at.
        store.record_task_state(
            _task_state(
                "task-1",
                "paper-task",
                DataProcessTaskStatus.COMPLETED,
                created_at=created_at,
            ),
            project_ids=[],
        )
        second = store.list("p-task", category="task")[0][0]
        assert second.activity_id == first.activity_id
        assert second.status == "completed"
        assert second.created_at == first.created_at

        store.mark_task_missing("task-1")
        third = store.list("p-task", category="task")[0][0]
        assert third.task_exists is False
        assert third.status == "completed"

    def test_task_retry_creates_new_linked_row(self, db: Database) -> None:
        _create_project(db, "p-retry")
        _insert_paper(db, "paper-retry", ["p-retry"])
        store = ProjectActivityStore(db)

        store.record_task_state(
            _task_state("task-original", "paper-retry", DataProcessTaskStatus.FAILED),
            project_ids=["p-retry"],
        )
        store.record_task_state(
            _task_state(
                "task-retry",
                "paper-retry",
                DataProcessTaskStatus.QUEUED,
                retry_of_task_id="task-original",
            ),
            project_ids=["p-retry"],
        )

        records, total = store.list("p-retry", category="task")
        assert total == 2
        retry_record = next(r for r in records if r.task_id == "task-retry")
        assert retry_record.retry_of_task_id == "task-original"
        assert retry_record.status == "queued"

    def test_task_projection_fans_out_to_linked_projects(self, db: Database) -> None:
        _create_project(db, "p-a")
        _create_project(db, "p-b")
        _insert_paper(db, "paper-shared", ["p-a", "p-b"])
        store = ProjectActivityStore(db)

        store.record_task_state(
            _task_state("task-shared", "paper-shared", DataProcessTaskStatus.QUEUED),
            project_ids=["p-a", "p-b"],
        )

        assert store.list("p-a", category="task")[1] == 1
        assert store.list("p-b", category="task")[1] == 1

    def test_deleting_project_cascades_activities(self, db: Database) -> None:
        _create_project(db, "p-cascade")
        ProjectActivityStore(db).record(
            project_id="p-cascade",
            category="project",
            event_type="project_updated",
        )

        ProjectRepository(db).delete("p-cascade")

        row = db.fetchone(
            "SELECT COUNT(*) AS count FROM project_activities WHERE project_id = ?",
            ("p-cascade",),
        )
        assert row is not None
        assert row["count"] == 0

    def test_task_projection_ignores_deleted_project_race(self, db: Database) -> None:
        _create_project(db, "p-race")
        _insert_paper(db, "paper-race", ["p-race"])
        store = ProjectActivityStore(db)
        stale_project_ids = ["p-race"]

        # Project is deleted after the association ids were captured.
        ProjectRepository(db).delete("p-race")
        store.record_task_state(
            _task_state("task-race", "paper-race", DataProcessTaskStatus.QUEUED),
            project_ids=stale_project_ids,
        )

        row = db.fetchone(
            "SELECT COUNT(*) AS count FROM project_activities WHERE task_id = ?",
            ("task-race",),
        )
        assert row is not None
        assert row["count"] == 0

    def test_task_store_upsert_records_activity(self, db: Database) -> None:
        _create_project(db, "p-store")
        _insert_paper(db, "paper-store", ["p-store"])

        DataProcessTaskStateStore(db).upsert(
            _task_state("task-store", "paper-store", DataProcessTaskStatus.QUEUED)
        )

        records, total = ProjectActivityStore(db).list("p-store", category="task")
        assert total == 1
        assert records[0].task_id == "task-store"
        assert records[0].task_exists is True

    def test_task_store_delete_keeps_activity_with_task_exists_false(
        self, db: Database
    ) -> None:
        _create_project(db, "p-del")
        _insert_paper(db, "paper-del", ["p-del"])
        store = DataProcessTaskStateStore(db)
        store.upsert(
            _task_state(
                "task-del",
                "paper-del",
                DataProcessTaskStatus.COMPLETED,
            )
        )

        store.delete("task-del")

        records, total = ProjectActivityStore(db).list("p-del", category="task")
        assert total == 1
        assert records[0].task_exists is False
