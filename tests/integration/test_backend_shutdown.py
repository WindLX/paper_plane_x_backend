"""Exercise the actual application entry point and SIGINT with a queued backlog."""

import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(
    sys.platform == "win32", reason="SIGINT subprocess test uses POSIX signals"
)
@pytest.mark.parametrize("blocked_request", [False, True])
def test_ctrl_c_stops_app_with_backlog(tmp_path: Path, blocked_request: bool) -> None:
    child_code = """
import asyncio
import sys
from pathlib import Path
from paper_plane_x_backend.services.data_process_tasks import lifecycle
from paper_plane_x_backend.services.data_process_tasks.models import DataProcessQueueTask
from paper_plane_x_backend.services.data_process_tasks.task_manager import DataProcessTaskManager

root = Path(sys.argv[1])
started = asyncio.Event()

class BlockingManager(DataProcessTaskManager):
    async def start(self):
        await super().start()
        await self.submit_task(DataProcessQueueTask(task_id="running", paper_id="paper", payload={}))
        await started.wait()
        for index in range(50):
            await self.submit_task(DataProcessQueueTask(task_id=f"queued-{index}", paper_id="paper", payload={}))
        (root / "ready").touch()

    async def _run_data_process_task(self, task):
        if task.task_id != "running":
            (root / "backlog_started").touch()
        started.set()
        await asyncio.Event().wait()

lifecycle._task_manager_instance = BlockingManager(shutdown_timeout=0.1)
from paper_plane_x_backend.main import app, run

@app.get("/blocked")
async def blocked():
    (root / "request_started").touch()
    await asyncio.Event().wait()

# Register the test request before the production console catch-all route.
app.router.routes.insert(0, app.router.routes.pop())
run()
"""
    config_path = tmp_path / "server.toml"
    config_path.write_text("")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {
        **os.environ,
        "PPX_CONFIG_FILE": str(config_path),
        "PPX_DATA_DIR": str(tmp_path),
        "PPX_DATABASE_PATH": str(tmp_path / "app.db"),
        "PPX_LOG__TO_FILE": "false",
        "PPX_API__HOST": "127.0.0.1",
        "PPX_API__PORT": str(port),
        "PPX_API__RELOAD": "false",
        "PPX_API__GRACEFUL_SHUTDOWN_TIMEOUT": "1",
        "PPX_API__CONSOLE_DIST_DIR": str(tmp_path / "console"),
    }
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", child_code, str(tmp_path)],
            env=env,
            stdout=log,
            stderr=log,
        )
        connection: socket.socket | None = None
        try:
            deadline = time.monotonic() + 10
            while not (tmp_path / "ready").exists():
                assert process.poll() is None, "Backend exited before starting workers"
                assert time.monotonic() < deadline, "Backend startup timed out"
                time.sleep(0.02)
            if blocked_request:
                while connection is None:
                    assert process.poll() is None
                    assert time.monotonic() < deadline
                    try:
                        connection = socket.create_connection(
                            ("127.0.0.1", port), timeout=0.1
                        )
                    except ConnectionRefusedError:
                        time.sleep(0.02)
                connection.sendall(b"GET /blocked HTTP/1.1\r\nHost: localhost\r\n\r\n")
                while not (tmp_path / "request_started").exists():
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
            begin = time.monotonic()
            process.send_signal(signal.SIGINT)
            process.wait(timeout=4)
            assert time.monotonic() - begin < 3
            assert process.returncode in {0, -signal.SIGINT}
            assert not (tmp_path / "backlog_started").exists()
        finally:
            if connection is not None:
                connection.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert (
            conn.execute(
                "SELECT status FROM data_process_tasks WHERE task_id = 'running'"
            ).fetchone()[0]
            == "CANCELED"
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM data_process_tasks WHERE status = 'QUEUED'"
            ).fetchone()[0]
            == 50
        )
