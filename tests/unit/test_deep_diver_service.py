from types import SimpleNamespace
from typing import Any

import pytest

import paper_plane_x_backend.services.librarian.deep_diver as deep_diver


@pytest.mark.asyncio
async def test_deep_dive_skips_image_loading_for_non_vlm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = SimpleNamespace(
        md_content="# Paper\n\nFull text",
        images_paths=["/unused/image.png"],
    )
    repo = SimpleNamespace(get=lambda paper_id: paper)
    captured: dict[str, Any] = {}

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            self.llm_config = SimpleNamespace(is_vlm=False)
            self.trace_ids = ["trace-1"]

        def append_user_message(self, payload: Any) -> None:
            captured["payload"] = payload

        async def run(self) -> Any:
            return SimpleNamespace(
                model_dump=lambda: {
                    "is_answered": False,
                    "answer": {"text": "not found", "citations": []},
                }
            )

    def fail_if_images_are_loaded(paths: Any) -> list[str]:
        raise AssertionError("non-VLM deep-dive must not load images")

    monkeypatch.setattr(deep_diver, "DeepDiverAgent", FakeAgent)
    monkeypatch.setattr(
        deep_diver.PaperParser,
        "load_images_base64",
        fail_if_images_are_loaded,
    )

    result = await deep_diver.deep_dive(
        repo=repo,
        paper_id="paper-1",
        question="question",
    )

    assert captured["payload"].images == []
    assert result["trace_id"] == "trace-1"
