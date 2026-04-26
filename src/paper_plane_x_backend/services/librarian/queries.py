"""Librarian 查询辅助逻辑。"""

from typing import Any

from paper_plane_x_backend.services.paper.repository import (
    PaperQueryRepository,
    PaperRepositoryError,
)


def matrix_fetch_by_paths(
    *,
    repo: PaperQueryRepository,
    paper_ids: list[str],
    field_paths: list[str],
) -> dict[str, dict[str, Any]]:
    """按 field_paths 拉取多篇论文的矩阵结果。"""
    if not paper_ids:
        raise PaperRepositoryError("paper_ids cannot be empty")
    if not field_paths:
        raise PaperRepositoryError("field_paths cannot be empty")

    result: dict[str, dict[str, Any]] = {}
    for paper_id in paper_ids:
        row: dict[str, Any] = {}
        for field_path in field_paths:
            row[field_path] = repo.fetch_by_path(
                paper_id=paper_id,
                field_path=field_path,
            )
        result[paper_id] = row
    return result
