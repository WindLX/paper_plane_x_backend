"""Verify explicit repair and its database backup using temporary data."""

import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from paper_plane_x_backend.models import ExtractionStatus
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.paper.repository import PaperRepository


def test_repair_command_backs_up_before_updating(db: Database) -> None:
    repo = PaperRepository(db)
    paper = repo.create(extraction_status=ExtractionStatus.PROCESSING)
    db.insert(
        "data_process_tasks",
        {
            "task_id": "canceled",
            "paper_id": paper.paper_id,
            "payload": "{}",
            "status": "CANCELED",
            "created_at": datetime.now(),
        },
    )
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "repair_interrupted_papers.py"
    )
    command = [sys.executable, str(script), "--database", str(db.db_path)]
    result = subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=10
    )
    assert "interrupted_papers=1" in result.stdout
    latest = repo.get(paper.paper_id)
    assert latest is not None
    assert latest.extraction_status == ExtractionStatus.PROCESSING
    result = subprocess.run(
        [*command, "--apply"], check=True, capture_output=True, text=True, timeout=10
    )
    assert "repaired_papers=1" in result.stdout
    backup_path = Path(
        next(
            line.removeprefix("backup=")
            for line in result.stdout.splitlines()
            if line.startswith("backup=")
        )
    )
    try:
        assert backup_path.stat().st_mode & 0o777 == 0o600
        with sqlite3.connect(backup_path) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert (
                conn.execute(
                    "SELECT extraction_status FROM papers WHERE paper_id = ?",
                    (paper.paper_id,),
                ).fetchone()[0]
                == "PROCESSING"
            )
        latest = repo.get(paper.paper_id)
        assert latest is not None
        assert latest.extraction_status == ExtractionStatus.FAILED
        result = subprocess.run(
            [*command, "--apply"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "interrupted_papers=0" in result.stdout
        assert "backup=" not in result.stdout
    finally:
        backup_path.unlink()
