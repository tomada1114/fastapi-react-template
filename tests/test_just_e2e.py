"""Tests for the justfile's ``e2e`` recipe: the browser test's own run.

The recipe body is read from the justfile and run with bash, so CI needs no
``just``, Node.js, or browser. Two stand-ins go first on ``PATH``:

- a fake ``uv`` runs ``uv run --locked python ...`` with this interpreter, so
  the recipe's own free-port and port-check one-liners run for real;
- a fake ``pnpm`` answers ``pnpm --dir e2e run typecheck`` with
  ``FAKE_TYPECHECK_EXIT`` (0 by default) and stands in for
  ``pnpm --dir e2e exec playwright test``: it records its arguments and
  environment under ``FAKE_RECORD``, then behaves as ``FAKE_PLAYWRIGHT`` says:
  ``exit:N`` exits N; ``leak:N`` leaves a listener of its own, in a session of
  its own, on ``E2E_API_PORT`` (as a server Playwright failed to stop would)
  and exits N; ``hang`` prints ``ready`` and waits for a signal, recording it.

Every process a test starts is its own: the listeners are stopped by the pid
they record, and nothing touches a port the test did not pick.

Each body runs under every bash on the host the tests can find: the one on
``PATH`` and ``/bin/bash``, which is bash 3.2 on macOS.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    type RunE2e = Callable[..., Run]

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"
JUST = "{{ quote(just_executable()) }}"
FAKE_JUST = "/opt/fake just/bin/just"
RUN_TIMEOUT = 60.0
READY_TIMEOUT = 20.0

FAKE_UV = """\
#!/bin/sh
if [ "$1 $2 $3" = "run --locked python" ]; then
  shift 3
  exec "$FAKE_PYTHON" "$@"
fi
echo "fake uv: unexpected arguments: $*" >&2
exit 97
"""

FAKE_PNPM = """\
#!/usr/bin/env bash
if [ "$*" = "--dir e2e run typecheck" ]; then
  exit "${FAKE_TYPECHECK_EXIT:-0}"
fi
if [ "$1 $2 $3 $4 $5" != "--dir e2e exec playwright test" ]; then
  echo "fake pnpm: unexpected arguments: $*" >&2
  exit 97
fi
shift 5
"$FAKE_PYTHON" -c 'import json, os, sys
with open(sys.argv[1], "w") as f:
    json.dump({"args": sys.argv[2:], "env": dict(os.environ)}, f)' \\
  "$FAKE_RECORD/playwright.json" "$@"
case "$FAKE_PLAYWRIGHT" in
  exit:*) exit "${FAKE_PLAYWRIGHT#exit:}" ;;
  leak:*)
    "$FAKE_PYTHON" -c 'import os, socket, sys, time
os.setsid()
s = socket.socket()
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen()
with open(sys.argv[2] + ".tmp", "w") as f:
    f.write(str(os.getpid()))
os.rename(sys.argv[2] + ".tmp", sys.argv[2])
time.sleep(300)' "$E2E_API_PORT" "$FAKE_RECORD/listener.pid" >/dev/null 2>&1 &
    while [ ! -f "$FAKE_RECORD/listener.pid" ]; do sleep 0.05; done
    exit "${FAKE_PLAYWRIGHT#leak:}"
    ;;
  hang)
    sleep 300 &
    child=$!
    trap 'kill "$child"; echo INT >> "$FAKE_RECORD/signals"; exit 130' INT
    trap 'kill "$child"; echo TERM >> "$FAKE_RECORD/signals"; exit 143' TERM
    echo ready
    wait "$child"
    ;;
