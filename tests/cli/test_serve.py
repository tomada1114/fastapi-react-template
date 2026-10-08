from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

import pytest
import uvicorn
from fastapi import FastAPI
from typer.testing import CliRunner

from my_app.cli.errors import ExitCode
from my_app.cli.main import app

# Run in a fresh interpreter: this test process has long since imported both.
_IMPORT_PROBE = (
    "import sys, my_app.cli.main; "
    "print(sorted(m for m in ('fastapi', 'uvicorn') if m in sys.modules))"
)


@dataclass
class _ServeCall:
    app: object
    host: str
    port: int


@pytest.fixture
def serve_calls(monkeypatch):
    """Record ``uvicorn.run`` calls instead of starting a real server.

    The server is the boundary: binding a port in a test would be slow, could
    collide with a developer's server, and would never return.
    """
    calls: list[_ServeCall] = []

    def _fake_run(served_app: object, *, host: str, port: int) -> None:
        calls.append(_ServeCall(served_app, host, port))

    monkeypatch.setattr(uvicorn, "run", _fake_run)
    return calls


def test_serve_without_options_binds_loopback_port_8000(serve_calls):
    result = CliRunner().invoke(app, ["serve"])

    assert result.exit_code == ExitCode.OK
    assert len(serve_calls) == 1
    assert (serve_calls[0].host, serve_calls[0].port) == ("127.0.0.1", 8000)
    assert isinstance(serve_calls[0].app, FastAPI)


def test_serve_with_options_binds_the_given_host_and_port(serve_calls):
    result = CliRunner().invoke(app, ["serve", "--host", "localhost", "--port", "9000"])

    assert result.exit_code == ExitCode.OK
    assert [(call.host, call.port) for call in serve_calls] == [("localhost", 9000)]


def test_serve_invalid_port_exits_with_usage_error_without_serving(serve_calls):
    result = CliRunner().invoke(app, ["serve", "--port", "not-a-port"])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert serve_calls == []


def test_serve_invalid_setting_exits_3_without_serving(serve_calls, monkeypatch):
    monkeypatch.setenv("MY_APP_DATABASE_URL", "sqlite:///:memory:")

    result = CliRunner().invoke(app, ["serve"])

    assert result.exit_code == ExitCode.CONFIG_ERROR
    assert result.stderr.startswith("Error: invalid configuration: ")
    assert serve_calls == []


def test_cli_import_does_not_load_the_server_stack():
    result = subprocess.run(  # noqa: S603 - fixed argv: this interpreter and a literal
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        check=True,
        text=True,
    )

    assert result.stdout.strip() == "[]"
