"""Tests for the justfile's ``dev`` recipe: the API and the screen as one pair.

The recipe body is read from the justfile and run with bash, so CI needs no
``just``. A fake ``just`` stands in for ``just backend dev`` and
``just frontend dev``: it starts a ``sleep`` of its own (the stand-in for
uvicorn or Vite, a process the recipe never started itself), prints
``ready <module> <recipe> <pid> <child pid>``, and waits. With
``FAKE_BACKEND_EXIT`` or ``FAKE_FRONTEND_EXIT`` set, that module's fake exits
with the code on ``SIGUSR1``, so a test decides when a server "fails".
With ``FAKE_STUBBORN`` set, the fake and its ``sleep`` ignore ``SIGTERM``, as a
server stuck in its shutdown would.

Each body runs under every bash on the host that the tests can find: the one on
``PATH`` and ``/bin/bash``, which is bash 3.2 on macOS.

The ``backend`` module's ``dev`` line runs with a fake ``uv`` that records its
argv, as ``tests/test_just_database.py`` runs the database recipes.
"""

from __future__ import annotations

import contextlib
import os
import selectors
import shlex
import shutil
import signal
import subprocess
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    type StartDev = Callable[..., Dev]

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"
BACKEND_JUSTFILE = REPO_ROOT / "backend" / "justfile"
JUST = "{{ quote(just_executable()) }}"
READY_TIMEOUT = 10.0
EXIT_TIMEOUT = 20.0

FAKE_JUST = """\
#!/usr/bin/env bash
case "$1" in
  backend) code=${FAKE_BACKEND_EXIT:-} ;;
  *) code=${FAKE_FRONTEND_EXIT:-} ;;
esac
if [ -n "${FAKE_STUBBORN:-}" ]; then trap '' TERM; fi
sleep 300 >/dev/null 2>&1 &
child=$!
if [ -n "$code" ]; then trap 'exit "$code"' USR1; fi
echo "ready $1 $2 $$ $child"
wait "$child"
"""


def _bashes() -> list[str]:
    found = [shutil.which("bash"), "/bin/bash"]
    paths = {str(Path(p).resolve()) for p in found if p and Path(p).is_file()}
    return sorted(paths)


BASHES = [pytest.param(path, id=path) for path in _bashes()]


def _recipe_body(justfile: Path, header: str) -> str:
    lines = justfile.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header)) + 1
    body: list[str] = []
    for line in lines[start:]:
        if not line.startswith("    "):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)) + "\n"


