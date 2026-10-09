from __future__ import annotations

from contextlib import AsyncExitStack
from http import HTTPStatus
from importlib import metadata, reload
from inspect import iscoroutinefunction
from uuid import UUID

import httpx2
import pytest
from fastapi import FastAPI
from fastapi import HTTPException as FastAPIHTTPException
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

import my_app
from my_app.api import app as app_module
from my_app.api.app import create_app
from my_app.composition import Container
from my_app.core.errors import (
    AppError,
    InvalidCursorError,
    InvalidPageLimitError,
    InvalidTodoError,
    TodoNotFoundError,
)
from my_app.settings import Settings

UNMAPPED_MESSAGE = "a rule with no status of its own"

pytestmark = pytest.mark.anyio


class _UnmappedError(AppError):
    """A domain error ``create_app`` has no specific status for."""

    def __init__(self) -> None:
        super().__init__(UNMAPPED_MESSAGE)


def test_healthz_returns_ok(client):
    response = client.get("/healthz")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}


def test_testclient_runs_on_httpx2_not_the_deprecated_httpx():
    assert issubclass(TestClient, httpx2.Client)


def test_openapi_uses_the_framework_default_version(make_container, monkeypatch):
    monkeypatch.setattr(metadata, "version", lambda _: "9.9.9")
    reload(my_app)
    reload(app_module)
    with TestClient(app_module.create_app(container=make_container())) as client:
        response = client.get("/openapi.json")

    assert response.json()["info"]["version"] == "0.1.0"


def test_unmapped_app_error_returns_400_problem(make_container):
    app = create_app(container=make_container())

    @app.get("/unmapped")
    def _raise_unmapped() -> None:
        raise _UnmappedError

    with TestClient(app) as client:
        response = client.get("/unmapped")

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Bad Request",
        "status": 400,
        "detail": UNMAPPED_MESSAGE,
        "code": "app_error",
    }


def test_create_app_without_settings_reads_the_environment(
    migrated_sqlite_url, monkeypatch
):
    monkeypatch.setenv("MY_APP_DATABASE_URL", migrated_sqlite_url)

    with TestClient(create_app()) as writer:
        created = writer.post("/api/todos", json={"title": "from env"})
    with TestClient(create_app()) as reader:
        titles = [todo["title"] for todo in reader.get("/api/todos").json()["items"]]

    assert created.status_code == HTTPStatus.CREATED
    assert titles == ["from env"]


def test_create_app_each_call_owns_an_independent_store():
    with TestClient(create_app(Settings())) as first:
        first.post("/api/todos", json={"title": "only in first"})

    with TestClient(create_app(Settings())) as second:
        assert second.get("/api/todos").json()["items"] == []


def test_create_app_with_sql_keeps_todos_across_apps(migrated_sqlite_url):
    settings = Settings(database_url=migrated_sqlite_url)
    with TestClient(create_app(settings)) as first:
        first.post("/api/todos", json={"title": "survives"})

    with TestClient(create_app(settings)) as second:
        titles = [todo["title"] for todo in second.get("/api/todos").json()["items"]]

    assert titles == ["survives"]


def test_create_app_on_unmigrated_database_answers_500(sqlite_url):
    # The app never creates its schema: a database nobody migrated is a bug in
    # the deployment, reported as a server error rather than repaired.
    app = create_app(Settings(database_url=sqlite_url))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/todos")

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_create_app_every_route_is_a_coroutine_function(make_container):
    # app.routes holds each included router as one opaque entry (fastapi
    # 0.141); iter_route_contexts flattens them the way the OpenAPI builder does.
    app_routes = create_app(container=make_container()).routes
    routes = [
        context.original_route
        for context in iter_route_contexts(app_routes)
        if isinstance(context.original_route, APIRoute)
    ]

    sync_routes = [
        route.path for route in routes if not iscoroutinefunction(route.endpoint)
    ]

    assert routes != []
    assert sync_routes == []


def test_create_app_shutdown_closes_factory_built_container(
    monkeypatch, make_container
):
    closed: list[str] = []
    resources = AsyncExitStack()
    resources.push_async_callback(_record, closed, "built")
    container = Container(make_container().todos, _resources=resources)
    monkeypatch.setattr(app_module, "build_container", lambda _: container)

    app = create_app(Settings())
    assert closed == []
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == HTTPStatus.OK
        assert closed == []

    assert closed == ["built"]


async def test_create_app_shutdown_leaves_supplied_container_caller_owned(
    make_container,
):
    closed: list[str] = []
    resources = AsyncExitStack()
    resources.push_async_callback(_record, closed, "supplied")
    container = Container(make_container().todos, _resources=resources)

    with TestClient(create_app(container=container)) as client:
        assert client.get("/healthz").status_code == HTTPStatus.OK

    assert closed == []
    await container.aclose()
    assert closed == ["supplied"]


