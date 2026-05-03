"""Librarian 字段说明与 guide 构造。"""

from __future__ import annotations

from types import UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from paper_plane_x_backend.schemas.agent_io.data_processor import (
    AnalysisReport,
    QuickScan,
    SynthesisData,
)
from paper_plane_x_backend.services.app_settings import get_app_settings_repo


def _unwrap_type(annotation: Any) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Annotated and args:
        return _unwrap_type(args[0])

    if origin in (Union, UnionType) and args:
        non_none_types = [arg for arg in args if arg is not type(None)]
        if len(non_none_types) == 1:
            return _unwrap_type(non_none_types[0])

    return annotation


def _collect_model_paths(model_cls: type[BaseModel], root: str) -> list[str]:
    paths: list[str] = [root]

    for field_name, field_info in model_cls.model_fields.items():
        field_path = f"{root}.{field_name}"
        paths.append(field_path)

        annotation = _unwrap_type(field_info.annotation)
        origin = get_origin(annotation)

        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths.extend(_collect_model_paths(annotation, field_path))
            continue

        if origin is list:
            item_types = get_args(annotation)
            if not item_types:
                continue

            item_type = _unwrap_type(item_types[0])
            list_item_path = f"{field_path}[0]"
            paths.append(list_item_path)

            if isinstance(item_type, type) and issubclass(item_type, BaseModel):
                paths.extend(_collect_model_paths(item_type, list_item_path))

    return paths


def _build_schema_from_annotation(annotation: Any) -> object:
    normalized = _unwrap_type(annotation)
    origin = get_origin(normalized)

    if origin is Literal:
        values = [str(item) for item in get_args(normalized)]
        return " | ".join(values)

    if origin is list:
        item_types = get_args(normalized)
        if not item_types:
            return ["unknown"]
        return [_build_schema_from_annotation(item_types[0])]

    if isinstance(normalized, type):
        if issubclass(normalized, BaseModel):
            return _build_schema_from_model(normalized)
        if normalized is str:
            return "string"
        if normalized is int:
            return "number"
        if normalized is float:
            return "number"
        if normalized is bool:
            return "boolean"

    return "unknown"


def _build_schema_from_model(model_cls: type[BaseModel]) -> dict[str, object]:
    schema: dict[str, object] = {}
    for field_name, field_info in model_cls.model_fields.items():
        schema[field_name] = _build_schema_from_annotation(field_info.annotation)
    return schema


def _build_projection_field_tree() -> dict[str, object]:
    return {
        "meta": {
            "title": "string | null",
            "authors": ["string"],
            "year": "number | null",
            "publication": "string | null",
            "doi": "string | null",
            "custom_meta": {
                "<key>": "unknown",
            },
            "raw_pdf_path": "string | null",
            "raw_pdf_sha256": "string | null",
        },
        "custom_meta": {
            "<key>": "unknown",
        },
        "md_content": "string | null",
        "quick_scan": _build_schema_from_model(QuickScan),
        "synthesis_data": _build_schema_from_model(SynthesisData),
        "analysis_report": _build_schema_from_model(AnalysisReport),
        "notes": {
            "array_access": (
                "数组字段使用 [index] 继续访问，例如 "
                "analysis_report.prerequisites[0].concept_name"
            ),
            "nullable": "任意节点都可能为 null，取决于论文当前处理状态和数据完整性",
        },
    }


def _build_query_field_tree() -> dict[str, object]:
    return {
        "meta": {
            "title": "CONTAINS string",
            "authors": "CONTAINS string",
            "year": "BETWEEN [start, end]",
            "publication": "CONTAINS string",
            "doi": "CONTAINS string",
            "custom_meta": {
                "<key>": "CONTAINS string",
            },
        },
        "year": "BETWEEN [start, end]",
        "md_content": "CONTAINS string",
        "quick_scan": _build_schema_from_model(QuickScan),
        "synthesis_data": _build_schema_from_model(SynthesisData),
        "analysis_report": _build_schema_from_model(AnalysisReport),
        "notes": {
            "operators": {
                "CONTAINS": "除年份外的字段统一使用 CONTAINS，按文本进行大小写不敏感匹配",
                "BETWEEN": "仅 year / meta.year 支持 BETWEEN，格式固定为 [start, end]",
            },
            "array_matching": (
                "数组和对象会先转成 JSON 文本再参与 CONTAINS 匹配，因此可命中嵌套内容"
            ),
        },
    }


