"""Database recipe execution with a fake uv; no database or server is started."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("recipe", ["db-upgrade", "db-revision", "dev"])
@pytest.mark.parametrize("postgres", [False, True], ids=["sqlite", "postgres"])
def test_database_recipe_installs_driver_only_for_postgres(
    tmp_path: Path, recipe: str, postgres: bool
) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "uv"
    fake.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$FAKE_RECORD"\n'
        'case "$MY_APP_DATABASE_URL" in\n'
        '  postgresql+asyncpg:*) case " $* " in\n'
        '    *" --extra postgres "*) exit 0 ;;\n'
        '    *) echo "missing asyncpg" >&2; exit 3 ;;\n'
        "  esac ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    record = tmp_path / "calls.txt"
    lines = (REPO_ROOT / "backend/justfile").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{recipe} "))
    body = []
    for line in lines[start + 1 :]:
        if not line.startswith("    "):
            break
        if "uv run" in line:
            body.append(line.strip())
    assert len(body) == 1
    url = (
        "postgresql+asyncpg://localhost/my_app_test"
        if postgres
        else "sqlite+aiosqlite:///./var/dev.db"
    )
    command = (
        body[0]
        .replace("{{ quote(url) }}", shlex.quote(url))
        .replace("{{ quote(MESSAGE) }}", shlex.quote("test revision"))
    )
    result = subprocess.run(  # noqa: S603 -- fixed shell argv, repository recipe and fixture URL
        ["sh", "-cu", command],  # noqa: S607 -- sh from PATH, as just runs each line
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_RECORD": str(record),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    args = record.read_text(encoding="utf-8").splitlines()
    assert args[:2] == ["run", "--locked"]
    assert ("--extra" in args) is postgres