async def _record(log: list[str], name: str) -> None:
    """An async cleanup callback that records that it ran."""
    log.append(name)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("GET", "/todos", id="list"),
        pytest.param("POST", "/todos", id="create"),
        pytest.param(
            "POST",
            "/todos/01900000-0000-7000-8000-000000000001/complete",
            id="complete",
        ),
        pytest.param(
            "DELETE", "/todos/01900000-0000-7000-8000-000000000001", id="delete"
        ),
    ],
)
def test_resource_routes_require_api_prefix(client, method, path):
    assert client.request(method, path).status_code == HTTPStatus.NOT_FOUND


def test_api_prefixed_list_returns_empty_page(client):
    response = client.get("/api/todos")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"items": [], "next_cursor": None}


def test_operation_ids_are_unique_function_names(make_container):
    app = create_app(container=make_container())
    schema = app.openapi()
    operations = [
        operation["operationId"]
        for path in schema["paths"].values()
        for operation in path.values()
    ]
    endpoint_names = [
        context.original_route.endpoint.__name__
        for context in iter_route_contexts(app.routes)
        if isinstance(context.original_route, APIRoute)
    ]

    assert set(operations) == {
        "healthz",
        "list_todos",
        "create_todo",
        "complete_todo",
        "delete_todo",
    }
    assert sorted(operations) == sorted(endpoint_names)
    assert len(operations) == len(set(operations))


def test_duplicate_endpoint_names_warn_when_building_openapi():
    app = FastAPI(generate_unique_id_function=app_module.route_operation_id)

    async def duplicate() -> None:
        return None

    app.add_api_route("/first", duplicate)
    app.add_api_route("/second", duplicate)

    with pytest.warns(UserWarning, match="Duplicate Operation ID"):
        app.openapi()


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="unset"),
        pytest.param("", id="blank"),
        pytest.param(" , ", id="empty-items"),
    ],
)
def test_create_app_empty_cors_origins_add_no_middleware(
    monkeypatch, make_container, value
):
    if value is not None:
        monkeypatch.setenv("MY_APP_CORS_ORIGINS", value)
    app = create_app(container=make_container())

    assert app.user_middleware == []


@pytest.mark.parametrize(
    ("origin", "status", "allowed"),
    [
        pytest.param(
            "https://app.example.com",
            HTTPStatus.OK,
            "https://app.example.com",
            id="allowed",
        ),
        pytest.param("https://evil.example", HTTPStatus.BAD_REQUEST, None, id="denied"),
    ],
)
def test_cors_preflight_checks_origins_and_allows_json_post(
    monkeypatch, origin, status, allowed
):
    monkeypatch.setenv(
        "MY_APP_CORS_ORIGINS", "http://localhost:5173, https://app.example.com"
    )
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/todos",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == status
    assert response.headers.get("access-control-allow-origin") == allowed
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in response.headers


def test_create_app_explicit_settings_control_cors_with_supplied_container(
    make_container,
):
    app = create_app(
        Settings(cors_origins=["https://app.example.com"]), container=make_container()
    )
    with TestClient(app) as client:
        response = client.get("/healthz", headers={"Origin": "https://app.example.com"})

    assert response.headers["access-control-allow-origin"] == "https://app.example.com"


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        pytest.param(
            "https://app.example.com", "https://app.example.com", id="allowed"
        ),
        pytest.param("https://evil.example", None, id="denied"),
    ],
)
def test_cors_headers_cover_unhandled_errors(sqlite_url, origin, allowed):
    app = create_app(
        Settings(database_url=sqlite_url, cors_origins=["https://app.example.com"])
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/todos", headers={"Origin": origin})

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.headers.get("access-control-allow-origin") == allowed


def test_create_app_cors_still_allows_middleware_registration(make_container):
    app = create_app(
        Settings(cors_origins=["https://app.example.com"]), container=make_container()
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["testserver"])
    with TestClient(app) as client:
        response = client.get("/healthz", headers={"Origin": "https://app.example.com"})

    assert response.status_code == HTTPStatus.OK
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"


def test_create_app_supplied_container_ignores_invalid_storage_env_but_reads_cors(
    monkeypatch, make_container
):
    container = make_container()
    monkeypatch.setenv("MY_APP_DATABASE_URL", "not-a-database-url")
    monkeypatch.setenv("MY_APP_CORS_ORIGINS", "https://APP.EXAMPLE.COM:443")
    with TestClient(create_app(container=container)) as client:
        response = client.get(
            "/api/todos", headers={"Origin": "https://app.example.com"}
        )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"items": [], "next_cursor": None}
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (AppError("base failure"), 400, "app_error"),
        (TodoNotFoundError(UUID(int=1)), 404, "todo_not_found"),
        (InvalidTodoError("bad title"), 422, "invalid_todo"),
        (InvalidCursorError("bad cursor"), 422, "invalid_cursor"),
        (InvalidPageLimitError("bad limit"), 422, "invalid_page_limit"),
    ],
)
def test_domain_error_returns_problem_details(make_container, error, status, code):
    app = create_app(container=make_container())

    @app.get("/failure")
    async def failure() -> None:
        raise error

    with TestClient(app) as client:
        response = client.get("/failure")

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": str(error),
        "code": code,
    }


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("GET", "/api/nope", 404, "not_found"),
        ("PUT", "/api/todos", 405, "method_not_allowed"),
    ],
)
def test_routing_error_returns_problem_details(client, method, path, status, code):
    response = client.request(method, path)

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": HTTPStatus(status).phrase,
        "code": code,
    }
    if status == 405:
        assert response.headers["allow"] == "GET"


