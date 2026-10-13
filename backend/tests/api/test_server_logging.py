"""Privacy and lifecycle contracts through an owned Uvicorn process."""

from __future__ import annotations

import errno
import json
import os
import signal
import socket
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import anyio
import httpx
import pytest

pytestmark = pytest.mark.anyio

# Values enter the failure at request time, never as literals in traceback lines.
APP_SOURCE = """
import json
import logging
import os
from urllib.parse import parse_qs
from my_app.api.app import create_app
from my_app.settings import Settings

class Faults:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/probe/"):
            await self.app(scope, receive, send)
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        payload = json.loads(body)
        cause = ValueError(parse_qs(scope["query_string"].decode())["value"][0])
        error = RuntimeError(payload["message"])
        error.add_note(payload["note"])
        error.__cause__ = cause
        if payload["group"]:
            error = ExceptionGroup(payload["group_message"], [error, cause])
        if scope["path"] == "/probe/after":
            await send({"type": "http.response.start", "status": 202,
                        "headers": [(b"content-type", b"text/plain")]})
        raise error

class ResponseStarts:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/probe/"):
            await self.app(scope, receive, send)
            return
        starts = 0
        async def count(message):
            nonlocal starts
            if message["type"] == "http.response.start":
                starts += 1
            await send(message)
        try:
            await self.app(scope, receive, count)
        finally:
            logging.getLogger("my_app.probe").info("Response starts=%d", starts)

def factory():
    settings = Settings(_env_file=None,
                        database_url=os.environ["MY_APP_DATABASE_URL"],
                        log_format=os.environ["MY_APP_LOG_FORMAT"],
                        log_level="INFO", cors_origins=["https://app.example"])
    app = create_app(settings)
    app.add_middleware(Faults)
    return ResponseStarts(app)
"""

SENTINELS = {
    "message": "SYNTHETIC_BODY_VALUE",
    "note": "SYNTHETIC_EXCEPTION_NOTE",
    "query": "SYNTHETIC_QUERY_VALUE",
    "group_message": "SYNTHETIC_GROUP_MESSAGE",
}


@dataclass
class ServerEvidence:
    """Only this test's process, port and complete combined output."""

    port: int
    chunks: list[bytes] = field(default_factory=list)
    returncode: int | None = None
    released: bool = False

    @property
    def output(self) -> str:
        return b"".join(self.chunks).decode("utf-8")


def port_is_free(port):
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == errno.ECONNREFUSED


