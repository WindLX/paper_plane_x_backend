"""Database service tests."""

from pathlib import Path

from paper_plane_x_backend.services.database import Database


def _table_columns(db: Database, table: str) -> list[str]:
    with db.get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


def _table_exists(db: Database, table: str) -> bool:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
    return row is not None


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
    assert not _table_exists(db, "conversations")
    assert not _table_exists(db, "conversation_messages")


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


def test_migration_backs_up_and_drops_legacy_conversation_tables(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "legacy_conversation.sqlite3")

    with db.get_connection() as conn:
        conn.executescript("""
            CREATE TABLE projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                agent_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                operation_logs TEXT
            );
            CREATE TABLE conversations (
                conversation_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New Conversation'
            );
            CREATE TABLE conversation_messages (
                message_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT
            );
            INSERT INTO projects(project_id, name) VALUES ('prj-1', 'Legacy');
            INSERT INTO conversations(conversation_id, project_id, title)
            VALUES ('cnv-1', 'prj-1', 'Legacy Chat');
            INSERT INTO conversation_messages(message_id, conversation_id, role, content)
            VALUES ('msg-1', 'cnv-1', 'user', 'hello');
            """)
        conn.commit()

    db.init_tables()

    assert not _table_exists(db, "conversations")
    assert not _table_exists(db, "conversation_messages")

    backups = sorted(
        (tmp_path / "backups").glob("legacy_conversation_pre_migration_*.db")
    )
    assert backups

    backup_db = Database(backups[-1])
    assert _table_exists(backup_db, "conversations")
    assert _table_exists(backup_db, "conversation_messages")


def test_update_auto_recovers_from_fts_corruption(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    db.init_tables()

    db.insert(
        "papers",
        {
            "paper_id": "pap-test-1",
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
        ("pap-test-1",),
    )
    assert affected == 1

    row = db.fetchone("SELECT title FROM papers WHERE paper_id = ?", ("pap-test-1",))
    assert row is not None
    assert row["title"] == "updated"

    with db.get_connection() as conn:
        conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('integrity-check')")
