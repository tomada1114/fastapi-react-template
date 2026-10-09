"""Tests for the justfile's ``worktree-prepare`` recipe.

Each recipe line is read from the justfile and run as just runs a linewise
recipe, ``sh -cu <line>`` in order from the recipe's directory, stopping at the
first non-zero exit, so CI needs no ``just``. Fake ``uv`` and ``pnpm`` on
``PATH`` append their argv to one record, which shows the order they ran in.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"

FAKE = """\
#!/usr/bin/env bash
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$FAKE_RECORD"
exit "${FAKE_EXIT:-0}"
"""


def _recipe_lines() -> list[str]:
    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    start = lines.index("worktree-prepare:") + 1
    body: list[str] = []
    for line in lines[start:]:
        if not line.startswith("    "):
            break
        body.append(line.strip())
    return body


def _run_recipe(cwd: Path, bindir: Path, record: Path, *, pnpm_exit: int = 0) -> int:
    environ = dict(os.environ)
    environ["PATH"] = f"{bindir}{os.pathsep}{environ['PATH']}"
    environ["FAKE_RECORD"] = str(record)
    for line in _recipe_lines():
        env = dict(environ)
        if "pnpm" in line:
            env["FAKE_EXIT"] = str(pnpm_exit)
        result = subprocess.run(  # noqa: S603 -- fixed argv, the recipe's own line
            ["sh", "-cu", line],  # noqa: S607 -- sh from PATH, as just runs a line
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return result.returncode
    return 0


@pytest.fixture
def bindir(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("uv", "pnpm"):
        fake = bindir / name
        fake.write_text(FAKE, encoding="utf-8")
        fake.chmod(0o755)
    return bindir


def test_worktree_prepare_without_pnpm_lockfile_runs_only_uv_sync(
    tmp_path: Path, bindir: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    record = tmp_path / "calls.txt"

    exit_code = _run_recipe(worktree, bindir, record)

    assert exit_code == 0
    assert record.read_text(encoding="utf-8").splitlines() == [
        "uv sync --all-groups --locked"
    ]


def test_worktree_prepare_with_pnpm_lockfile_installs_frozen_after_uv_sync(
    tmp_path: Path, bindir: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n", encoding="utf-8"
    )
    record = tmp_path / "calls.txt"

    exit_code = _run_recipe(worktree, bindir, record)

    assert exit_code == 0
    assert record.read_text(encoding="utf-8").splitlines() == [
        "uv sync --all-groups --locked",
        "pnpm install --frozen-lockfile",
    ]


def test_worktree_prepare_failed_pnpm_install_fails_the_recipe(
    tmp_path: Path, bindir: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n", encoding="utf-8"
    )
    record = tmp_path / "calls.txt"

    exit_code = _run_recipe(worktree, bindir, record, pnpm_exit=7)

    assert exit_code == 7
