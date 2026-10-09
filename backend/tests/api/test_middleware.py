"""Request identity and access logging at the real ASGI boundary."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from my_app.api.app import create_app
from my_app.api.middleware import RequestIdMiddleware
from my_app.settings import Settings


@pytest.mark.parametrize("value", ["abc-123", "A" * 128, "a.b_c-0"])
def test_request_id_well_formed_is_echoed_and_logged(make_container, caplog, value):
    with (
        caplog.at_level("INFO", logger="my_app.access"),
        TestClient(create_app(container=make_container())) as client,
    ):
        response = client.get("/healthz", headers={"X-Request-ID": value})
    assert response.headers.get("X-Request-ID") == value
    records = [record for record in caplog.records if record.name == "my_app.access"]
    assert len(records) == 1
    assert records[0].request_id == value
    assert records[0].status == 200
    assert records[0].method == "GET"
    assert records[0].path == "/healthz"
    assert records[0].duration_ms >= 0


@pytest.mark.parametrize("value", [None, "", "a" * 129, "has space", "/"])
def test_request_id_malformed_is_replaced(make_container, value):
    headers = {} if value is None else {"X-Request-ID": value}
    with TestClient(create_app(container=make_container())) as client:
        response = client.get("/healthz", headers=headers)
    assert UUID(response.headers["X-Request-ID"]).version == 7


@pytest.mark.parametrize(
    "case",
    [
        ("delete", "/api/todos/01900000-0000-7000-8000-ffffffffffff", {}, 404),
        ("post", "/api/todos", {"json": {}}, 422),
        ("get", "/missing", {}, 404),
        ("post", "/healthz", {}, 405),
        ("get", "/failure", {}, 500),
    ],
)
def test_problem_details_carry_the_request_id(make_container, caplog, case):
    method, path, kwargs, status = case
    app = create_app(container=make_container())

    async def failure():
        msg = "test failure"
        raise RuntimeError(msg)

    app.add_api_route("/failure", failure)
    with (
        caplog.at_level("INFO", logger="my_app.access"),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = getattr(client, method)(
            path, headers={"X-Request-ID": "r-problem"}, **kwargs
        )
    assert response.status_code == status
    assert (
        response.json()["request_id"] == response.headers["X-Request-ID"] == "r-problem"
    )
    records = [record for record in caplog.records if record.name == "my_app.access"]
    assert len(records) == 1
    assert records[0].status == status


def test_logs_never_contain_body_or_query(make_container, caplog):
    with (
        caplog.at_level("INFO", logger="my_app"),
        TestClient(create_app(container=make_container())) as client,
    ):
        client.post("/api/todos", json={"title": "SENTINEL-TITLE"})
        client.get("/api/todos?limit=5&cursor=SENTINEL-CURSOR")
    assert "SENTINEL" not in caplog.text
    assert all(
        "SENTINEL" not in str(value)
        for record in caplog.records
        for value in record.__dict__.values()
    )


def test_cors_preflight_problem_and_response_share_request_id(make_container):
    app = create_app(
        Settings(cors_origins=["https://app.example"]), container=make_container()
    )
    with TestClient(app) as client:
        response = client.options(
            "/api/todos",
            headers={
                "Origin": "https://other.example",
                "Access-Control-Request-Method": "POST",
                "X-Request-ID": "preflight",
            },
        )
    assert (
        response.json()["request_id"] == response.headers["X-Request-ID"] == "preflight"
    )


def test_duplicate_request_id_headers_use_first(make_container):
    with TestClient(create_app(container=make_container())) as client:
        response = client.get(
            "/healthz",
            headers=[("X-Request-ID", "/"), ("X-Request-ID", "valid-second")],
        )
    assert UUID(response.headers["X-Request-ID"]).version == 7


@pytest.mark.anyio
async def test_streaming_access_record_follows_final_body(caplog):
    sent = []

    async def stream(scope, receive, send):
        await send({"type": "http.response.start", "status": 202, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        assert not [r for r in caplog.records if r.name == "my_app.access"]
        await send({"type": "http.response.body", "body": b"last"})

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        assert not [r for r in caplog.records if r.name == "my_app.access"]
        sent.append(message)

    with caplog.at_level("INFO", logger="my_app.access"):
        await RequestIdMiddleware(stream)(
            {"type": "http", "method": "GET", "path": "/stream", "headers": []},
            receive,
            send,
        )
    assert sent[-1] == {"type": "http.response.body", "body": b"last"}
    records = [r for r in caplog.records if r.name == "my_app.access"]
    assert len(records) == 1
    assert records[0].status == 202
