import asyncio
import logging
from pathlib import Path
from time import perf_counter
from typing import Any

from paper_plane_x_backend.agents import DeepDiverAgent
from paper_plane_x_backend.schemas.agent_io.librarian import DeepDiverAgentInput
from paper_plane_x_backend.services.paper import PaperParser
from paper_plane_x_backend.services.paper.repository import (
    PaperRepository,
    PaperRepositoryError,
)

logger = logging.getLogger(__name__)


async def deep_dive(
    *,
    repo: PaperRepository,
    paper_id: str,
    question: str,
    caller: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    started_at = perf_counter()
    logger.info(
        "event=librarian.deep_dive.start paper_id=%s question_len=%s caller=%s caller_id=%s",
        paper_id,
        len(question),
        caller,
        caller_id,
    )
    paper = repo.get(paper_id=paper_id)
    if not paper:
        raise PaperRepositoryError(f"Paper with id {paper_id} not found")
    if not paper.md_content:
        raise PaperRepositoryError(
            f"Paper with id {paper_id} has no md_content for deep diving"
        )

    agent = DeepDiverAgent(caller=caller, caller_id=caller_id)
    if agent.llm_config.is_vlm and paper.images_paths:
        image_paths = [Path(p) for p in paper.images_paths]
        images = await asyncio.to_thread(PaperParser.load_images_base64, image_paths)
    else:
        images = []

    logger.info(
        "event=librarian.deep_dive.input_ready paper_id=%s md_chars=%s image_count=%s is_vlm=%s elapsed_ms=%.1f",
        paper_id,
        len(paper.md_content),
        len(images),
        agent.llm_config.is_vlm,
        (perf_counter() - started_at) * 1000,
    )
    agent.append_user_message(
        DeepDiverAgentInput(
            md_content=paper.md_content,
            images=images,
            question=question,
        )
    )
    try:
        result = await agent.run()
    except asyncio.CancelledError:
        logger.warning(
            "event=librarian.deep_dive.canceled paper_id=%s caller=%s caller_id=%s elapsed_ms=%.1f",
            paper_id,
            caller,
            caller_id,
            (perf_counter() - started_at) * 1000,
        )
        raise
    except Exception:
        logger.exception(
            "event=librarian.deep_dive.failed paper_id=%s caller=%s caller_id=%s elapsed_ms=%.1f",
            paper_id,
            caller,
            caller_id,
            (perf_counter() - started_at) * 1000,
        )
        raise

    trace_id = agent.trace_ids[-1] if agent.trace_ids else None
    logger.info(
        "event=librarian.deep_dive.completed paper_id=%s trace_id=%s caller=%s caller_id=%s elapsed_ms=%.1f",
        paper_id,
        trace_id,
        caller,
        caller_id,
        (perf_counter() - started_at) * 1000,
    )
    return {
        "result": result.model_dump(),
        "trace_id": trace_id,
    }
