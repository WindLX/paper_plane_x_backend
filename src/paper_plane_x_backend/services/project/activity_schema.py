"""Project activity table SQL declarations.

This module deliberately has no database import so the schema can be consumed by
the database initialization layer without creating an import cycle. The parent
workbench integration adds :data:`PROJECT_ACTIVITY_SCHEMA_SQL` to ``database.py``.
"""

PROJECT_ACTIVITIES_TABLE = "project_activities"

PROJECT_ACTIVITY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS project_activities (
    activity_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    category TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    object_name TEXT,
    paper_id TEXT,
    file_path TEXT,
    task_id TEXT,
    trace_ids TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    error TEXT,
    retry_of_task_id TEXT,
    task_exists INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_project_activities_project_created
    ON project_activities(project_id, created_at DESC, activity_id DESC);

CREATE INDEX IF NOT EXISTS idx_project_activities_project_category
    ON project_activities(project_id, category, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_project_activities_project_status
    ON project_activities(project_id, status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_activities_project_task
    ON project_activities(project_id, task_id) WHERE task_id IS NOT NULL;
"""

__all__ = [
    "PROJECT_ACTIVITIES_TABLE",
    "PROJECT_ACTIVITY_SCHEMA_SQL",
]
