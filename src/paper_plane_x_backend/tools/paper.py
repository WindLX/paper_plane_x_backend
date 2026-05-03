"""Paper 作用域 Agent 工具集合."""

from typing import Any

from paper_plane_x_backend.core.agent_runtime.tooling import tool
from paper_plane_x_backend.services.database import get_db
from paper_plane_x_backend.services.paper.repository import (
    PaperRepository,
    PaperRepositoryError,
)


def _build_paper_repo() -> PaperRepository:
    return PaperRepository(get_db())


@tool(
    name="get_paper_agent_note",
    description=(
        "查看指定 paper 的 agent_note（论文级 AI 笔记）。"
        "\n输入：paper_id。"
        "\n输出：成功时返回 {paper_id, agent_note}；失败时返回 {paper_id, error}。"
    ),
)
def get_paper_agent_note(
    paper_id: str,
) -> dict[str, Any]:
    repo = _build_paper_repo()
    try:
        note = repo.get_agent_note(paper_id)
    except PaperRepositoryError as exc:
        return {
            "paper_id": paper_id,
            "error": exc.message,
        }
    return {
        "paper_id": paper_id,
        "agent_note": note,
    }


@tool(
    name="write_paper_agent_note",
    description=(
        "写入指定 paper 的 agent_note（论文级 AI 笔记）。如果已存在则会覆盖。"
        "\n输入：paper_id, content（笔记内容）。"
        "\n输出：成功时返回 {paper_id, agent_note}；失败时返回 {paper_id, error}。"
    ),
)
def write_paper_agent_note(
    paper_id: str,
    content: str,
) -> dict[str, Any]:
    repo = _build_paper_repo()
    try:
        repo.set_agent_note(paper_id, content)
        note = repo.get_agent_note(paper_id)
    except PaperRepositoryError as exc:
        return {
            "paper_id": paper_id,
            "error": exc.message,
        }
    return {
        "paper_id": paper_id,
        "agent_note": note,
    }


@tool(
    name="update_paper_agent_note",
    description=(
        "修改指定 paper 的 agent_note（论文级 AI 笔记）。与 write 语义相同。"
        "\n输入：paper_id, content（更新后的笔记内容）。"
        "\n输出：成功时返回 {paper_id, agent_note}；失败时返回 {paper_id, error}。"
    ),
)
def update_paper_agent_note(
    paper_id: str,
    content: str,
) -> dict[str, Any]:
    repo = _build_paper_repo()
    try:
        repo.set_agent_note(paper_id, content)
        note = repo.get_agent_note(paper_id)
    except PaperRepositoryError as exc:
        return {
            "paper_id": paper_id,
            "error": exc.message,
        }
    return {
        "paper_id": paper_id,
        "agent_note": note,
    }


@tool(
    name="delete_paper_agent_note",
    description=(
        "删除指定 paper 的 agent_note（论文级 AI 笔记），将其置为 null。"
        "\n输入：paper_id。"
        "\n输出：成功时返回 {paper_id, agent_note}；失败时返回 {paper_id, error}。"
    ),
)
def delete_paper_agent_note(
    paper_id: str,
) -> dict[str, Any]:
    repo = _build_paper_repo()
    try:
        repo.delete_agent_note(paper_id)
        note = repo.get_agent_note(paper_id)
    except PaperRepositoryError as exc:
        return {
            "paper_id": paper_id,
            "error": exc.message,
        }
    return {
        "paper_id": paper_id,
        "agent_note": note,
    }
