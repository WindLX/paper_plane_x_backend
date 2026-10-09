import shutil
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from paper_plane_x_backend.services.project.files import MAX_FILE_SIZE


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (10, 120, 240)).save(buffer, format="PNG")
    return buffer.getvalue()


def _create_project(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Files API"})
    assert response.status_code == 201
    return response.json()["project_id"]


def test_file_mutations_are_recorded_once_and_reads_are_not(client: TestClient) -> None:
    project_id = _create_project(client)
    base = f"/api/v1/projects/{project_id}"
    client.put(
        f"{base}/files/content", json={"file_path": "/note.md", "content": "# Original"}
    )
    client.patch(
        f"{base}/files/text",
        json={"file_path": "/note.md", "old_text": "Original", "new_text": "Updated"},
    )
    client.post(
        f"{base}/files/upload",
        data={"file_path": "/figure.png"},
        files={"file": ("figure.png", _png_bytes(), "image/png")},
    )
    before = client.get(f"{base}/activities", params={"category": "file"}).json()
    assert before["total"] == 3
    assert sorted(item["event_type"] for item in before["items"]) == [
        "file_uploaded",
        "file_written",
        "file_written",
    ]
    client.get(f"{base}/files/content", params={"file_path": "/note.md"})
    client.get(f"{base}/files/preview", params={"file_path": "/figure.png"})
    assert (
        client.get(f"{base}/activities", params={"category": "file"}).json()["total"]
        == 3
    )
    client.delete(f"{base}/files/content", params={"file_path": "/figure.png"})
    assert (
        client.get(f"{base}/activities", params={"category": "file"}).json()["total"]
        == 4
    )


@pytest.mark.parametrize(
    "markup",
    [
        '<link rel="stylesheet" href="https://example.invalid/style.css">',
        "<style>body {background: url(https://example.invalid/image.png)}</style>",
        '<iframe src="https://example.invalid/">',
    ],
)
def test_export_rejects_external_html_resources_before_conversion(
    client: TestClient, markup: str
) -> None:
    project_id = _create_project(client)
    base = f"/api/v1/projects/{project_id}"
    client.put(
        f"{base}/files/content", json={"file_path": "/note.md", "content": markup}
    )
    response = client.post(
        f"{base}/files/export", json={"file_path": "/note.md", "format": "html"}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "export_invalid_resources"
    activities = client.get(f"{base}/activities", params={"category": "export"}).json()
    assert activities["total"] == 1
    assert activities["items"][0]["status"] == "failed"


def test_new_project_lists_empty_sandbox(client: TestClient) -> None:
    project_id = _create_project(client)

    response = client.get(f"/api/v1/projects/{project_id}/files")

    assert response.status_code == 200
    assert response.json() == {"items": []}

    project_id = _create_project(client)
    write_response = client.put(
        f"/api/v1/projects/{project_id}/files/content",
        json={"file_path": "/draft.md", "content": "head\nbody\ntail\n"},
    )
    assert write_response.status_code == 200

    find_response = client.get(
        f"/api/v1/projects/{project_id}/files/find",
        params={"file_path": "/draft.md", "query": "body"},
    )
    assert find_response.status_code == 200
    assert find_response.json()["matches"][0]["line_no"] == 2

    patch_response = client.patch(
        f"/api/v1/projects/{project_id}/files/patch",
        json={
            "file_path": "/draft.md",
            "action": "insert_after",
            "anchor_text": "body\n",
            "content": "extra\n",
        },
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["occurrences"] == 1

    read_response = client.get(
        f"/api/v1/projects/{project_id}/files/content",
        params={"file_path": "/draft.md"},
    )
    assert read_response.status_code == 200
    assert read_response.json()["content"] == "head\nbody\nextra\ntail\n"


def test_project_file_replace_lines(client: TestClient) -> None:
    project_id = _create_project(client)
    client.put(
        f"/api/v1/projects/{project_id}/files/content",
        json={"file_path": "/notes.md", "content": "a\nb\nc\n"},
    )

    response = client.patch(
        f"/api/v1/projects/{project_id}/files/lines",
        json={
            "file_path": "/notes.md",
            "start_line": 2,
            "end_line": 3,
            "new_text": "x\ny",
        },
    )

    assert response.status_code == 200
    assert response.json()["lines_replaced"] == 2


def test_project_file_upload(client: TestClient) -> None:
    project_id = _create_project(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/files/upload",
        data={"file_path": "/notes/uploaded.md"},
        files={"file": ("uploaded.md", b"# Uploaded\n", "text/markdown")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "file_path": "/notes/uploaded.md",
        "bytes_written": 11,
        "is_dir": False,
    }

    read_response = client.get(
        f"/api/v1/projects/{project_id}/files/content",
        params={"file_path": "/notes/uploaded.md"},
    )
    assert read_response.status_code == 200
    assert read_response.json()["content"] == "# Uploaded\n"


def test_project_file_invalid_path_returns_400(client: TestClient) -> None:
    project_id = _create_project(client)

    response = client.put(
        f"/api/v1/projects/{project_id}/files/content",
        json={"file_path": "/../escape.md", "content": "x"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "path_traversal"


def test_project_file_oversized_upload_returns_413(client: TestClient) -> None:
    project_id = _create_project(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/files/upload",
        data={"file_path": "/notes/huge.md"},
        files={"file": ("huge.md", b"x" * (MAX_FILE_SIZE + 1), "text/markdown")},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"


def test_project_file_download_returns_raw_bytes(client: TestClient) -> None:
    project_id = _create_project(client)
    payload = b"line1\r\n\xff\xfe binary \x00\r\n"
    upload_response = client.post(
        f"/api/v1/projects/{project_id}/files/upload",
        data={"file_path": "/notes/raw.txt"},
        files={"file": ("raw.txt", payload, "text/plain")},
    )
    assert upload_response.status_code == 200

    response = client.get(
        f"/api/v1/projects/{project_id}/files/download",
        params={"file_path": "/notes/raw.txt"},
    )

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="raw.txt"'


def test_project_file_download_non_ascii_filename_uses_rfc5987(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    payload = "# 报告\n".encode()
    upload_response = client.post(
        f"/api/v1/projects/{project_id}/files/upload",
        data={"file_path": "/中文/报告.md"},
        files={"file": ("报告.md", payload, "text/markdown")},
    )
    assert upload_response.status_code == 200

    response = client.get(
        f"/api/v1/projects/{project_id}/files/download",
        params={"file_path": "/中文/报告.md"},
    )

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-disposition"] == (
        "attachment; filename*=UTF-8''%E6%8A%A5%E5%91%8A.md"
    )


def test_project_file_download_missing_returns_404(client: TestClient) -> None:
    project_id = _create_project(client)

    response = client.get(
        f"/api/v1/projects/{project_id}/files/download",
        params={"file_path": "/missing.md"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_project_file_download_traversal_returns_400(client: TestClient) -> None:
    project_id = _create_project(client)

    response = client.get(
        f"/api/v1/projects/{project_id}/files/download",
        params={"file_path": "/../escape.md"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "path_traversal"


def test_project_file_download_empty_directory_returns_400(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    directory_response = client.put(
        f"/api/v1/projects/{project_id}/files/content",
        json={"file_path": "/empty-dir", "is_dir": True},
    )
    assert directory_response.status_code == 200

    response = client.get(
        f"/api/v1/projects/{project_id}/files/download",
        params={"file_path": "/empty-dir"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "path_is_directory"


def test_project_file_image_upload_list_preview_and_download(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    payload = _png_bytes()

    upload_response = client.post(
        f"/api/v1/projects/{project_id}/files/upload",
        data={"file_path": "/images/图 一.png"},
        files={"file": ("图 一.png", payload, "image/png")},
    )
    assert upload_response.status_code == 200
    assert upload_response.json() == {
        "file_path": "/images/图 一.png",
        "bytes_written": len(payload),
        "is_dir": False,
    }

    list_response = client.get(
        f"/api/v1/projects/{project_id}/files",
        params={"dir_path": "/images"},
    )
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "图 一.png"
    assert items[0]["kind"] == "image"
    assert items[0]["content_type"] == "image/png"
    assert items[0]["size"] == len(payload)
    assert items[0]["modified_at"] is not None

    preview_response = client.get(
        f"/api/v1/projects/{project_id}/files/preview",
        params={"file_path": "/images/图 一.png"},
    )
    assert preview_response.status_code == 200
    assert preview_response.content == payload
    assert preview_response.headers["content-type"] == "image/png"
    assert preview_response.headers["content-security-policy"] == "sandbox"
    assert preview_response.headers["x-content-type-options"] == "nosniff"
    assert preview_response.headers["content-disposition"].startswith("inline;")

    download_response = client.get(
        f"/api/v1/projects/{project_id}/files/download",
        params={"file_path": "/images/图 一.png"},
    )
    assert download_response.status_code == 200
    assert download_response.content == payload
    assert download_response.headers["content-type"] == "image/png"
    assert download_response.headers["content-disposition"].startswith("attachment;")

    content_response = client.get(
        f"/api/v1/projects/{project_id}/files/content",
        params={"file_path": "/images/图 一.png"},
    )
    assert content_response.status_code == 400
    assert content_response.json()["detail"]["code"] == "not_text_file"

    delete_response = client.delete(
        f"/api/v1/projects/{project_id}/files/content",
        params={"file_path": "/images/图 一.png"},
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"removed": "/images/图 一.png"}


def test_project_file_upload_rejects_invalid_image_content(client: TestClient) -> None:
    project_id = _create_project(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/files/upload",
        data={"file_path": "/fake.png"},
        files={"file": ("fake.png", b"not a png", "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_image_content"


def test_project_file_upload_rejects_unsafe_svg(client: TestClient) -> None:
    project_id = _create_project(client)
    payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

    response = client.post(
        f"/api/v1/projects/{project_id}/files/upload",
        data={"file_path": "/unsafe.svg"},
        files={"file": ("unsafe.svg", payload, "image/svg+xml")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "svg_forbidden_element"


def test_project_file_preview_rejects_text_file(client: TestClient) -> None:
    project_id = _create_project(client)
    client.put(
        f"/api/v1/projects/{project_id}/files/content",
        json={"file_path": "/note.md", "content": "# note\n"},
    )

    response = client.get(
        f"/api/v1/projects/{project_id}/files/preview",
        params={"file_path": "/note.md"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "not_an_image"


def test_project_file_export_markdown_returns_raw_bytes(client: TestClient) -> None:
    project_id = _create_project(client)
    markdown = "# 报告\r\n\r\n![图](missing.png)\r\n"
    client.put(
        f"/api/v1/projects/{project_id}/files/content",
        json={"file_path": "/notes/report.md", "content": markdown},
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/files/export",
        json={"file_path": "/notes/report.md", "format": "markdown"},
    )

    assert response.status_code == 200
    assert response.content == markdown.encode()
    assert response.headers["content-disposition"] == (
        'attachment; filename="report.md"'
    )


def test_project_file_export_preflight_lists_invalid_images(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    markdown = (
        "![missing](images/missing.png)\n\n"
        '<img src="https://example.com/remote.png" alt="remote">\n'
    )
    client.put(
        f"/api/v1/projects/{project_id}/files/content",
        json={"file_path": "/notes/report.md", "content": markdown},
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/files/export",
        json={"file_path": "/notes/report.md", "format": "html"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "export_invalid_resources"
    references = detail["details"]["references"]
    assert {entry["reason"] for entry in references} == {"missing", "external"}


@pytest.mark.skipif(
    shutil.which("pandoc") is None,
    reason="pandoc is not installed",
)
def test_project_file_export_html_embeds_referenced_image(client: TestClient) -> None:
    project_id = _create_project(client)
    payload = _png_bytes()
    upload_response = client.post(
        f"/api/v1/projects/{project_id}/files/upload",
        data={"file_path": "/images/figure.png"},
        files={"file": ("figure.png", payload, "image/png")},
    )
    assert upload_response.status_code == 200
    client.put(
        f"/api/v1/projects/{project_id}/files/content",
        json={
            "file_path": "/notes/report.md",
            "content": "![f](../images/figure.png)\n",
        },
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/files/export",
        json={"file_path": "/notes/report.md", "format": "html"},
    )

    assert response.status_code == 200
    assert b"data:image/png;base64," in response.content
    assert b"../images/figure.png" not in response.content