def _alive(pid: int) -> bool:
    """Whether ``pid`` runs; a zombie (exited, not yet reaped) does not.

    Where PID 1 does not reap orphans (a container without an init), a stopped
    grandchild stays a zombie that still answers ``kill -0``.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = subprocess.run(  # noqa: S603 -- a fixed ps argv, no shell
        ["ps", "-o", "stat=", "-p", str(pid)],  # noqa: S607 -- ps from PATH, as the recipe runs it
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


@dataclass
class Server:
    module: str
    recipe: str
    pid: int
    child: int


@dataclass
class Dev:
    process: subprocess.Popen[bytes]
    servers: dict[str, Server]

    def finish(self) -> int:
        return self.process.wait(timeout=EXIT_TIMEOUT)

    def pids(self) -> list[int]:
        return [pid for s in self.servers.values() for pid in (s.pid, s.child)]


def _await_servers(process: subprocess.Popen[bytes]) -> dict[str, Server]:
    assert process.stdout is not None
    servers: dict[str, Server] = {}
    buffer = b""
    deadline = time.monotonic() + READY_TIMEOUT
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while len(servers) < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                pytest.fail(f"the fake servers never got ready: {buffer!r}")
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                pytest.fail(f"the recipe closed its output early: {buffer!r}")
            buffer += chunk
            *lines, rest = buffer.split(b"\n")
            for line in lines:
                _, module, recipe, pid, child = line.decode().split()
                servers[module] = Server(module, recipe, int(pid), int(child))
            buffer = rest
    return servers


@pytest.fixture
def start_dev(tmp_path: Path) -> Iterator[StartDev]:
    fake = tmp_path / "just"
    fake.write_text(FAKE_JUST, encoding="utf-8")
    fake.chmod(0o755)
    script = tmp_path / "dev.sh"
    script.write_text(
        _recipe_body(JUSTFILE, "dev:").replace(JUST, shlex.quote(str(fake))),
        encoding="utf-8",
    )
    started: list[Dev] = []

    def start(bash: str, **env: str) -> Dev:
        environ = {
            k: v
            for k, v in os.environ.items()
            if k not in {"FAKE_BACKEND_EXIT", "FAKE_FRONTEND_EXIT", "FAKE_STUBBORN"}
        }
        process = subprocess.Popen(  # noqa: S603 -- fixed argv, no shell
            [bash, str(script)],
            cwd=tmp_path,
            env=environ | env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            process_group=0,
        )
        dev = Dev(process, {})
        started.append(dev)
        dev.servers = _await_servers(process)
        return dev

    yield start

    # A failing test leaks nothing: each fake leads a process group of its own.
    for dev in started:
        for server in dev.servers.values():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(server.pid, signal.SIGKILL)
        if dev.process.poll() is None:
            dev.process.kill()
        dev.process.wait(timeout=EXIT_TIMEOUT)
        if dev.process.stdout is not None:
            dev.process.stdout.close()


@pytest.mark.parametrize("bash", BASHES)
def test_dev_starts_backend_dev_and_frontend_dev(
    start_dev: StartDev, bash: str
) -> None:
    dev = start_dev(bash)

    assert {(s.module, s.recipe) for s in dev.servers.values()} == {
        ("backend", "dev"),
        ("frontend", "dev"),
    }
    assert all(_alive(pid) for pid in dev.pids())


@pytest.mark.parametrize("bash", BASHES)
@pytest.mark.parametrize(
    ("signum", "status"),
    [
        pytest.param(signal.SIGINT, 130, id="int"),
        pytest.param(signal.SIGTERM, 143, id="term"),
        pytest.param(signal.SIGHUP, 129, id="hup"),
    ],
)
def test_dev_signal_stops_both_servers_and_their_children(
    start_dev: StartDev, bash: str, signum: signal.Signals, status: int
) -> None:
    dev = start_dev(bash)

    dev.process.send_signal(signum)

    assert dev.finish() == status
    assert [pid for pid in dev.pids() if _alive(pid)] == []


@pytest.mark.parametrize("bash", BASHES)
def test_dev_signal_kills_servers_that_ignore_sigterm(
    start_dev: StartDev, bash: str
) -> None:
    dev = start_dev(bash, FAKE_STUBBORN="1")

    dev.process.send_signal(signal.SIGTERM)

    assert dev.finish() == 143
    assert [pid for pid in dev.pids() if _alive(pid)] == []


@pytest.mark.parametrize("bash", BASHES)
@pytest.mark.parametrize(
    ("failing", "other"),
    [
        pytest.param("backend", "frontend", id="api-exits"),
        pytest.param("frontend", "backend", id="screen-exits"),
    ],
)
def test_dev_one_server_exits_stops_the_other_with_its_status(
    start_dev: StartDev, bash: str, failing: str, other: str
) -> None:
    dev = start_dev(bash, **{f"FAKE_{failing.upper()}_EXIT": "3"})

    os.kill(dev.servers[failing].pid, signal.SIGUSR1)

    assert dev.finish() == 3
    survivors = [pid for pid in dev.pids() if _alive(pid)]
    assert survivors == [], f"{other} or a child outlived the {failing} exit"


@pytest.mark.parametrize(
    ("env", "port"),
    [
        pytest.param({}, "8000", id="default"),
        pytest.param({"MY_APP_API_PORT": "51001"}, "51001", id="override"),
    ],
)
def test_backend_dev_serves_on_loopback_api_port(
    tmp_path: Path, env: dict[str, str], port: str
) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "uv"
    fake.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_RECORD"\n', encoding="utf-8"
    )
    fake.chmod(0o755)
    record = tmp_path / "calls.txt"
    command = (
        _recipe_body(BACKEND_JUSTFILE, "dev ")
        .strip()
        .replace("{{ quote(url) }}", shlex.quote("sqlite+aiosqlite:///./var/dev.db"))
    )
    environ = {k: v for k, v in os.environ.items() if k != "MY_APP_API_PORT"}

    result = subprocess.run(  # noqa: S603 -- fixed shell argv, repository recipe line
        ["sh", "-cu", command],  # noqa: S607 -- sh from PATH, as just runs each line
        cwd=tmp_path,
        env=environ
        | env
        | {
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_RECORD": str(record),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    args = record.read_text(encoding="utf-8").splitlines()
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("--port") + 1] == port
