"""Read-only project overview aggregation.

The overview never calls a model. It combines current project papers, the latest
task per paper, sandbox files, recent activities, and the existing pure
``global_finder_by_project`` statistics query.
"""

from __future__ import annotations

import heapq
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from paper_plane_x_backend.models import (
    DataProcessTaskStatus,
    ExtractionStatus,
    FactCheckStatus,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.librarian import global_finder_by_project
from paper_plane_x_backend.services.paper.repository import (
    PaperQueryRepository,
    PaperRepositoryError,
)
from paper_plane_x_backend.services.project.activity import ProjectActivityStore
from paper_plane_x_backend.services.project.files import (
    ALLOWED_EXTENSIONS,
    ProjectFileError,
    get_project_file_manager,
)
from paper_plane_x_backend.services.project.images import IMAGE_EXTENSIONS
from paper_plane_x_backend.services.project.repository import ProjectRepository

logger = logging.getLogger(__name__)

DEFAULT_TOP_TAGS_LIMIT = 8
DEFAULT_RECENT_LIMIT = 5
DEFAULT_ATTENTION_LIMIT = 10

_ACTIVE_TASK_STATUSES = (
    DataProcessTaskStatus.QUEUED.value,
    DataProcessTaskStatus.RUNNING.value,
    DataProcessTaskStatus.CANCELING.value,
)

_EMPTY_YEAR_DISTRIBUTION: dict[str, Any] = {
    "available_count": 0,
    "missing_count": 0,
    "mean": None,
    "variance": None,
    "median": None,
    "mode_years": [],
    "q25": None,
    "q75": None,
    "outlier_count": 0,
    "low_outlier_count": 0,
    "high_outlier_count": 0,
}


def _classify_extension(suffix: str) -> str | None:
    if suffix in ALLOWED_EXTENSIONS:
        return "text"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_json_dict(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return {str(k): v for k, v in cast(dict[Any, Any], value).items()}
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return {str(k): v for k, v in cast(dict[Any, Any], parsed).items()}
    return None


def _extract_error(value: object) -> str | None:
    payload = _as_json_dict(value)
    if payload is None:
        return None
    error = payload.get("error")
    return error if isinstance(error, str) else None


def _format_datetime(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else None


def _has_parsed_content(paper: dict[str, Any]) -> bool:
    md_content = paper.get("md_content")
    return isinstance(md_content, str) and bool(md_content.strip())


class ProjectOverviewService:
    """Build the readonly project workbench overview payload."""

    def __init__(
        self,
        db: Database,
        *,
        top_tags_limit: int = DEFAULT_TOP_TAGS_LIMIT,
        recent_limit: int = DEFAULT_RECENT_LIMIT,
        attention_limit: int = DEFAULT_ATTENTION_LIMIT,
    ) -> None:
        self._db = db
        self._top_tags_limit = top_tags_limit
        self._recent_limit = recent_limit
        self._attention_limit = attention_limit
        self._project_repo = ProjectRepository(db)
        self._query_repo = PaperQueryRepository(db)
        self._activity_store = ProjectActivityStore(db)

    def build(self, project_id: str) -> dict[str, Any]:
        """Aggregate the overview for one project.

        Raises:
            ProjectRepositoryError: when the project does not exist.
        """
        self._project_repo.ensure_exists(project_id)
        section_errors: dict[str, str] = {}
        agent_summary = self._project_repo.get_agent_summary(project_id)

        papers = self._load_project_papers(project_id)
        latest_tasks = self._load_latest_tasks(project_id)
        active_task_count = self._count_active_tasks(project_id)
        all_attention_items = self._build_attention(papers, latest_tasks)
        attention_items = all_attention_items[: self._attention_limit]
        parsed_count = sum(1 for paper in papers if _has_parsed_content(paper))

        top_tags, year_distribution, year_range = self._load_statistics(
            project_id, section_errors
        )

        recent_files, files_error = self._scan_recent_files(project_id)
        if files_error is not None:
            section_errors["recent_files"] = files_error

        recent_activities, activity_error = self._load_recent_activities(project_id)
        if activity_error is not None:
            section_errors["recent_activities"] = activity_error

        return {
            "project_id": project_id,
            "agent_summary": agent_summary,
            "stats": {
                "paper_count": len(papers),
                "parsed_count": parsed_count,
                "active_task_count": active_task_count,
                "attention_count": len(all_attention_items),
            },
            "attention_items": attention_items,
            "recent_papers": [
                {
                    "paper_id": str(paper.get("paper_id") or ""),
                    "title": _optional_str(paper.get("title")),
                    "updated_at": _format_datetime(paper.get("updated_at")),
                }
                for paper in papers[: self._recent_limit]
            ],
            "recent_files": recent_files,
            "recent_activities": recent_activities,
            "top_tags": top_tags,
            "year_distribution": year_distribution,
            "year_range": year_range,
            "section_errors": section_errors,
        }

    # ------------------------------------------------------------------
    # papers, tasks, attention
    # ------------------------------------------------------------------
    def _load_project_papers(self, project_id: str) -> list[dict[str, Any]]:
        return self._db.fetchall(
            """
            SELECT
                p.paper_id,
                p.title,
                p.updated_at,
                p.md_content,
                p.extraction_status,
                p.extraction_fact_check_status,
                p.analysis_fact_check_status,
                p.extraction_fact_check_result,
                p.analysis_fact_check_result
            FROM papers p
            JOIN paper_projects pp ON pp.paper_id = p.paper_id
            WHERE pp.project_id = ?
            ORDER BY p.updated_at DESC, p.paper_id ASC
            """,
            (project_id,),
        )

    def _load_latest_tasks(self, project_id: str) -> dict[str, dict[str, Any]]:
        rows = self._db.fetchall(
            """
            SELECT * FROM (
                SELECT
                    t.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY t.paper_id
                        ORDER BY t.created_at DESC, t.task_id DESC
                    ) AS row_number
                FROM data_process_tasks t
                WHERE t.paper_id IN (
                    SELECT paper_id FROM paper_projects WHERE project_id = ?
                )
            )
            WHERE row_number = 1
            """,
            (project_id,),
        )
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            paper_id = row.get("paper_id")
            if isinstance(paper_id, str) and paper_id:
                latest[paper_id] = row
        return latest

    def _count_active_tasks(self, project_id: str) -> int:
        placeholders = ", ".join("?" for _ in _ACTIVE_TASK_STATUSES)
        row = self._db.fetchone(
            f"""
            SELECT COUNT(*) AS count
            FROM data_process_tasks t
            JOIN paper_projects pp ON pp.paper_id = t.paper_id
            WHERE pp.project_id = ? AND t.status IN ({placeholders})
            """,
            (project_id, *_ACTIVE_TASK_STATUSES),
        )
        return int(row["count"]) if row else 0

    def _build_attention(
        self,
        papers: list[dict[str, Any]],
        latest_tasks: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for paper in papers:
            paper_id = str(paper.get("paper_id") or "")
            if not paper_id:
                continue
            title = _optional_str(paper.get("title"))
            task = latest_tasks.get(paper_id)
            task_id = _optional_str(task.get("task_id")) if task else None

            if (
                task is not None
                and task.get("status") == DataProcessTaskStatus.FAILED.value
            ):
                items.append(
                    {
                        "paper_id": paper_id,
                        "title": title,
                        "stage": "task_failed",
                        "error": _optional_str(task.get("error")),
                        "task_id": task_id,
                    }
                )
                continue

            extraction_status = paper.get("extraction_status")
            if extraction_status == ExtractionStatus.FAILED.value:
                items.append(
                    {
                        "paper_id": paper_id,
                        "title": title,
                        "stage": "parse_failed",
                        "error": _extract_error(
                            paper.get("extraction_fact_check_result")
                        ),
                        "task_id": task_id,
                    }
                )
                continue

            if extraction_status in {
                ExtractionStatus.PENDING.value,
                ExtractionStatus.PROCESSING.value,
            }:
                # Still being processed; a failed task would already have matched above.
                continue

            if (
                paper.get("extraction_fact_check_status")
                == FactCheckStatus.FAILED.value
            ):
                items.append(
                    {
                        "paper_id": paper_id,
                        "title": title,
                        "stage": "extraction_fact_check_failed",
                        "error": _extract_error(
                            paper.get("extraction_fact_check_result")
                        ),
                        "task_id": task_id,
                    }
                )
                continue

            if paper.get("analysis_fact_check_status") == FactCheckStatus.FAILED.value:
                items.append(
                    {
                        "paper_id": paper_id,
                        "title": title,
                        "stage": "analysis_fact_check_failed",
                        "error": _extract_error(
                            paper.get("analysis_fact_check_result")
                        ),
                        "task_id": task_id,
                    }
                )
        return items

    # ------------------------------------------------------------------
    # statistics
    # ------------------------------------------------------------------
    def _load_statistics(
        self,
        project_id: str,
        section_errors: dict[str, str],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
        try:
            payload = global_finder_by_project(
                paper_repo=self._query_repo,
                project_repo=self._project_repo,
                project_id=project_id,
                top_tags_limit=self._top_tags_limit,
            )
        except PaperRepositoryError as exc:
            section_errors["year_distribution"] = exc.message
            section_errors["top_tags"] = exc.message
            return [], dict(_EMPTY_YEAR_DISTRIBUTION), None

        stats_obj = payload.get("stats")
        stats: dict[str, Any] = (
            {str(k): v for k, v in cast(dict[Any, Any], stats_obj).items()}
            if isinstance(stats_obj, dict)
            else {}
        )

        top_tags: list[dict[str, Any]] = []
        top_tags_raw = stats.get("top_tags")
        if isinstance(top_tags_raw, list):
            for item in cast(list[Any], top_tags_raw):
                if not isinstance(item, dict):
                    continue
                item_dict = cast(dict[str, Any], item)
                tag = item_dict.get("tag")
                if tag is None:
                    continue
                count = item_dict.get("count")
                top_tags.append(
                    {
                        "tag": str(tag),
                        "count": count if isinstance(count, int) else 0,
                    }
                )

        year_distribution_raw = stats.get("year_distribution")
        year_distribution: dict[str, Any] = (
            {str(k): v for k, v in cast(dict[Any, Any], year_distribution_raw).items()}
            if isinstance(year_distribution_raw, dict)
            else dict(_EMPTY_YEAR_DISTRIBUTION)
        )
        year_range = stats.get("year_range")
        return (
            top_tags,
            year_distribution,
            year_range if isinstance(year_range, str) else None,
        )

    # ------------------------------------------------------------------
    # sandbox files
    # ------------------------------------------------------------------
    def _scan_recent_files(
        self,
        project_id: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            root = get_project_file_manager().sandbox_root(project_id)
        except ProjectFileError as exc:
            logger.warning(
                "event=project.overview.recent_files_root_failed project_id=%s error=%s",
                project_id,
                exc.message,
            )
            return [], exc.message

        if not root.exists() or not root.is_dir():
            return [], None

        heap: list[tuple[float, str, str, int]] = []
        skipped = 0
        walk_error: str | None = None
        try:
            for path in root.rglob("*"):
                if path.is_symlink() or not path.is_file():
                    continue
                kind = _classify_extension(path.suffix.lower())
                if kind is None:
                    continue
                try:
                    resolved = path.resolve()
                    stat = resolved.stat()
                    relative = resolved.relative_to(root).as_posix()
                except (OSError, ValueError):
                    skipped += 1
                    continue
                entry = (stat.st_mtime, f"/{relative}", kind, stat.st_size)
                if len(heap) < self._recent_limit:
                    heapq.heappush(heap, entry)
                elif entry[0] > heap[0][0]:
                    heapq.heapreplace(heap, entry)
        except OSError as exc:
            walk_error = str(exc)

        files = [
            {
                "file_path": file_path,
                "name": Path(file_path).name,
                "kind": kind,
                "size": size,
                "updated_at": datetime.fromtimestamp(mtime).isoformat(),
            }
            for mtime, file_path, kind, size in sorted(heap, reverse=True)
        ]
        if walk_error is not None:
            return files, walk_error
        if skipped:
            return files, f"{skipped} file(s) skipped while scanning"
        return files, None

    # ------------------------------------------------------------------
    # activities
    # ------------------------------------------------------------------
    def _load_recent_activities(
        self,
        project_id: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            records, _ = self._activity_store.list(
                project_id,
                limit=self._recent_limit,
            )
        except sqlite3.Error as exc:
            logger.warning(
                "event=project.overview.activities_failed project_id=%s error=%s",
                project_id,
                exc,
            )
            return [], str(exc)
        return [record.to_payload() for record in records], None


__all__ = [
    "DEFAULT_ATTENTION_LIMIT",
    "DEFAULT_RECENT_LIMIT",
    "DEFAULT_TOP_TAGS_LIMIT",
    "ProjectOverviewService",
]
