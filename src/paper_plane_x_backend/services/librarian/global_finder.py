"""Librarian Global Finder 统计逻辑。"""

from __future__ import annotations

from collections import Counter
from math import floor
from typing import Any, cast

from paper_plane_x_backend.services.paper.repository import PaperQueryRepository
from paper_plane_x_backend.services.project.repository import ProjectRepository


def _compute_percentile(sorted_values: list[int], percentile: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    rank = (len(sorted_values) - 1) * percentile
    lower_index = floor(rank)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]
    weight = rank - lower_index
    return float(lower_value + (upper_value - lower_value) * weight)


def _build_year_distribution(
    years: list[int],
    total_paper_count: int,
) -> tuple[dict[str, object], int, int]:
    if not years:
        return (
            {
                "available_count": 0,
                "missing_count": total_paper_count,
                "mean": None,
                "variance": None,
                "median": None,
                "mode_years": [],
                "q25": None,
                "q75": None,
                "outlier_count": 0,
                "low_outlier_count": 0,
                "high_outlier_count": 0,
            },
            0,
            0,
        )

    sorted_years = sorted(years)
    count = len(sorted_years)
    mean = sum(sorted_years) / count
    variance = sum((year - mean) ** 2 for year in sorted_years) / count
    median = _compute_percentile(sorted_years, 0.5)
    q25 = _compute_percentile(sorted_years, 0.25)
    q75 = _compute_percentile(sorted_years, 0.75)
    p05 = _compute_percentile(sorted_years, 0.05)
    p95 = _compute_percentile(sorted_years, 0.95)
    min_year = sorted_years[0]
    max_year = sorted_years[-1]

    counter = Counter(sorted_years)
    top_mode_count = max(counter.values())
    mode_years = sorted(
        [year for year, freq in counter.items() if freq == top_mode_count]
    )

    assert p05 is not None and p95 is not None
    low_outlier_count = sum(1 for year in sorted_years if year < p05)
    high_outlier_count = sum(1 for year in sorted_years if year > p95)

    return (
        {
            "available_count": count,
            "missing_count": max(0, total_paper_count - count),
            "mean": mean,
            "variance": variance,
            "median": median,
            "mode_years": mode_years,
            "q25": q25,
            "q75": q75,
            "outlier_count": low_outlier_count + high_outlier_count,
            "low_outlier_count": low_outlier_count,
            "high_outlier_count": high_outlier_count,
        },
        min_year,
        max_year,
    )


def global_finder_by_project(
    paper_repo: PaperQueryRepository,
    project_repo: ProjectRepository | None,
    project_id: str,
    top_tags_limit: int,
) -> dict[str, object]:
    """按 project 聚合基础论文概览与全局统计。"""
    rows = paper_repo.list_project_paper_overview(project_id=project_id)

    papers: list[dict[str, object]] = []
    years: list[int] = []
    tag_counter: Counter[str] = Counter()

    for row in rows:
        year_value = row.get("year")
        if isinstance(year_value, int):
            years.append(year_value)

        quick_scan_value = row.get("quick_scan")
        quick_scan_dict: dict[str, Any] | None = (
            cast(dict[str, Any], quick_scan_value)
            if isinstance(quick_scan_value, dict)
            else None
        )
        tags: list[str] = []
        if quick_scan_dict is not None:
            raw_tags = quick_scan_dict.get("tags")
            if isinstance(raw_tags, list):
                raw_tags_list = cast(list[Any], raw_tags)
                tags = [
                    tag for tag in raw_tags_list if isinstance(tag, str) and tag.strip()
                ]
                tag_counter.update(tags)

        papers.append(
            {
                "paper_id": str(row.get("paper_id") or ""),
                "title": (
                    row.get("title") if isinstance(row.get("title"), str) else None
                ),
                "authors": (
                    [author for author in cast(list[str], row.get("authors", []))]
                    if isinstance(row.get("authors"), list)
                    else []
                ),
                "year": year_value if isinstance(year_value, int) else None,
                "quick_scan": (
                    {
                        "tags": tags,
                        "verdict": (
                            quick_scan_dict.get("verdict")
                            if isinstance(quick_scan_dict.get("verdict"), str)
                            else None
                        ),
                        "reason": (
                            quick_scan_dict.get("reason")
                            if isinstance(quick_scan_dict.get("reason"), str)
                            else None
                        ),
                        "quick_summary": (
                            quick_scan_dict.get("quick_summary")
                            if isinstance(quick_scan_dict.get("quick_summary"), str)
                            else None
                        ),
                    }
                    if quick_scan_dict is not None
                    else None
                ),
            }
        )

    top_tags = [
        {"tag": tag, "count": count}
        for tag, count in sorted(
            tag_counter.items(), key=lambda item: (-item[1], item[0])
        )[:top_tags_limit]
    ]

    agent_summary: str | None = None
    if project_repo is not None:
        agent_summary = project_repo.get_agent_summary(project_id)

    year_dist, min_year, max_year = _build_year_distribution(
        years, total_paper_count=len(rows)
    )

    return {
        "project_id": project_id,
        "papers": papers,
        "agent_summary": agent_summary,
        "stats": {
            "paper_count": len(papers),
            "top_tags_limit": top_tags_limit,
            "year_range": (
                f"{min_year}-{max_year}"
                if min_year is not None and max_year is not None
                else None
            ),
            "year_distribution": year_dist,
            "top_tags": top_tags,
        },
    }