def build_field_paths_guide() -> str:
    """构造可复用的 field_paths 说明文本。"""
    meta_manual_lines = [
        "meta：",
        "- meta：返回整棵元数据对象。",
        "- meta.title / meta.authors / meta.year / meta.publication / meta.doi。",
        "- meta.raw_pdf_path / meta.raw_pdf_sha256。",
        "- meta.custom_meta：返回自定义元数据对象。",
        "- meta.custom_meta.<key>：读取 custom_meta 下的任意键。",
        "- custom_meta 与 custom_meta.<key> 也可直接使用（与 meta.custom_meta 等价）。",
    ]

    structured_roots: list[tuple[str, type[BaseModel]]] = [
        ("quick_scan", QuickScan),
        ("synthesis_data", SynthesisData),
        ("analysis_report", AnalysisReport),
    ]

    structured_sections: list[str] = []
    for root, model_cls in structured_roots:
        structured_sections.append(f"{root}（由 {model_cls.__name__} 自动提取）：")
        for path in _collect_model_paths(model_cls, root):
            structured_sections.append(f"- {path}")

    return "\n".join(
        [
            "可用 field_paths：",
            "- md_content：原始 Markdown 全文。",
            *meta_manual_lines,
            *structured_sections,
            "数组取值规则：使用 [index] 访问元素，例如 analysis_report.prerequisites[0].concept_name。",
        ]
    )


def build_librarian_guide_payload() -> dict[str, object]:
    """构造前端与 API 共用的结构化 guide payload。"""
    projection_field_tree = _build_projection_field_tree()
    return {
        "field_paths_guide": build_field_paths_guide(),
        "global_finder_schema": {
            "request": {
                "project_id": "string",
            },
            "response": {
                "project_id": "string",
                "papers": [
                    {
                        "paper_id": "string",
                        "title": "string | null",
                        "authors": ["string"],
                        "year": "number | null",
                        "quick_scan": {
                            "tags": ["string"],
                            "verdict": "string | null",
                            "reason": "string | null",
                            "quick_summary": "string | null",
                        },
                    }
                ],
                "stats": {
                    "paper_count": "number",
                    "top_tags_limit": "number",
                    "year_distribution": {
                        "available_count": "number",
                        "missing_count": "number",
                        "mean": "number | null",
                        "variance": "number | null",
                        "median": "number | null",
                        "mode_years": ["number"],
                        "q25": "number | null",
                        "q75": "number | null",
                        "outlier_count": "number",
                        "low_outlier_count": "number",
                        "high_outlier_count": "number",
                    },
                    "top_tags": [
                        {
                            "tag": "string",
                            "count": "number",
                        }
                    ],
                },
            },
        },
        "query_schema": {
            "mode": "query_expr | paper_id",
            "project_id": "可选，限定 project 作用域",
            "paper_id": "精确匹配单篇论文",
            "query_expr": _build_query_field_tree(),
            "paging": {
                "limit": "number",
                "offset": "number",
            },
        },
        "projection_schema": {
            "request": {
                "paper_id": "string",
                "field_path": projection_field_tree,
            },
            "response": {
                "paper_id": "string",
                "field_path": "string",
                "value": "any | null",
            },
        },
        "matrix_schema": {
            "request": {
                "paper_ids": ["paper_id"],
                "field_paths": projection_field_tree,
            },
            "response": {
                "paper_ids": ["paper_id"],
                "field_paths": ["field_path"],
                "items": {
                    "<paper_id>": {
                        "<field_path>": "value | null",
                    }
                },
            },
        },
        "query_examples": [
            "(meta.title CONTAINS transformer) AND (meta.year BETWEEN [2020, 2025])",
            "(quick_scan.verdict CONTAINS 推荐) OR "
            "(analysis_report.related_references CONTAINS Lyapunov)",
            "(md_content CONTAINS AdamW) AND (meta.publication CONTAINS NeurIPS)",
        ],
        "projection_examples": [
            "meta",
            "meta.title",
            "meta.custom_meta.zotero_key",
            "custom_meta.zotero_key",
            "synthesis_data.methodology.innovation.text",
            "synthesis_data.review_summary.citations[0].quote",
        ],
        "matrix_tips": [
            "Paper IDs 和字段路径都支持每行一个，也支持逗号分隔。",
            "Matrix compare 最适合同一批字段跨多篇论文横向对比；字段路径规则与 projection 完全一致。",
            "复杂对象会在单元格里显示摘要，下方保留原始 JSON，便于继续排查嵌套结构。",
        ],
        "project_query_tips": [
            "CONTAINS 适用于文本字段，大小写不敏感；数组和对象会按 JSON 文本参与匹配。",
            "BETWEEN 目前只用于 year / meta.year，格式固定为 [start, end]。",
            "条件组支持 AND / OR 和括号嵌套，project 页面会自动把搜索范围限定到当前 project 内。",
        ],
        "global_finder_tips": [
            "Global Finder 聚合指定 project 下全部已关联论文的基础信息，用于快速建立整体感觉。",
            "年份统计仅基于 year 有值的论文计算；缺失年份会单独计入 missing_count。",
            f"热门标签默认返回前 {get_app_settings_repo().get().librarian.top_tags_limit} 个，可通过配置修改。",
        ],
    }
