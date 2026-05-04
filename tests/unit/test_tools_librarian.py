"""Librarian hybrid retrieval tests."""

from typing import Any

import pytest

from paper_plane_x_backend.services.librarian import build_field_paths_guide
from paper_plane_x_backend.services.paper.repository import PaperRepositoryError
from paper_plane_x_backend.tools import librarian


def test_fetch_paper_by_path_function_removed() -> None:
    assert not hasattr(librarian, "fetch_paper_by_path")


def test_matrix_compare_by_paths_tool_success(monkeypatch) -> None:
    class _FakeRepo:
        def __init__(self, _db) -> None:
            pass

        @staticmethod
        def fetch_by_path(
            paper_id: str,
            field_path: str,
        ):
            if paper_id == "p-1" and field_path == "meta.title":
                return "T1"
            raise PaperRepositoryError("bad input")

    monkeypatch.setattr(librarian, "get_db", lambda: object())
    monkeypatch.setattr(librarian, "PaperQueryRepository", _FakeRepo)

    assert librarian.matrix_compare.function is not None
    payload = librarian.matrix_compare.function(
        paper_ids=["p-1"],
        field_paths=["meta.title"],
    )
    assert payload["items"]["p-1"]["meta.title"] == "T1"


def test_matrix_compare_by_paths_tool_returns_error_payload(monkeypatch) -> None:
    class _FakeRepo:
        def __init__(self, _db) -> None:
            pass

        @staticmethod
        def fetch_by_path(
            paper_id: str,
            field_path: str,
        ):
            _ = paper_id, field_path
            raise PaperRepositoryError("field_paths cannot be empty")

    monkeypatch.setattr(librarian, "get_db", lambda: object())
    monkeypatch.setattr(librarian, "PaperQueryRepository", _FakeRepo)

    assert librarian.matrix_compare.function is not None
    payload = librarian.matrix_compare.function(
        paper_ids=["p-1"],
        field_paths=[],
    )
    assert payload["paper_ids"] == ["p-1"]
    assert payload["field_paths"] == []
    assert payload["error"] == "field_paths cannot be empty"


def test_matrix_compare_by_paths_tool_strips_citations(monkeypatch) -> None:
    class _FakeRepo:
        def __init__(self, _db) -> None:
            pass

        @staticmethod
        def fetch_by_path(
            paper_id: str,
            field_path: str,
        ):
            _ = paper_id, field_path
            return {
                "text": "核心创新",
                "citations": [{"quote": "Q1", "anchor": "#1"}],
            }

    monkeypatch.setattr(librarian, "get_db", lambda: object())
    monkeypatch.setattr(librarian, "PaperQueryRepository", _FakeRepo)

    assert librarian.matrix_compare.function is not None
    payload = librarian.matrix_compare.function(
        paper_ids=["p-1"],
        field_paths=["synthesis_data.methodology.innovation"],
    )
    value = payload["items"]["p-1"]["synthesis_data.methodology.innovation"]
    assert value["text"] == "核心创新"
    assert "citations" not in value


def test_build_field_paths_guide_contains_meta_and_structured_paths() -> None:
    guide = build_field_paths_guide()

    assert "meta：" in guide
    assert "meta.raw_pdf_path" in guide
    assert "quick_scan.verdict" in guide
    assert "synthesis_data.methodology.innovation.text" in guide
    assert "analysis_report.core_formulation.objective_function.text" in guide
    assert "analysis_report.related_references[0].title" in guide


def test_matrix_compare_description_contains_field_paths_guide() -> None:
    desc = librarian.matrix_compare.description
    shared_guide = librarian.matrix_compare.shared_guides
    assert "跨多篇论文按 field_paths 读取结构化字段" in desc
    assert "custom_meta.<key>" in shared_guide["Librarian Field Paths"]


@pytest.mark.asyncio
async def test_deep_dive_tool_strips_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_deep_dive(*, repo, paper_id: str, question: str, **kwargs: Any):
        _ = repo, paper_id, question, kwargs
        return {
            "result": {
                "is_answered": True,
                "answer": {
                    "text": "核心回答",
                    "citations": [{"quote": "Q1", "source_header": "§1"}],
                },
            },
            "trace_id": "trace-1",
        }

    monkeypatch.setattr(librarian, "get_db", lambda: object())
    monkeypatch.setattr(librarian, "PaperRepository", lambda _db: object())
    monkeypatch.setattr(librarian, "deep_dive", fake_deep_dive)

    assert librarian.deep_dive_tool.function is not None
    payload = await librarian.deep_dive_tool.function(
        paper_id="pap-test-1",
        question="What is new?",
    )
    assert payload["paper_id"] == "pap-test-1"
    assert payload["answer"]["is_answered"] is True
    assert payload["answer"]["answer"]["text"] == "核心回答"
    assert "citations" not in payload["answer"]["answer"]


@pytest.mark.asyncio
async def test_deep_dive_tool_passes_caller_and_caller_id_via_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 deep_dive_tool 通过 context_params 接收并传递 caller/caller_id."""
    captured_kwargs: dict[str, Any] = {}

    async def fake_deep_dive(*, repo, paper_id: str, question: str, **kwargs: Any):
        captured_kwargs.update(kwargs)
        return {
            "result": {
                "is_answered": True,
                "answer": {
                    "text": "captured",
                    "citations": [],
                },
            },
            "trace_id": "trace-ctx",
        }

    monkeypatch.setattr(librarian, "get_db", lambda: object())
    monkeypatch.setattr(librarian, "PaperRepository", lambda _db: object())
    monkeypatch.setattr(librarian, "deep_dive", fake_deep_dive)

    assert librarian.deep_dive_tool.function is not None
    # 通过 tool.execute 模拟 Agent 传递的 context
    result = await librarian.deep_dive_tool.execute(
        paper_id="paper-ctx",
        question="q",
        context={
            "_caller_agent_name": "ParentAgent",
            "_caller_trace_id": "parent-trace-123",
        },
    )
    assert result["paper_id"] == "paper-ctx"
    assert captured_kwargs.get("caller") == "ParentAgent"
    assert captured_kwargs.get("caller_id") == "parent-trace-123"


@pytest.mark.asyncio
async def test_deep_dive_tool_without_caller_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证直接调用 function 时 caller/caller_id 为 None，工具仍可正常执行."""
    captured_kwargs: dict[str, Any] = {}

    async def fake_deep_dive(*, repo, paper_id: str, question: str, **kwargs: Any):
        captured_kwargs.update(kwargs)
        return {
            "result": {
                "is_answered": True,
                "answer": {
                    "text": "no caller",
                    "citations": [],
                },
            },
            "trace_id": "trace-none",
        }

    monkeypatch.setattr(librarian, "get_db", lambda: object())
    monkeypatch.setattr(librarian, "PaperRepository", lambda _db: object())
    monkeypatch.setattr(librarian, "deep_dive", fake_deep_dive)

    assert librarian.deep_dive_tool.function is not None
    # 直接调用 function 不通过 execute，不经过 context_params 注入
    result = await librarian.deep_dive_tool.function(
        paper_id="paper-2",
        question="q2",
    )
    # function 层面 caller/caller_id 为 None
    assert result["paper_id"] == "paper-2"
    assert captured_kwargs.get("caller") is None
    assert captured_kwargs.get("caller_id") is None
