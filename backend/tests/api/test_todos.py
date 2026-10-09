from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from uuid import UUID

import pytest

from my_app.core.models import MAX_PAGE_LIMIT, MAX_TITLE_LENGTH

INVALID_CURSOR_MESSAGE = (
    "Invalid page cursor: pass the next_cursor of an earlier page, "
    "or no cursor for the first page"
)
NIL_ID = "00000000-0000-0000-0000-000000000000"
UNKNOWN_IDS = [
    pytest.param(NIL_ID, id="nil"),
    pytest.param(str(UUID(int=2**128 - 1)), id="max"),
    pytest.param("01900000-0000-7000-8000-0000000003e7", id="never-assigned"),
]


@pytest.fixture
def make_todo(client):
    """Create a to-do through the API and return its JSON body."""

    def _make(title: str = "buy milk") -> dict[str, object]:
        response = client.post("/api/todos", json={"title": title})
        assert response.status_code == HTTPStatus.CREATED
        body: dict[str, object] = response.json()
        return body

    return _make


def test_list_todos_empty_store_returns_empty_last_page(client):
    response = client.get("/api/todos")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"items": [], "next_cursor": None}


def test_create_todo_valid_title_returns_201_with_open_todo(client, nth_id, fixed_now):
    response = client.post("/api/todos", json={"title": "  buy milk "})

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body == {
        "id": str(nth_id(1)),
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
    response = client.post("/api/todos", json={"title": title})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert "characters" in response.json()["detail"]
    assert client.get("/api/todos").json()["items"] == []


def test_create_todo_missing_title_returns_422_with_fastapi_list_detail(client):
    response = client.post("/api/todos", json={})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert isinstance(response.json()["detail"], list)


def test_list_todos_after_creates_returns_them_oldest_first(client, make_todo):
    first = make_todo("first")
    second = make_todo("second")

    response = client.get("/api/todos")

    assert response.json() == {"items": [first, second], "next_cursor": None}


def test_list_todos_two_pages_returns_all_in_creation_order(client, make_todo):
    a, b, c = make_todo("a"), make_todo("b"), make_todo("c")

    first = client.get("/api/todos", params={"limit": 2})
    cursor = first.json()["next_cursor"]
    second = client.get("/api/todos", params={"limit": 2, "cursor": cursor})

    assert first.status_code == HTTPStatus.OK
    assert first.json()["items"] == [a, b]
    assert isinstance(cursor, str)
    assert len(cursor) == 22
    assert second.status_code == HTTPStatus.OK
    assert second.json() == {"items": [c], "next_cursor": None}


@pytest.mark.parametrize(
    "cursor",
    [
        pytest.param("not-a-cursor", id="not-a-cursor"),
        pytest.param("", id="empty"),
        pytest.param("A" * 21, id="21-characters"),
    ],
)
def test_list_todos_invalid_cursor_returns_422(client, make_todo, cursor):
    make_todo()

    response = client.get("/api/todos", params={"cursor": cursor})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert response.json() == {"detail": INVALID_CURSOR_MESSAGE}


@pytest.mark.parametrize("limit", [1, MAX_PAGE_LIMIT])
def test_list_todos_limit_at_a_bound_returns_200(client, make_todo, limit):
    make_todo()

    response = client.get("/api/todos", params={"limit": limit})

    assert response.status_code == HTTPStatus.OK
    assert len(response.json()["items"]) == 1


@pytest.mark.parametrize(
    "limit", [pytest.param(0, id="zero"), pytest.param(-1, id="negative")]
)
def test_list_todos_limit_below_one_returns_422(client, limit):
    response = client.get("/api/todos", params={"limit": limit})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert response.json() == {"detail": f"Page limit must be 1-100, got {limit}"}


def test_list_todos_limit_above_max_returns_422(client):
    response = client.get("/api/todos?limit=101")

    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert response.json() == {"detail": "Page limit must be 1-100, got 101"}


def test_list_todos_non_integer_limit_returns_422_with_fastapi_list_detail(client):
    response = client.get("/api/todos", params={"limit": "abc"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert isinstance(response.json()["detail"], list)


def test_complete_todo_existing_id_returns_completed_todo(client, make_todo):
    todo = make_todo()

    response = client.post(f"/api/todos/{todo['id']}/complete")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {**todo, "completed": True}


@pytest.mark.parametrize("todo_id", UNKNOWN_IDS)
def test_complete_todo_unknown_id_returns_404(client, todo_id):
    response = client.post(f"/api/todos/{todo_id}/complete")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"detail": f"To-do {todo_id} not found"}


def test_complete_todo_unhyphenated_uppercase_id_names_the_canonical_id(client):
    response = client.post(f"/api/todos/{'F' * 32}/complete")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"detail": f"To-do {UUID(int=2**128 - 1)} not found"}


def test_delete_todo_existing_id_returns_204_and_removes_it(client, make_todo):
    todo = make_todo()

    response = client.delete(f"/api/todos/{todo['id']}")

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert response.content == b""
    assert client.get("/api/todos").json()["items"] == []


@pytest.mark.parametrize("todo_id", UNKNOWN_IDS)
def test_delete_todo_unknown_id_returns_404(client, todo_id):
    response = client.delete(f"/api/todos/{todo_id}")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"detail": f"To-do {todo_id} not found"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("POST", "/api/todos/abc/complete", id="complete-abc"),
        pytest.param("DELETE", "/api/todos/abc", id="delete-abc"),
        pytest.param("POST", "/api/todos/999/complete", id="complete-integer"),
        pytest.param("DELETE", "/api/todos/999", id="delete-integer"),
    ],
)
def test_todo_route_non_uuid_id_returns_422(client, method, path):
    response = client.request(method, path)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        pytest.param("get", "/api/todos", "422", id="list-invalid-page"),
        pytest.param("post", "/api/todos", "422", id="create-invalid-title"),
        pytest.param(
            "post", "/api/todos/{todo_id}/complete", "404", id="complete-not-found"
        ),
        pytest.param("delete", "/api/todos/{todo_id}", "404", id="delete-not-found"),
    ],
)
def test_openapi_documents_domain_errors_with_error_response(
    client, method, path, status
):
    operation = client.get("/openapi.json").json()["paths"][path][method]

    schema = operation["responses"][status]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


def test_openapi_list_todos_documents_the_page_shape(client):
    document = client.get("/openapi.json").json()
    operation = document["paths"]["/api/todos"]["get"]

    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    page = document["components"]["schemas"]["TodoPageResponse"]
    assert schema == {"$ref": "#/components/schemas/TodoPageResponse"}
    assert set(page["properties"]) == {"items", "next_cursor"}