@asynccontextmanager
async def owned_server(tmp_path, database_url, fmt):
    """Drain logs concurrently; stop only the launched process on every exit."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    assert port_is_free(port)
    evidence = ServerEvidence(port)
    (tmp_path / "privacy_probe.py").write_text(APP_SOURCE, encoding="utf-8")
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("MY_APP_")
    }
    env.update(
        {
            "PYTHONPATH": str(tmp_path),
            "MY_APP_DATABASE_URL": database_url,
            "MY_APP_CORS_ORIGINS": "https://app.example",
            "MY_APP_LOG_LEVEL": "INFO",
            "MY_APP_LOG_FORMAT": fmt,
        }
    )
    process = await anyio.open_process(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "privacy_probe:factory",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    ready = anyio.Event()

    async def collect():
        assert process.stdout is not None
        async for chunk in process.stdout:
            evidence.chunks.append(chunk)
            if f"Uvicorn running on http://127.0.0.1:{port}" in evidence.output:
                ready.set()

    try:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(collect)
            try:
                with anyio.fail_after(15):
                    await ready.wait()
                yield evidence
            finally:
                with anyio.CancelScope(shield=True):
                    process.terminate()
                    with anyio.move_on_after(10) as deadline:
                        await process.wait()
                    if deadline.cancel_called:
                        process.kill()
                        with anyio.fail_after(5):
                            await process.wait()
                    evidence.returncode = process.returncode
    finally:
        with anyio.CancelScope(shield=True):
            await process.aclose()
        evidence.released = port_is_free(port)
        assert evidence.released, (
            "The owned port remains occupied; no other PID was touched"
        )


def assert_safe_diagnostics(evidence, fmt, path, group):
    output = evidence.output
    for sentinel in SENTINELS.values():
        assert sentinel not in output
    assert "Exception in ASGI application" in output
    assert "Traceback" in output
    assert "privacy_probe.py" in output
    expected_type = "builtins.ExceptionGroup" if group else "builtins.RuntimeError"
    assert expected_type in output
    assert "privacy-request" in output
    assert evidence.returncode in {0, -signal.SIGTERM}
    assert "Finished server process" in output
    assert evidence.released
    if fmt == "json":
        records = [
            json.loads(line) for line in output.splitlines() if line.startswith("{")
        ]
        access = [
            r
            for r in records
            if r["logger"] == "my_app.access" and r.get("path") == path
        ]
        assert len(access) == 1
        assert access[0]["request_id"] == "privacy-request"
        errors = [r for r in records if r["logger"] == "my_app.api.errors"]
        assert len(errors) == 1
        assert errors[0]["exception_type"] == expected_type
        assert errors[0]["request_id"] == "privacy-request"
    else:
        access = [
            line
            for line in output.splitlines()
            if "my_app.access [privacy-request]" in line
        ]
        assert len(access) == 1
        assert path in access[0]
        assert "my_app.api.errors [privacy-request]" in output
    assert output.count("Response starts=1") == 1
    assert "Response starts=2" not in output


@pytest.mark.parametrize(
    "fmt", [pytest.param("text", id="text"), pytest.param("json", id="json")]
)
@pytest.mark.parametrize(
    "group", [pytest.param(False, id="chain-notes"), pytest.param(True, id="group")]
)
async def test_server_error_before_headers_keeps_safe_correlated_diagnostics(
    tmp_path, migrated_sqlite_url, fmt, group
):
    async with (
        owned_server(tmp_path, migrated_sqlite_url, fmt) as evidence,
        httpx.AsyncClient(base_url=f"http://127.0.0.1:{evidence.port}") as client,
    ):
        seed = await client.post("/api/todos", json={"title": "safe seed"})
        assert seed.status_code == 201  # Open the actual migrated SQL engine.
        response = await client.post(
            "/probe/before",
            params={"value": SENTINELS["query"]},
            json={**SENTINELS, "group": group},
            headers={
                "Origin": "https://app.example",
                "X-Request-ID": "privacy-request",
            },
        )

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["access-control-allow-origin"] == "https://app.example"
    assert (
        response.headers["x-request-id"]
        == response.json()["request_id"]
        == "privacy-request"
    )
    assert response.json()["detail"] == "An unexpected error occurred"
    assert response.json()["code"] == "internal_error"
    assert_safe_diagnostics(evidence, fmt, "/probe/before", group)


@pytest.mark.parametrize(
    "fmt", [pytest.param("text", id="text"), pytest.param("json", id="json")]
)
@pytest.mark.parametrize(
    "group", [pytest.param(False, id="chain-notes"), pytest.param(True, id="group")]
)
async def test_server_error_after_headers_never_sends_second_response(
    tmp_path, migrated_sqlite_url, fmt, group
):
    async with (
        owned_server(tmp_path, migrated_sqlite_url, fmt) as evidence,
        httpx.AsyncClient(base_url=f"http://127.0.0.1:{evidence.port}") as client,
        client.stream(
            "POST",
            "/probe/after",
            params={"value": SENTINELS["query"]},
            json={**SENTINELS, "group": group},
            headers={
                "Origin": "https://app.example",
                "X-Request-ID": "privacy-request",
            },
        ) as response,
    ):
        assert response.status_code == 202
        assert response.headers["x-request-id"] == "privacy-request"
        assert response.headers["access-control-allow-origin"] == "https://app.example"
        with pytest.raises(httpx.RemoteProtocolError, match="incomplete chunked read"):
            await response.aread()

    assert_safe_diagnostics(evidence, fmt, "/probe/after", group)


async def test_owned_server_probe_failure_stops_process_and_releases_port(
    tmp_path, migrated_sqlite_url
):
    observed = []

    async def fail_probe():
        async with owned_server(tmp_path, migrated_sqlite_url, "text") as evidence:
            observed.append(evidence)
            message = "synthetic probe failure"
            raise RuntimeError(message)

    with pytest.raises(ExceptionGroup, match="unhandled errors") as raised:
        await fail_probe()

    assert len(raised.value.exceptions) == 1
    assert str(raised.value.exceptions[0]) == "synthetic probe failure"
    assert len(observed) == 1
    assert observed[0].returncode in {0, -signal.SIGTERM}
    assert observed[0].released
    assert "Finished server process" in observed[0].output
