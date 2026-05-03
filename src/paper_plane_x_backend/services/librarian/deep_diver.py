from pathlib import Path
from typing import Any

from paper_plane_x_backend.agents import DeepDiverAgent
from paper_plane_x_backend.schemas.agent_io.librarian import DeepDiverAgentInput
from paper_plane_x_backend.services.paper import PaperParser
from paper_plane_x_backend.services.paper.repository import (
    PaperRepository,
    PaperRepositoryError,
)


async def deep_dive(
    *,
    repo: PaperRepository,
    paper_id: str,
    question: str,
    caller: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    paper = repo.get(paper_id=paper_id)
    if not paper:
        raise PaperRepositoryError(f"Paper with id {paper_id} not found")
    if not paper.md_content:
        raise PaperRepositoryError(
            f"Paper with id {paper_id} has no md_content for deep diving"
        )
    if paper.images_paths:
        image_paths = [Path(p) for p in paper.images_paths]
        images = PaperParser.load_images_base64(image_paths)
    else:
        images = []

    agent = DeepDiverAgent(caller=caller, caller_id=caller_id)
    agent.append_user_message(
        DeepDiverAgentInput(
            md_content=paper.md_content,
            images=images,
            question=question,
        )
    )
    result = await agent.run()
    trace_id = agent.trace_ids[-1] if agent.trace_ids else None
    return {
        "result": result.model_dump(),
        "trace_id": trace_id,
    }
