from fastapi.testclient import TestClient

from paper_plane_x_backend.services.project.files import MAX_FILE_SIZE


def _create_project(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Files API"})
    assert response.status_code == 201
    return response.json()["project_id"]


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