@pytest.mark.parametrize(
    ("status", "detail"),
    [(403, "denied"), (403, {"secret": "hidden"}), (204, "ignored"), (304, "ignored")],
)
def test_http_exception_keeps_headers_and_respects_body_rules(
    make_container, status, detail
):
    app = create_app(container=make_container())

    @app.get("/http-failure")
    async def failure() -> None:
        raise HTTPException(status, detail=detail, headers={"X-Reason": "policy"})

    with TestClient(app) as client:
        response = client.get("/http-failure")

    assert response.status_code == status
    assert response.headers["x-reason"] == "policy"
    if status in (204, 304):
        assert response.content == b""
    else:
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json() == {
            "type": "about:blank",
            "title": "Forbidden",
            "status": 403,
            "detail": detail if isinstance(detail, str) else "Forbidden",
            "code": "http_error",
        }


def test_unhandled_exception_returns_500_problem_without_leaking(
    make_container, caplog
):
    app = create_app(container=make_container())
    error = RuntimeError("db password=hunter2")

    @app.get("/unexpected")
    async def unexpected() -> None:
        raise error

    with (
        caplog.at_level("ERROR", logger="my_app.api.errors"),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/unexpected")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "An unexpected error occurred",
        "code": "internal_error",
    }
    assert "hunter2" not in response.text
    records = [
        record for record in caplog.records if record.name == "my_app.api.errors"
    ]
    assert len(records) == 1
    assert records[0].getMessage() == "Unhandled exception"
    assert records[0].exc_info is not None
    assert records[0].exc_info[1] is error
    assert "hunter2" in caplog.text


def test_openapi_documents_every_error_as_problem_details(client):
    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    assert set(schemas) == {
        "HealthResponse",
        "ProblemDetails",
        "ProblemFieldError",
        "TodoCreateRequest",
        "TodoPageResponse",
        "TodoResponse",
    }
    seen_errors = 0
    for path in document["paths"].values():
        for operation in path.values():
            responses = operation["responses"]
            assert "500" in responses
            if operation.get("parameters") or "requestBody" in operation:
                assert "422" in responses
            for status, response in responses.items():
                if int(status) >= 400:
                    seen_errors += 1
                    assert response["content"] == {
                        "application/problem+json": {
                            "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                        }
                    }
    assert seen_errors > 0


@pytest.mark.parametrize("status", [499, 599])
@pytest.mark.parametrize("detail", ["custom failure", {"private": "context"}])
def test_http_exception_unregistered_status_keeps_status_detail_and_headers(
    make_container, status, detail
):
    app = create_app(container=make_container())

    @app.get("/custom-http")
    async def custom_http() -> None:
        raise HTTPException(status, detail=detail, headers={"X-Reason": "custom"})

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/custom-http")

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-reason"] == "custom"
    assert response.json() == {
        "type": "about:blank",
        "title": "Unknown Status",
        "status": status,
        "detail": detail if isinstance(detail, str) else "Unknown Status",
        "code": "http_error",
    }


@pytest.mark.parametrize(
    "error",
    [
        HTTPException(
            401, "authentication required", headers={"WWW-Authenticate": "Bearer"}
        ),
        FastAPIHTTPException(
            499, {"private": "context"}, headers={"X-Reason": "custom"}
        ),
    ],
)
def test_middleware_http_exception_returns_problem_without_server_error_log(
    make_container, caplog, error
):
    app = create_app(
        Settings(cors_origins=["https://app.example.com"]), container=make_container()
    )

    async def reject(request, call_next):
        raise error

    app.add_middleware(BaseHTTPMiddleware, dispatch=reject)
    with (
        caplog.at_level("ERROR", logger="my_app.api.errors"),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/healthz", headers={"Origin": "https://app.example.com"})

    assert response.status_code == error.status_code
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"
    for name, value in error.headers.items():
        assert response.headers[name] == value
    phrase = "Unauthorized" if error.status_code == 401 else "Unknown Status"
    assert response.json() == {
        "type": "about:blank",
        "title": phrase,
        "status": error.status_code,
        "detail": error.detail if isinstance(error.detail, str) else phrase,
        "code": "http_error",
    }
    assert not [
        record for record in caplog.records if record.name == "my_app.api.errors"
    ]
