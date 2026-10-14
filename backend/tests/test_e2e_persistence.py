"""e2e/verify_persistence.py, the browser test's independent persistence check.

The Playwright spec runs it as a process of its own on the run's SQLite file,
after the screen has created and completed a to-do. These tests run it the same
way, against migrated scratch files, so a check that passed on a to-do the API
only kept in memory, or on another database, fails here.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest
from sqlalchemy import event

from my_app import composition
from my_app.adapters.sql.engine import make_engine
from my_app.settings import ENV_PREFIX, Settings
from tests.settings_env import without_settings_env

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable
    from types import ModuleType

    from my_app.composition import Container
    from my_app.core.models import Todo

E2E = Path(__file__).resolve().parents[2] / "e2e"
VERIFIER = E2E / "verify_persistence.py"
ENVIRONMENT_TS = E2E / "environment.ts"
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
TITLE = "Buy milk (e2e)"
E2E_VALUES = {
    "cors_origins": [],
    "log_level": "INFO",
    "log_format": "text",
}

pytestmark = pytest.mark.anyio


@pytest.fixture
def verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_persistence", VERIFIER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _verify(
    database_url: str, todo_id: object, title: str = TITLE, **env: str
) -> subprocess.CompletedProcess[bytes]:
    return await anyio.run_process(
        [sys.executable, str(VERIFIER), database_url, str(todo_id), title],
        check=False,
        env=without_settings_env(os.environ) | env,
    )


async def _stored(
    make_container: Callable[[Settings], Container],
    database_url: str | None,
    *,
    complete: bool,
) -> Todo:
    container = make_container(Settings(database_url=database_url))
    todo = await container.todos.create(TITLE)
    if complete:
        await container.todos.complete(todo.id)
    await container.aclose()
    return todo


async def test_verifier_completed_todo_in_the_file_passes(
    make_container, migrated_sqlite_url
):
    todo = await _stored(make_container, migrated_sqlite_url, complete=True)

    result = await _verify(migrated_sqlite_url, todo.id)

    assert result.returncode == 0, result.stderr
    assert f"to-do {todo.id} is stored, completed" in result.stdout.decode()


async def test_verifier_todo_the_api_kept_in_memory_fails(
    make_container, migrated_sqlite_url
):
    # The API pointed at the in-memory store: the screen sees the to-do, and
    # survives nothing but a reload; the database file stays empty.
    todo = await _stored(make_container, None, complete=True)

    result = await _verify(migrated_sqlite_url, todo.id)

    assert result.returncode == 1
    assert f"no to-do {todo.id} is stored" in result.stderr.decode()


async def test_verifier_open_todo_fails(make_container, migrated_sqlite_url):
    todo = await _stored(make_container, migrated_sqlite_url, complete=False)

    result = await _verify(migrated_sqlite_url, todo.id)

    assert result.returncode == 1
    assert "but not completed" in result.stderr.decode()


async def test_verifier_other_title_fails(make_container, migrated_sqlite_url):
    todo = await _stored(make_container, migrated_sqlite_url, complete=True)

    result = await _verify(migrated_sqlite_url, todo.id, title="Buy bread (e2e)")

    assert result.returncode == 1
    assert f"with title {TITLE!r}" in result.stderr.decode()


async def test_verifier_ignores_an_inherited_database_url(
    make_container, migrated_sqlite_url, tmp_path
):
    # The inherited variable names a database that holds the to-do; the run's
    # own, given as an argument, does not.
    todo = await _stored(make_container, migrated_sqlite_url, complete=True)
    empty = f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}"
    await anyio.run_process(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        env=without_settings_env(os.environ)
        | {
            f"{ENV_PREFIX}DATABASE_URL": empty,
            f"{ENV_PREFIX}CORS_ORIGINS": "",
            f"{ENV_PREFIX}LOG_LEVEL": "INFO",
            f"{ENV_PREFIX}LOG_FORMAT": "text",
        },
    )

    result = await _verify(empty, todo.id, MY_APP_DATABASE_URL=migrated_sqlite_url)

    assert result.returncode == 1
    assert f"no to-do {todo.id} is stored" in result.stderr.decode()


async def test_verifier_missing_file_fails_without_creating_it(tmp_path):
    missing = tmp_path / "missing.db"

    result = await _verify(f"sqlite+aiosqlite:///{missing}", "0" * 32)

    assert result.returncode == 1
    assert "no database file" in result.stderr.decode()
    assert not missing.exists()


async def test_verifier_other_database_url_is_a_usage_error():
    result = await _verify("postgresql+asyncpg://localhost/x", "0" * 32)

    assert result.returncode == 2
    assert "not a SQLite URL" in result.stderr.decode()


async def test_verifier_find_todo_closes_its_engine(
    verifier, make_container, migrated_sqlite_url, monkeypatch
):
    todo = await _stored(make_container, migrated_sqlite_url, complete=True)
    opened, disposed = [], []

    def recording_make_engine(url):
        engine = make_engine(url)
        opened.append(engine)
        event.listen(
            engine.sync_engine, "engine_disposed", lambda _: disposed.append(engine)
        )
        return engine

    monkeypatch.setattr(composition, "make_engine", recording_make_engine)

    found = await verifier.find_todo(
        verifier.isolated_settings(migrated_sqlite_url), todo.id
    )

    assert found is not None
    assert (found.id, found.title, found.is_completed) == (todo.id, TITLE, True)
    assert len(opened) == 1
    assert disposed == opened


def test_verifier_settings_outrank_environment_and_dotenv(
    verifier, monkeypatch, tmp_path
):
    hostile = {
        "DATABASE_URL": "sqlite+aiosqlite:////hostile/dev.db",
        "CORS_ORIGINS": "https://hostile.example",
        "LOG_LEVEL": "DEBUG",
        "LOG_FORMAT": "json",
    }
    dotenv = tmp_path / "scratch.env"
    dotenv.write_text(
        "".join(f"{ENV_PREFIX}{k}={v}\n" for k, v in hostile.items()), encoding="utf-8"
    )
    # As if backend/.env held the hostile values, without touching that file.
    monkeypatch.setitem(Settings.model_config, "env_file", dotenv)
    assert Settings().log_format == "json"
    for name, value in hostile.items():
        monkeypatch.setenv(f"{ENV_PREFIX}{name}", value)
    url = f"sqlite+aiosqlite:///{tmp_path / 'e2e.db'}"

    settings = verifier.isolated_settings(url)

    assert settings.model_dump() == {"database_url": url, **E2E_VALUES}


def test_verifier_settings_set_every_settings_field(verifier, tmp_path):
    settings = verifier.isolated_settings(f"sqlite+aiosqlite:///{tmp_path / 'e2e.db'}")

    assert settings.model_fields_set == set(Settings.model_fields)


def test_e2e_settings_environment_names_every_settings_field():
    # environment.ts gives the API and this check every Settings field
    # explicitly; one it left out could come from backend/.env.
    source = ENVIRONMENT_TS.read_text(encoding="utf-8")
    body = re.search(r"function settingsEnvironment\(.*?\n\}", source, re.DOTALL)
    assert body is not None

    names = set(re.findall(rf"\b({ENV_PREFIX}[A-Z_]+):", body[0]))

    assert names == {f"{ENV_PREFIX}{field.upper()}" for field in Settings.model_fields}