esac
exit 98
"""

# Every Settings field, with the value `just e2e` gives it.
E2E_SETTINGS = {
    "MY_APP_CORS_ORIGINS": "",
    "MY_APP_LOG_LEVEL": "INFO",
    "MY_APP_LOG_FORMAT": "text",
}
HOSTILE = {
    "MY_APP_DATABASE_URL": "sqlite+aiosqlite:////hostile/dev.db",
    "MY_APP_CORS_ORIGINS": "https://hostile.example",
    "MY_APP_LOG_LEVEL": "DEBUG",
    "MY_APP_LOG_FORMAT": "json",
    "MY_APP_API_PORT": "8000",
    "MY_APP_FUTURE_SETTING": "hostile",
}
_DATABASE = re.compile(r"database in (?P<tmp>\S+)")
_PORTS = re.compile(r"API port (?P<api>\d+), screen port (?P<web>\d+)")

SETTINGS_PROBE = """\
import json, sys
from my_app.settings import Settings
settings = Settings(_env_file=sys.argv[1])
print(json.dumps({"fields": sorted(Settings.model_fields), "values": settings.model_dump(mode="json")}))
"""


def _bashes() -> list[str]:
    found = [shutil.which("bash"), "/bin/bash"]
    paths = {str(Path(p).resolve()) for p in found if p and Path(p).is_file()}
    return sorted(paths)


BASHES = [pytest.param(path, id=path) for path in _bashes()]


def _recipe_body(header: str) -> str:
    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header)) + 1
    body: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith("    "):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)).strip() + "\n"


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class Run:
    status: int
    output: str
    record: Path

    @property
    def tmp(self) -> Path:
        match = _DATABASE.search(self.output)
        assert match, self.output
        return Path(match["tmp"])

    @property
    def ports(self) -> tuple[int, int]:
        match = _PORTS.search(self.output)
        assert match, self.output
        return int(match["api"]), int(match["web"])

    @property
    def playwright(self) -> dict[str, object] | None:
        path = self.record / "playwright.json"
        if not path.is_file():
            return None
        recorded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        return recorded


@dataclass
class Fixture:
    script: Path
    record: Path
    env: dict[str, str]
    started: list[subprocess.Popen[str]]

    def popen(self, bash: str, *args: str, **env: str) -> subprocess.Popen[str]:
        process = subprocess.Popen(  # noqa: S603 -- fixed argv, no shell
            [bash, str(self.script), *args],
            env=self.env | env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            process_group=0,
        )
        self.started.append(process)
        return process

    def run(self, bash: str, *args: str, **env: str) -> Run:
        process = self.popen(bash, *args, **env)
        output, _ = process.communicate(timeout=RUN_TIMEOUT)
        return Run(process.returncode, output, self.record)


@pytest.fixture
def e2e(tmp_path: Path) -> Iterator[Fixture]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, text in (("uv", FAKE_UV), ("pnpm", FAKE_PNPM)):
        (bindir / name).write_text(text, encoding="utf-8")
        (bindir / name).chmod(0o755)
    record = tmp_path / "record"
    record.mkdir()
    script = tmp_path / "e2e.sh"
    script.write_text(
        _recipe_body("e2e ").replace(JUST, shlex.quote(FAKE_JUST)), encoding="utf-8"
    )
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("MY_APP_", "E2E_", "FAKE_")) and name != "JUST"
    }
    env = inherited | {
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_PYTHON": sys.executable,
        "FAKE_RECORD": str(record),
        "FAKE_PLAYWRIGHT": "exit:0",
    }
    fixture = Fixture(script, record, env, [])
    yield fixture

    # A failing test leaks nothing: the recipe and its fakes lead groups of
    # their own, and a leaked listener records its pid.
    for process in fixture.started:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=RUN_TIMEOUT)
        if process.stdout is not None:
            process.stdout.close()
    pid_file = record / "listener.pid"
    if pid_file.is_file():
        with contextlib.suppress(ProcessLookupError):
            os.kill(int(pid_file.read_text(encoding="utf-8")), signal.SIGKILL)


def _assert_cleaned_up(run: Run) -> None:
    """Both ports were checked and the temporary directory is gone."""
    api, web = run.ports
    assert f"nothing listening on {api}" in run.output
    assert f"nothing listening on {web}" in run.output
    assert f"removed {run.tmp}" in run.output
    assert not run.tmp.exists()


@pytest.mark.parametrize("bash", BASHES)
def test_e2e_passing_run_cleans_up_and_exits_zero(e2e: Fixture, bash: str) -> None:
    run = e2e.run(bash)

    assert run.status == 0, run.output
    _assert_cleaned_up(run)
    api, web = run.ports
    assert api != web
    assert not {api, web} & {8000, 5173}


@pytest.mark.parametrize("bash", BASHES)
def test_e2e_hands_playwright_the_run_and_quoted_arguments(
    e2e: Fixture, bash: str
) -> None:
    run = e2e.run(bash, "--grep", "a to-do", "--trace=on")

    assert run.status == 0, run.output
    recorded = run.playwright
    assert recorded is not None
    assert recorded["args"] == ["--grep", "a to-do", "--trace=on"]
    env = recorded["env"]
    assert isinstance(env, dict)
    api, web = run.ports
    assert env["E2E_DATABASE_URL"] == f"sqlite+aiosqlite:///{run.tmp}/e2e.db"
    assert run.tmp.is_absolute()
    assert (env["E2E_API_PORT"], env["E2E_WEB_PORT"]) == (str(api), str(web))
    assert env["JUST"] == FAKE_JUST


@pytest.mark.parametrize("bash", BASHES)
def test_e2e_replaces_hostile_settings_and_outranks_a_dotenv_file(
    e2e: Fixture, bash: str, tmp_path: Path
) -> None:
    # A dotenv file may only name Settings fields (Settings forbids extras).
    dotenv = tmp_path / "scratch.env"
    dotenv.write_text(
        "".join(
            f"{name}={HOSTILE[name]}\n"
            for name in ("MY_APP_DATABASE_URL", *E2E_SETTINGS)
        ),
        encoding="utf-8",
    )

    run = e2e.run(bash, **HOSTILE)

    assert run.status == 0, run.output
    recorded = run.playwright
    assert recorded is not None
    env = recorded["env"]
    assert isinstance(env, dict)
    database_url = f"sqlite+aiosqlite:///{run.tmp}/e2e.db"
    assert {k: v for k, v in env.items() if k.startswith("MY_APP_")} == {
        "MY_APP_DATABASE_URL": database_url,
        **E2E_SETTINGS,
    }
    # Settings, built under that environment with a hostile dotenv file,
    # takes every field from the environment.
    probe = subprocess.run(  # noqa: S603 -- fixed argv, this interpreter
        [sys.executable, "-c", SETTINGS_PROBE, str(dotenv)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    settings = json.loads(probe.stdout)
    assert {f"MY_APP_{field.upper()}" for field in settings["fields"]} == {
        name for name in env if name.startswith("MY_APP_")
    }
    assert settings["values"] == {
        "database_url": database_url,
        "cors_origins": [],
        "log_level": "INFO",
        "log_format": "text",
    }


@pytest.mark.parametrize("bash", BASHES)
@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param("exit:1", id="browser-failure"),
        pytest.param("exit:3", id="startup-failure"),
    ],
)
def test_e2e_failed_run_keeps_its_status_and_cleans_up(
    e2e: Fixture, bash: str, outcome: str
) -> None:
    run = e2e.run(bash, FAKE_PLAYWRIGHT=outcome)

    assert run.status == int(outcome.removeprefix("exit:")), run.output
    _assert_cleaned_up(run)


@pytest.mark.parametrize("bash", BASHES)
def test_e2e_failed_typecheck_skips_playwright_and_cleans_up(
    e2e: Fixture, bash: str
) -> None:
    run = e2e.run(bash, FAKE_TYPECHECK_EXIT="2")

    assert run.status == 2, run.output
    assert run.playwright is None
    _assert_cleaned_up(run)


@pytest.mark.parametrize("bash", BASHES)
@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        pytest.param("leak:0", 1, id="passing-run-fails"),
        pytest.param("leak:4", 4, id="failing-run-keeps-its-status"),
    ],
)
def test_e2e_listener_left_behind_is_named_not_killed(
    e2e: Fixture, bash: str, outcome: str, status: int
) -> None:
    run = e2e.run(bash, FAKE_PLAYWRIGHT=outcome)

    assert run.status == status, run.output
    api, web = run.ports
    assert f"something still listens on {api}" in run.output
    assert f"nothing listening on {web}" in run.output
    assert not run.tmp.exists()
    assert _listening(api), "the recipe stopped a listener it did not start"


@pytest.mark.parametrize("bash", BASHES)
@pytest.mark.parametrize(
    ("signum", "status"),
    [
        pytest.param(signal.SIGINT, 130, id="int"),
        pytest.param(signal.SIGTERM, 143, id="term"),
        pytest.param(signal.SIGHUP, 129, id="hup"),
    ],
)
def test_e2e_interrupt_reaches_playwright_as_sigint_and_cleans_up(
    e2e: Fixture, bash: str, signum: signal.Signals, status: int
) -> None:
    process = e2e.popen(bash, FAKE_PLAYWRIGHT="hang")
    assert process.stdout is not None
    lines: list[str] = []
    deadline = time.monotonic() + READY_TIMEOUT
    while "ready\n" not in lines:
        assert time.monotonic() < deadline, "".join(lines)
        line = process.stdout.readline()
        assert line, f"the recipe ended early: {''.join(lines)}"
        lines.append(line)

    process.send_signal(signum)
    output, _ = process.communicate(timeout=RUN_TIMEOUT)

    run = Run(process.returncode, "".join(lines) + output, e2e.record)
    assert run.status == status, run.output
    signals = (e2e.record / "signals").read_text(encoding="utf-8").split()
    assert signals == ["INT"]
    _assert_cleaned_up(run)


@pytest.mark.parametrize("bash", BASHES)
@pytest.mark.parametrize("port", ["8000", "5173", "0", "70000", "x1"])
def test_e2e_refuses_a_developer_or_invalid_port(
    e2e: Fixture, bash: str, port: str
) -> None:
    run = e2e.run(bash, E2E_API_PORT=port)

    assert run.status == 1, run.output
    assert "error: e2e port" in run.output
    assert run.playwright is None


@pytest.mark.parametrize("bash", BASHES)
def test_e2e_refuses_a_taken_port_and_starts_nothing(e2e: Fixture, bash: str) -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = str(taken.getsockname()[1])

        run = e2e.run(bash, E2E_WEB_PORT=port)

    assert run.status == 1, run.output
    assert f"port {port} is taken" in run.output
    assert run.playwright is None


@pytest.mark.parametrize("bash", BASHES)
def test_e2e_refuses_one_port_for_both_servers(e2e: Fixture, bash: str) -> None:
    port = str(_free_port())

    run = e2e.run(bash, E2E_API_PORT=port, E2E_WEB_PORT=port)

    assert run.status == 1, run.output
    assert "two ports" in run.output
    assert run.playwright is None
