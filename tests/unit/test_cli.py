import json
from pathlib import Path
from typing import Any

import httpx

from paper_plane_x_backend import cli


def test_context_precedence_args_env_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    context_path = tmp_path / "context.json"
    context_path.write_text(
        json.dumps(
            {
                "base_url": "http://file/api/v1",
                "project_id": "file-project",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "CONTEXT_PATH", context_path)
    monkeypatch.setenv("PPX_BASE_URL", "http://env/api/v1")
    monkeypatch.setenv("PPX_PROJECT_ID", "env-project")

    assert cli.resolve_context(
        base_url="http://arg/api/v1",
        project_id="arg-project",
    ) == {
        "base_url": "http://arg/api/v1",
        "project_id": "arg-project",
    }


def test_librarian_search_builds_http_request(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    context_path = tmp_path / "context.json"
    context_path.write_text(
        json.dumps(
            {
                "base_url": "http://server/api/v1",
                "project_id": "proj-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "CONTEXT_PATH", context_path)
    captured: dict[str, Any] = {}

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        captured.update({"method": method, "url": url, **kwargs})
        request = httpx.Request(method, url)
        return httpx.Response(
            200,
            json={"paper_ids": ["p1"], "total": 1},
            request=request,
        )

    monkeypatch.setattr(cli.httpx, "request", fake_request)

    status = cli.run(
        [
            "librarian",
            "search",
            "--query-expr",
            "(meta.title CONTAINS test)",
            "--limit",
            "5",
        ]
    )

    assert status == 0
    assert captured["method"] == "POST"
    assert captured["url"] == "http://server/api/v1/librarian/search"
    assert captured["json"]["project_id"] == "proj-1"
    assert captured["json"]["limit"] == 5
    assert json.loads(capsys.readouterr().out)["paper_ids"] == ["p1"]


def test_cli_reports_http_error(
    monkeypatch,
    capsys,
) -> None:
    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        request = httpx.Request(method, url)
        return httpx.Response(
            422,
            json={"detail": {"code": "invalid_field"}},
            request=request,
        )

    monkeypatch.setattr(cli.httpx, "request", fake_request)

    status = cli.run(
        [
            "--project-id",
            "proj-1",
            "librarian",
            "search",
            "--query-expr",
            "(bad CONTAINS x)",
        ]
    )

    assert status == 1
    payload = json.loads(capsys.readouterr().err)
    assert "invalid_field" in payload["error"]
