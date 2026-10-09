from __future__ import annotations

from datetime import datetime
from http import HTTPStatus

import pytest

from my_app.core.models import MAX_TITLE_LENGTH


@pytest.fixture
def make_todo(client):
    """Create a to-do through the API and return its JSON body."""

    def _make(title: str = "buy milk") -> dict[str, object]:
        response = client.post("/todos", json={"title": title})
        assert response.status_code == HTTPStatus.CREATED
        body: dict[str, object] = response.json()
        return body

    return _make


def test_list_todos_empty_store_returns_empty_list(client):
    response = client.get("/todos")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


def test_create_todo_valid_title_returns_201_with_open_todo(client, fixed_now):
    response = client.post("/todos", json={"title": "  buy milk "})

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body == {
        "id": 1,
        "title": "buy milk",
        "completed": False,
        "created_at": body["created_at"],
    }
    assert datetime.fromisoformat(body["created_at"]) == fixed_now


@pytest.mark.parametrize(
    "title",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace-only"),
        pytest.param("x" * (MAX_TITLE_LENGTH + 1), id="too-long"),
    ],
)
def test_create_todo_invalid_title_returns_422_and_stores_nothing(client, title):
    response = client.post("/todos", json={"title": title})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert "characters" in response.json()["detail"]
    assert client.get("/todos").json() == []


def test_create_todo_missing_title_returns_422_with_fastapi_list_detail(client):
    response = client.post("/todos", json={})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert isinstance(response.json()["detail"], list)


def test_list_todos_after_creates_returns_them_oldest_first(client, make_todo):
    first = make_todo("first")
    second = make_todo("second")

    response = client.get("/todos")

    assert response.json() == [first, second]


def test_complete_todo_existing_id_returns_completed_todo(client, make_todo):
    todo = make_todo()

    response = client.post(f"/todos/{todo['id']}/complete")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {**todo, "completed": True}


@pytest.mark.parametrize(
    "todo_id",
    [pytest.param(999, id="never-assigned"), pytest.param(2**63, id="above-int64")],
)
def test_complete_todo_unknown_id_returns_404(client, todo_id):
    response = client.post(f"/todos/{todo_id}/complete")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"detail": f"To-do {todo_id} not found"}


def test_delete_todo_existing_id_returns_204_and_removes_it(client, make_todo):
    todo = make_todo()

    response = client.delete(f"/todos/{todo['id']}")

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert response.content == b""
    assert client.get("/todos").json() == []


def test_delete_todo_unknown_id_returns_404(client):
    response = client.delete("/todos/999")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"detail": "To-do 999 not found"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("POST", "/todos/abc/complete", id="complete"),
        pytest.param("DELETE", "/todos/abc", id="delete"),
    ],
)
def test_todo_route_non_integer_id_returns_422(client, method, path):
    response = client.request(method, path)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        pytest.param("post", "/todos", "422", id="create-invalid-title"),
        pytest.param(
            "post", "/todos/{todo_id}/complete", "404", id="complete-not-found"
        ),
        pytest.param("delete", "/todos/{todo_id}", "404", id="delete-not-found"),
    ],
)
def test_openapi_documents_domain_errors_with_error_response(
    client, method, path, status
):
    operation = client.get("/openapi.json").json()["paths"][path][method]

    schema = operation["responses"][status]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
