#!/usr/bin/env python3
"""数据库 ID 前缀化迁移脚本（重建数据库版本）.

将所有业务 UUID 改为带前缀格式：
- papers.paper_id       → pap-{hex}
- projects.project_id   → prj-{hex}
- data_process_tasks.task_id → tsk-{hex}
- agent_traces.trace_id → trc-{hex}

策略：读取旧库全部数据 → 内存中替换 ID → 创建全新数据库 → 原子替换旧库。
完全避免 UPDATE PRIMARY KEY 触发 FTS5/触发器的问题。

用法:
    python scripts/migrate_ids.py           # 执行迁移
    python scripts/migrate_ids.py --dry-run # 仅预览变更统计
"""

import argparse
import json
import logging
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from paper_plane_x_backend.config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("migrate_ids")


def _generate_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _is_prefixed(value: str | None) -> bool:
    if not value:
        return False
    return value.startswith(("pap-", "prj-", "tsk-", "trc-"))


def _resolve_caller_id(
    caller_id: str | None, task_map: dict, trace_map: dict
) -> str | None:
    """解析 caller_id：可能是 task_id 或 trace_id，按顺序匹配."""
    if not caller_id or _is_prefixed(caller_id):
        return caller_id
    if caller_id in task_map:
        return task_map[caller_id]
    if caller_id in trace_map:
        return trace_map[caller_id]
    return caller_id


