"""Paper Plane X HTTP CLI for external agent tools."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

import click
import httpx
import typer

DEFAULT_BASE_URL = "http://127.0.0.1:8000/api/v1"
CONTEXT_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONTEXT_PATH = CONTEXT_DIR / "paper-plane-x" / "context.json"
QueryParamValue = str | int | bool


class CLIError(Exception):
    def __init__(self, message: str, *, status_code: int = 2) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _load_context(path: Path | None = None) -> dict[str, str]:
    path = path or CONTEXT_PATH
    if not path.exists():
        return {}
    try:
        data_obj: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CLIError(f"Invalid context file JSON: {path}: {exc}") from exc
    if not isinstance(data_obj, dict):
        raise CLIError(f"Invalid context file shape: {path}")
    data = cast(dict[str, object], data_obj)
    return {key: str(value) for key, value in data.items() if value is not None}


def _save_context(data: dict[str, str], path: Path | None = None) -> None:
    path = path or CONTEXT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def resolve_context(
    base_url: str | None = None,
    project_id: str | None = None,
) -> dict[str, str | None]:
    stored = _load_context()
    resolved_base_url = (
        base_url
        or os.environ.get("PPX_BASE_URL")
        or stored.get("base_url")
        or DEFAULT_BASE_URL
    )
    resolved_project_id = (
        project_id or os.environ.get("PPX_PROJECT_ID") or stored.get("project_id")
    )
    return {
        "base_url": resolved_base_url.rstrip("/"),
        "project_id": resolved_project_id,
    }


def _print_json(payload: object, *, stream: Any | None = None) -> None:
    stream = stream or sys.stdout
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _require_project_id(ctx: dict[str, str | None]) -> str:
    project_id = ctx.get("project_id")
    if not project_id:
        raise CLIError("project_id is required. Run: ppx context set --project-id <id>")
    return project_id


def _request(
    method: str,
    path: str,
    *,
    ctx: dict[str, str | None],
    json_body: object | None = None,
    params: dict[str, QueryParamValue | None] | None = None,
) -> object:
    base_url = ctx["base_url"]
    url = f"{base_url}{path}"
    cleaned_params = (
        {key: value for key, value in params.items() if value is not None}
        if params
        else None
    )
    try:
        response = httpx.request(
            method,
            url,
            json=json_body,
            params=cleaned_params,
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise CLIError(f"HTTP request failed: {exc}", status_code=1) from exc

    if response.status_code >= 400:
        try:
            detail = response.json()
        except json.JSONDecodeError:
            detail = response.text
        raise CLIError(
            json.dumps(
                {"status_code": response.status_code, "error": detail},
                ensure_ascii=False,
            ),
            status_code=1,
        )

    if not response.content:
        return {}
    return response.json()


app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def callback(
    ctx: typer.Context,
    base_url: str | None = typer.Option(None, "--base-url"),
    project_id: str | None = typer.Option(None, "--project-id"),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["ctx"] = resolve_context(base_url=base_url, project_id=project_id)


context_app = typer.Typer()
app.add_typer(context_app, name="context")


@context_app.command("show")
def context_show(ctx: typer.Context) -> None:
    _print_json(ctx.obj["ctx"])


@context_app.command("set")
def context_set(
    set_base_url: str | None = typer.Option(None, "--base-url"),
    set_project_id: str | None = typer.Option(None, "--project-id"),
) -> None:
    data = _load_context()
    if set_base_url is not None:
        data["base_url"] = set_base_url.rstrip("/")
    if set_project_id is not None:
        data["project_id"] = set_project_id
    _save_context(data)
    _print_json(data)


project_app = typer.Typer()
app.add_typer(project_app, name="project")


@project_app.command("global-finder")
def project_global_finder(ctx: typer.Context) -> None:
    ctx_dict = ctx.obj["ctx"]
    project_id = _require_project_id(ctx_dict)
    payload = _request(
        "POST",
        "/librarian/global-finder",
        ctx=ctx_dict,
        json_body={"project_id": project_id},
    )
    _print_json(payload)


librarian_app = typer.Typer()
app.add_typer(librarian_app, name="librarian")


@librarian_app.command("search")
def librarian_search(
    ctx: typer.Context,
    query_expr: str = typer.Option(..., "--query-expr"),
    limit: int = typer.Option(20, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    payload = _request(
        "POST",
        "/librarian/search",
        ctx=ctx_dict,
        json_body={
            "project_id": ctx_dict.get("project_id"),
            "query_expr": query_expr,
            "limit": limit,
            "offset": offset,
        },
    )
    _print_json(payload)


@librarian_app.command("matrix")
def librarian_matrix(
    ctx: typer.Context,
    paper_ids: str = typer.Option(..., "--paper-ids"),
    field_paths: str = typer.Option(..., "--field-paths"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    payload = _request(
        "POST",
        "/librarian/matrix",
        ctx=ctx_dict,
        json_body={
            "paper_ids": _split_csv(paper_ids),
            "field_paths": _split_csv(field_paths),
        },
    )
    _print_json(payload)


@librarian_app.command("deep-dive")
def librarian_deep_dive(
    ctx: typer.Context,
    paper_id: str = typer.Option(..., "--paper-id"),
    question: str = typer.Option("", "--question"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    payload = _request(
        "POST",
        "/librarian/deep-dive",
        ctx=ctx_dict,
        json_body={"paper_id": paper_id, "question": question},
    )
    _print_json(payload)


files_app = typer.Typer()
app.add_typer(files_app, name="files")


@files_app.command("list")
def files_list(
    ctx: typer.Context,
    dir: str = typer.Option("/", "--dir"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    project_id = _require_project_id(ctx_dict)
    prefix = f"/projects/{project_id}/files"
    payload = _request("GET", prefix, ctx=ctx_dict, params={"dir_path": dir})
    _print_json(payload)


@files_app.command("read")
def files_read(
    ctx: typer.Context,
    path: str = typer.Option(..., "--path"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    project_id = _require_project_id(ctx_dict)
    prefix = f"/projects/{project_id}/files"
    payload = _request(
        "GET", f"{prefix}/content", ctx=ctx_dict, params={"file_path": path}
    )
    _print_json(payload)


@files_app.command("lines")
def files_lines(
    ctx: typer.Context,
    path: str = typer.Option(..., "--path"),
    start_line: int = typer.Option(..., "--start-line"),
    end_line: int | None = typer.Option(None, "--end-line"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    project_id = _require_project_id(ctx_dict)
    prefix = f"/projects/{project_id}/files"
    payload = _request(
        "GET",
        f"{prefix}/lines",
        ctx=ctx_dict,
        params={
            "file_path": path,
            "start_line": start_line,
            "end_line": end_line,
        },
    )
    _print_json(payload)


@files_app.command("find")
def files_find(
    ctx: typer.Context,
    path: str = typer.Option(..., "--path"),
    query: str = typer.Option(..., "--query"),
    case_sensitive: bool = typer.Option(False, "--case-sensitive"),
    max_matches: int = typer.Option(20, "--max-matches"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    project_id = _require_project_id(ctx_dict)
    prefix = f"/projects/{project_id}/files"
    payload = _request(
        "GET",
        f"{prefix}/find",
        ctx=ctx_dict,
        params={
            "file_path": path,
            "query": query,
            "case_sensitive": case_sensitive,
            "max_matches": max_matches,
        },
    )
    _print_json(payload)


@files_app.command("write")
def files_write(
    ctx: typer.Context,
    path: str = typer.Option(..., "--path"),
    content: str = typer.Option(..., "--content"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    project_id = _require_project_id(ctx_dict)
    prefix = f"/projects/{project_id}/files"
    payload = _request(
        "PUT",
        f"{prefix}/content",
        ctx=ctx_dict,
        json_body={"file_path": path, "content": content},
    )
    _print_json(payload)


@files_app.command("replace-lines")
def files_replace_lines(
    ctx: typer.Context,
    path: str = typer.Option(..., "--path"),
    start_line: int = typer.Option(..., "--start-line"),
    end_line: int = typer.Option(..., "--end-line"),
    new_text: str = typer.Option(..., "--new-text"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    project_id = _require_project_id(ctx_dict)
    prefix = f"/projects/{project_id}/files"
    payload = _request(
        "PATCH",
        f"{prefix}/lines",
        ctx=ctx_dict,
        json_body={
            "file_path": path,
            "start_line": start_line,
            "end_line": end_line,
            "new_text": new_text,
        },
    )
    _print_json(payload)


@files_app.command("replace-text")
def files_replace_text(
    ctx: typer.Context,
    path: str = typer.Option(..., "--path"),
    old_text: str = typer.Option(..., "--old-text"),
    new_text: str = typer.Option(..., "--new-text"),
    replace_all: bool = typer.Option(False, "--replace-all"),
    expected_occurrences: int = typer.Option(1, "--expected-occurrences"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    project_id = _require_project_id(ctx_dict)
    prefix = f"/projects/{project_id}/files"
    payload = _request(
        "PATCH",
        f"{prefix}/text",
        ctx=ctx_dict,
        json_body={
            "file_path": path,
            "old_text": old_text,
            "new_text": new_text,
            "replace_all": replace_all,
            "expected_occurrences": expected_occurrences,
        },
    )
    _print_json(payload)


@files_app.command("patch")
def files_patch(
    ctx: typer.Context,
    path: str = typer.Option(..., "--path"),
    action: str = typer.Option(..., "--action"),
    anchor_text: str = typer.Option(..., "--anchor-text"),
    content: str = typer.Option("", "--content"),
    expected_occurrences: int = typer.Option(1, "--expected-occurrences"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    project_id = _require_project_id(ctx_dict)
    prefix = f"/projects/{project_id}/files"
    payload = _request(
        "PATCH",
        f"{prefix}/patch",
        ctx=ctx_dict,
        json_body={
            "file_path": path,
            "action": action,
            "anchor_text": anchor_text,
            "content": content,
            "expected_occurrences": expected_occurrences,
        },
    )
    _print_json(payload)


@files_app.command("delete")
def files_delete(
    ctx: typer.Context,
    path: str = typer.Option(..., "--path"),
) -> None:
    ctx_dict = ctx.obj["ctx"]
    project_id = _require_project_id(ctx_dict)
    prefix = f"/projects/{project_id}/files"
    payload = _request(
        "DELETE", f"{prefix}/content", ctx=ctx_dict, params={"file_path": path}
    )
    _print_json(payload)


paper_note_app = typer.Typer()
app.add_typer(paper_note_app, name="paper-note")


@paper_note_app.command("get")
def paper_note_get(
    ctx: typer.Context,
    paper_id: str = typer.Option(..., "--paper-id"),
) -> None:
    path = f"/papers/{paper_id}/agent-note"
    payload = _request("GET", path, ctx=ctx.obj["ctx"])
    _print_json(payload)


@paper_note_app.command("write")
def paper_note_write(
    ctx: typer.Context,
    paper_id: str = typer.Option(..., "--paper-id"),
    content: str = typer.Option(..., "--content"),
) -> None:
    path = f"/papers/{paper_id}/agent-note"
    payload = _request("PUT", path, ctx=ctx.obj["ctx"], json_body={"content": content})
    _print_json(payload)


@paper_note_app.command("delete")
def paper_note_delete(
    ctx: typer.Context,
    paper_id: str = typer.Option(..., "--paper-id"),
) -> None:
    path = f"/papers/{paper_id}/agent-note"
    payload = _request("DELETE", path, ctx=ctx.obj["ctx"])
    _print_json(payload)


def run(argv: list[str] | None = None) -> int:
    try:
        app(args=argv or [], prog_name="ppx", standalone_mode=False)
    except click.ClickException as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return exc.exit_code
    except CLIError as exc:
        _print_json({"error": exc.message}, stream=sys.stderr)
        return exc.status_code
    return 0


def main() -> None:
    raise SystemExit(run())
