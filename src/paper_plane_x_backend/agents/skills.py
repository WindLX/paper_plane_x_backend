"""Researcher/SubAgent skills registry."""

from __future__ import annotations

from dataclasses import dataclass

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.core.agent_runtime.tooling import Tool
from paper_plane_x_backend.tools.conversation_io import (
    find_in_project_file,
    list_project_files,
    patch_project_file,
    read_project_file,
    read_project_file_lines,
    remove_project_file,
    replace_project_file_lines,
    replace_project_file_text,
    write_project_file,
)
from paper_plane_x_backend.tools.hitl import ask_human
from paper_plane_x_backend.tools.librarian import (
    deep_dive_tool,
    global_finder,
    matrix_compare,
    search_paper,
)
from paper_plane_x_backend.tools.paper import (
    delete_paper_agent_note,
    get_paper_agent_note,
    update_paper_agent_note,
    write_paper_agent_note,
)
from paper_plane_x_backend.tools.subagent import delegate_to_subagent

SKILL_PROMPTS_PLACEHOLDER = "{{SKILL_PROMPTS}}"
DEFAULT_RESEARCHER_SKILLS = ("librarian", "paper")


@dataclass(frozen=True)
class AgentSkillDefinition:
    name: str
    tools: tuple[Tool, ...]
    prompt_filename: str
    enabled_by_default: bool = False
    available_for_subagent: bool = True


SKILL_REGISTRY: dict[str, AgentSkillDefinition] = {
    "conversation_io": AgentSkillDefinition(
        name="conversation_io",
        tools=(
            read_project_file,
            read_project_file_lines,
            find_in_project_file,
            write_project_file,
            replace_project_file_lines,
            replace_project_file_text,
            patch_project_file,
            list_project_files,
            remove_project_file,
        ),
        prompt_filename="conversation_io.md",
    ),
    "hitl": AgentSkillDefinition(
        name="hitl",
        tools=(ask_human,),
        prompt_filename="hitl.md",
        available_for_subagent=False,
    ),
    "librarian": AgentSkillDefinition(
        name="librarian",
        tools=(
            global_finder,
            matrix_compare,
            search_paper,
            deep_dive_tool,
        ),
        prompt_filename="librarian.md",
        enabled_by_default=True,
    ),
    "paper": AgentSkillDefinition(
        name="paper",
        tools=(
            get_paper_agent_note,
            write_paper_agent_note,
            update_paper_agent_note,
            delete_paper_agent_note,
        ),
        prompt_filename="paper.md",
        enabled_by_default=True,
    ),
    "subagent": AgentSkillDefinition(
        name="subagent",
        tools=(delegate_to_subagent,),
        prompt_filename="subagent.md",
        available_for_subagent=False,
    ),
}


def list_available_skill_names(*, for_subagent: bool = False) -> list[str]:
    return [
        name
        for name, definition in SKILL_REGISTRY.items()
        if not for_subagent or definition.available_for_subagent
    ]


def get_default_skill_names(*, for_subagent: bool = False) -> list[str]:
    return [
        name
        for name, definition in SKILL_REGISTRY.items()
        if definition.enabled_by_default
        and (not for_subagent or definition.available_for_subagent)
    ]


def resolve_skill_names(
    enabled_skills: list[str] | None,
    *,
    for_subagent: bool = False,
) -> list[str]:
    requested = enabled_skills or get_default_skill_names(for_subagent=for_subagent)
    available_names = set(list_available_skill_names(for_subagent=for_subagent))

    resolved: list[str] = []
    seen: set[str] = set()
    for skill_name in requested:
        if skill_name in seen:
            continue
        if skill_name not in SKILL_REGISTRY:
            raise ValueError(f"Unknown skill: {skill_name}")
        if skill_name not in available_names:
            raise ValueError(f"Skill '{skill_name}' is not available in this agent")
        resolved.append(skill_name)
        seen.add(skill_name)
    return resolved


def resolve_skill_tools(
    enabled_skills: list[str] | None,
    *,
    for_subagent: bool = False,
) -> list[Tool]:
    resolved_names = resolve_skill_names(enabled_skills, for_subagent=for_subagent)
    tools: list[Tool] = []
    seen: set[str] = set()
    for skill_name in resolved_names:
        for tool in SKILL_REGISTRY[skill_name].tools:
            if tool.name in seen:
                continue
            tools.append(tool)
            seen.add(tool.name)
    return tools


def render_skill_prompt(
    *,
    base_prompt: str,
    enabled_skills: list[str] | None,
    for_subagent: bool = False,
) -> str:
    resolved_names = resolve_skill_names(enabled_skills, for_subagent=for_subagent)
    sections: list[str] = []
    for skill_name in resolved_names:
        definition = SKILL_REGISTRY[skill_name]
        content = settings.load_prompt("skills", definition.prompt_filename).strip()
        if content:
            sections.append(content)

    rendered_sections = "\n\n".join(sections).strip()
    if SKILL_PROMPTS_PLACEHOLDER in base_prompt:
        return base_prompt.replace(SKILL_PROMPTS_PLACEHOLDER, rendered_sections)
    if not rendered_sections:
        return base_prompt
    return f"{base_prompt.rstrip()}\n\n{rendered_sections}"