def backup_database(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.parent / f"app.db.backup-{timestamp}"
    shutil.copy2(db_path, backup_path)
    logger.info("数据库已备份到 %s", backup_path)
    return backup_path


def build_mappings(conn: sqlite3.Connection) -> tuple[dict, dict, dict, dict]:
    paper_map: dict[str, str] = {}
    project_map: dict[str, str] = {}
    task_map: dict[str, str] = {}
    trace_map: dict[str, str] = {}

    for (old_id,) in conn.execute("SELECT paper_id FROM papers"):
        if old_id and not _is_prefixed(old_id):
            paper_map[old_id] = _generate_id("pap")

    for (old_id,) in conn.execute("SELECT project_id FROM projects"):
        if old_id and not _is_prefixed(old_id):
            project_map[old_id] = _generate_id("prj")

    for (old_id,) in conn.execute("SELECT task_id FROM data_process_tasks"):
        if old_id and not _is_prefixed(old_id):
            task_map[old_id] = _generate_id("tsk")

    for (old_id,) in conn.execute("SELECT trace_id FROM agent_traces"):
        if old_id and not _is_prefixed(old_id):
            trace_map[old_id] = _generate_id("trc")

    logger.info(
        "映射统计: papers=%d, projects=%d, tasks=%d, traces=%d",
        len(paper_map),
        len(project_map),
        len(task_map),
        len(trace_map),
    )
    return paper_map, project_map, task_map, trace_map


def get_schema(conn: sqlite3.Connection) -> list[str]:
    """获取所有 DDL 语句（排除 sqlite_sequence 和 FTS5 内部辅助表）."""
    rows = conn.execute("""
        SELECT sql FROM sqlite_master
        WHERE sql IS NOT NULL
          AND name != 'sqlite_sequence'
          AND name NOT LIKE '%\\_config' ESCAPE '\'
          AND name NOT LIKE '%\\_content' ESCAPE '\'
          AND name NOT LIKE '%\\_data' ESCAPE '\'
          AND name NOT LIKE '%\\_docsize' ESCAPE '\'
          AND name NOT LIKE '%\\_idx' ESCAPE '\'
        ORDER BY type, name
        """).fetchall()
    return [row[0] for row in rows]


def migrate_table(
    old_conn: sqlite3.Connection,
    new_conn: sqlite3.Connection,
    table: str,
    columns: list[str],
    id_columns: list[str],
    paper_map: dict,
    project_map: dict,
    task_map: dict,
    trace_map: dict,
    json_trace_columns: list[str] | None = None,
    caller_id_column: str | None = None,
) -> int:
    """迁移单表数据，替换指定列中的 ID."""
    json_trace_columns = json_trace_columns or []
    rows = old_conn.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()

    placeholders = ", ".join("?" for _ in columns)
    insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"

    count = 0
    for row in rows:
        row_dict = dict(row)

        # 替换主键/外键列
        for col in id_columns:
            old_val = row_dict.get(col)
            if old_val is None:
                continue
            if col == "paper_id" and old_val in paper_map:
                row_dict[col] = paper_map[old_val]
            elif col == "project_id" and old_val in project_map:
                row_dict[col] = project_map[old_val]
            elif col == "task_id" and old_val in task_map:
                row_dict[col] = task_map[old_val]
            elif col == "trace_id" and old_val in trace_map:
                row_dict[col] = trace_map[old_val]
            elif col == "retry_of_task_id" and old_val in task_map:
                row_dict[col] = task_map[old_val]

        # 替换 JSON trace_ids 列
        for col in json_trace_columns:
            value = row_dict.get(col)
            if not value:
                continue
            try:
                trace_ids: list[str] = json.loads(value)
                if isinstance(trace_ids, list):
                    new_trace_ids = [trace_map.get(tid, tid) for tid in trace_ids]
                    if new_trace_ids != trace_ids:
                        row_dict[col] = json.dumps(new_trace_ids)
            except (json.JSONDecodeError, TypeError):
                pass

        # 替换 caller_id
        if caller_id_column and caller_id_column in row_dict:
            old_caller = row_dict[caller_id_column]
            row_dict[caller_id_column] = _resolve_caller_id(
                old_caller, task_map, trace_map
            )

        new_conn.execute(insert_sql, [row_dict[c] for c in columns])
        count += 1

    logger.info("%s 表迁移 %d 行", table, count)
    return count


def rebuild_database(
    db_path: Path,
    paper_map: dict,
    project_map: dict,
    task_map: dict,
    trace_map: dict,
    dry_run: bool,
) -> None:
    """重建整个数据库，避免 UPDATE PRIMARY KEY 的问题."""
    new_db_path = db_path.parent / "app.db.new"

    if dry_run:
        logger.info("=== DRY RUN 模式，仅预览，不创建新数据库 ===")
        return

    with sqlite3.connect(str(db_path)) as old_conn:
        old_conn.row_factory = sqlite3.Row

        # 创建新数据库
        if new_db_path.exists():
            new_db_path.unlink()

        with sqlite3.connect(str(new_db_path)) as new_conn:
            # 复制 schema（DDL）
            for ddl in get_schema(old_conn):
                new_conn.execute(ddl)

            # 禁用外键检查（避免插入顺序问题）
            new_conn.execute("PRAGMA foreign_keys = OFF")

            # 迁移各表（注意：普通表先插入，FTS 虚拟表由触发器自动维护）
            migrate_table(
                old_conn,
                new_conn,
                "projects",
                [
                    "project_id",
                    "name",
                    "description",
                    "agent_summary",
                    "created_at",
                    "updated_at",
                    "operation_logs",
                ],
                ["project_id"],
                paper_map,
                project_map,
                task_map,
                trace_map,
            )
            migrate_table(
                old_conn,
                new_conn,
                "papers",
                [
                    "paper_id",
                    "title",
                    "authors",
                    "year",
                    "publication",
                    "doi",
                    "custom_meta",
                    "md_content",
                    "raw_pdf_path",
                    "raw_pdf_sha256",
                    "images_paths",
                    "extraction_status",
                    "quick_scan",
                    "synthesis_data",
                    "analysis_report",
                    "extraction_fact_check_status",
                    "extraction_fact_check_result",
                    "analysis_fact_check_status",
                    "analysis_fact_check_result",
                    "agent_note",
                    "extraction_retry_count",
                    "analysis_retry_count",
                    "created_at",
                    "updated_at",
                ],
                ["paper_id"],
                paper_map,
                project_map,
                task_map,
                trace_map,
            )
            migrate_table(
                old_conn,
                new_conn,
                "paper_projects",
                ["paper_id", "project_id", "created_at"],
                ["paper_id", "project_id"],
                paper_map,
                project_map,
                task_map,
                trace_map,
            )
            migrate_table(
                old_conn,
                new_conn,
                "data_process_tasks",
                [
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
                ],
                ["task_id", "paper_id", "retry_of_task_id"],
                paper_map,
                project_map,
                task_map,
                trace_map,
                json_trace_columns=[
                    "extraction_trace_ids",
                    "analysis_trace_ids",
                    "extraction_fact_check_trace_ids",
                    "analysis_fact_check_trace_ids",
                ],
            )
            migrate_table(
                old_conn,
                new_conn,
                "agent_traces",
                [
                    "trace_id",
                    "agent_name",
                    "messages",
                    "llm_model",
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "usage_payload",
                    "caller",
                    "caller_id",
                    "created_at",
                ],
                ["trace_id"],
                paper_map,
                project_map,
                task_map,
                trace_map,
                caller_id_column="caller_id",
            )

            new_conn.commit()

    # 原子替换：旧库 → 备份，新库 → 正式
    backup_old = (
        db_path.parent / f"app.db.replaced-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.move(str(db_path), str(backup_old))
    shutil.move(str(new_db_path), str(db_path))
    logger.info("数据库已原子替换，旧库保存到 %s", backup_old)


def main() -> int:
    parser = argparse.ArgumentParser(description="数据库 ID 前缀化迁移")
    parser.add_argument(
        "--dry-run", action="store_true", help="仅预览变更统计，不写入数据库"
    )
    args = parser.parse_args()

    db_path = Path(settings.database_path)
    if not db_path.exists():
        logger.error("数据库文件不存在: %s", db_path)
        return 1

    # 先备份原始数据库
    backup_database(db_path)

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        paper_map, project_map, task_map, trace_map = build_mappings(conn)

    total = len(paper_map) + len(project_map) + len(task_map) + len(trace_map)
    if total == 0:
        logger.info("所有 ID 已经是新格式，无需迁移")
        return 0

    if args.dry_run:
        logger.info("=== DRY RUN 模式，不会写入数据库 ===")
        return 0

    rebuild_database(
        db_path, paper_map, project_map, task_map, trace_map, dry_run=False
    )
    logger.info("迁移完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
