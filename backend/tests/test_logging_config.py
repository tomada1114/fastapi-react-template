"""Formatting, handler ownership and request-context propagation."""

from __future__ import annotations

import io
import json
import logging

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient

from my_app.api.app import create_app
from my_app.logging_config import configure_logging, request_id_var


@pytest.fixture
def configured_logging():
    logger = logging.getLogger("my_app")
    original = (logger.handlers[:], logger.level, logger.propagate)
    logger.handlers = []
    configure_logging("INFO", "json")
    stream = io.StringIO()
    assert isinstance(logger.handlers[0], logging.StreamHandler)
    logger.handlers[0].setStream(stream)
    yield logger, stream
    for handler in logger.handlers:
        handler.close()
    logger.handlers, logger.level, logger.propagate = original


def test_configure_logging_replaces_its_handler_and_preserves_other_handlers(
    configured_logging,
):
    logger, _ = configured_logging
    external = logging.NullHandler()
    logger.addHandler(external)
    configure_logging("DEBUG", "text")
    configure_logging("INFO", "json")
    assert len(logger.handlers) == 2
    assert external in logger.handlers
    assert logger.propagate is True


def test_json_logs_include_context_access_fields_and_traceback(configured_logging):
    _, stream = configured_logging

    def failure():
        msg = "test failure"
        raise RuntimeError(msg)

    token = request_id_var.set("format-test")
    try:
        try:
            failure()
        except RuntimeError:
            logging.getLogger("my_app.sample").exception(
                "Failure",
                extra={
                    "method": "GET",
                    "path": "/test",
                    "status": 500,
                    "duration_ms": 1.2,
                },
            )
    finally:
        request_id_var.reset(token)
    record = json.loads(stream.getvalue())
    assert set(record) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "request_id",
        "exception",
        "method",
        "path",
        "status",
        "duration_ms",
    }
    assert record["request_id"] == "format-test"
    assert record["timestamp"].endswith("+00:00")
    assert record["level"] == "ERROR"
    assert "RuntimeError: test failure" in record["exception"]


def test_outside_request_and_text_format_include_none_identity(configured_logging):
    logger, _ = configured_logging
    configure_logging("INFO", "text")
    stream = io.StringIO()
    logger.handlers[0].setStream(stream)
    logging.getLogger("my_app.sample").info("outside")
    assert "[None] outside" in stream.getvalue()


def test_preserved_handler_receives_identity_before_it_formats(configured_logging):
    logger, _ = configured_logging
    stream = io.StringIO()
    external = logging.StreamHandler(stream)
    external.setFormatter(logging.Formatter("%(request_id)s %(message)s"))
    logger.addHandler(external)
    configure_logging("INFO", "text")
    token = request_id_var.set("external-id")
    try:
        logging.getLogger("my_app.adapters.sample").info("adapter")
    finally:
        request_id_var.reset(token)
    logging.getLogger("my_app.adapters.sample").info("outside")
    assert stream.getvalue().splitlines() == ["external-id adapter", "None outside"]


@pytest.mark.parametrize("control", ["%0A", "%0D%0A", "%E2%80%A8", "%C2%85"])
def test_text_access_log_escapes_decoded_path_controls(
    configured_logging, make_container, control
):
    logger, _ = configured_logging
    configure_logging("INFO", "text")
    stream = io.StringIO()
    logger.handlers[0].setStream(stream)
    with TestClient(create_app(container=make_container())) as client:
        response = client.get(f"/line{control}ERROR%20forged")
    assert response.status_code == 404
    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    assert "ERROR forged" in lines[0]


@pytest.mark.anyio
async def test_concurrent_requests_keep_adapter_and_access_ids_separate(
    configured_logging, make_container, caplog
):
    app = create_app(container=make_container())
    arrived = 0
    barrier = anyio.Event()

    async def log_route():
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            barrier.set()
        await barrier.wait()
        logging.getLogger("my_app.adapters.sample").info("adapter")
        return {}

    app.add_api_route("/log", log_route)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def send(value):
            response = await client.get("/log", headers={"X-Request-ID": value})
            assert response.headers["X-Request-ID"] == value

        with caplog.at_level("INFO", logger="my_app"):
            async with anyio.create_task_group() as group:
                group.start_soon(send, "one")
                group.start_soon(send, "two")
    for name in ("my_app.adapters.sample", "my_app.access"):
        records = [r for r in caplog.records if r.name == name]
        assert sorted(r.request_id for r in records) == ["one", "two"]
    assert request_id_var.get() is None
