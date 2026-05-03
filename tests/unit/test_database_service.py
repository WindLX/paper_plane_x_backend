"""Database service tests."""

from pathlib import Path

from paper_plane_x_backend.services.database import Database


def _table_columns(db: Database, table: str) -> list[str]:
    with db.get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


def test_init_tables_creates_current_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")

    db.init_tables()

    trace_columns = _table_columns(db, "agent_traces")
    assert "messages" in trace_columns
    assert "llm_model" in trace_columns
    assert "usage_payload" in trace_columns
    assert "caller" in trace_columns
    assert "caller_id" in trace_columns

    task_columns = _table_columns(db, "data_process_tasks")
    for column in [
        "task_id",
        "paper_id",
        "payload",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "error",
        "retry_of_task_id",
        "extraction_trace_ids",
        "analysis_trace_ids",
        "extraction_fact_check_trace_ids",
        "analysis_fact_check_trace_ids",
    ]:
        assert column in task_columns

    # librarian_history 表已删除
    tables = db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='librarian_history'"
    )
    assert tables == []


def test_init_tables_is_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")

    db.init_tables()
    db.init_tables()

    assert "paper_id" in _table_columns(db, "papers")
    assert "caller" in _table_columns(db, "agent_traces")


def test_migration_adds_agent_summary_column_to_existing_db(tmp_path: Path) -> None:
    db = Database(tmp_path / "legacy.sqlite3")

    with db.get_connection() as conn:
        conn.execute("""
            CREATE TABLE projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                operation_logs TEXT
            )
            """)
        conn.execute("""
            CREATE TABLE papers (
                paper_id TEXT PRIMARY KEY,
                title TEXT,
                md_content TEXT,
                quick_scan TEXT,
                synthesis_data TEXT,
                analysis_report TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
        conn.commit()

    db.init_tables()

    project_columns = _table_columns(db, "projects")
    assert "agent_summary" in project_columns

    paper_columns = _table_columns(db, "papers")
    assert "agent_note" in paper_columns


def test_update_auto_recovers_from_fts_corruption(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    db.init_tables()

    db.insert(
        "papers",
        {
            "paper_id": "p1",
            "title": "origin",
            "md_content": "content",
        },
    )

    with db.get_connection() as conn:
        conn.execute("DROP TABLE papers_fts_data")
        conn.commit()

    affected = db.update(
        "papers",
        {"title": "updated"},
        "paper_id = ?",
        ("p1",),
    )
    assert affected == 1

    row = db.fetchone("SELECT title FROM papers WHERE paper_id = ?", ("p1",))
    assert row is not None
    assert row["title"] == "updated"

    with db.get_connection() as conn:
        conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('integrity-check')")
