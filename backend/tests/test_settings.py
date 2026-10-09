from __future__ import annotations

import pytest
from pydantic import ValidationError

from my_app.settings import Settings


def test_settings_database_url_unset_selects_in_memory_store():
    assert Settings().database_url is None


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("sqlite+aiosqlite:///todos.db", id="sqlite-relative"),
        pytest.param("sqlite+aiosqlite:///./var/dev.db", id="sqlite-dot-relative"),
        pytest.param("sqlite+aiosqlite:////var/lib/todos.db", id="sqlite-absolute"),
        pytest.param(
            "postgresql+asyncpg://app:secret@localhost:5432/todos", id="postgresql"
        ),
    ],
)
def test_settings_supported_database_url_from_env_is_kept_as_given(monkeypatch, url):
    monkeypatch.setenv("MY_APP_DATABASE_URL", url)

    assert Settings().database_url == url


def test_settings_unprefixed_env_var_is_ignored(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///other.db")

    assert Settings().database_url is None


def test_settings_database_url_empty_counts_as_unset(monkeypatch):
    monkeypatch.setenv("MY_APP_DATABASE_URL", "")

    assert Settings().database_url is None


@pytest.mark.parametrize(
    ("url", "pattern"),
    [
        pytest.param(
            "sqlite:///todos.db",
            r"blocking sqlite driver; use 'sqlite\+aiosqlite:///<path>' instead",
            id="sync-sqlite",
        ),
        pytest.param(
            "postgresql://localhost/todos",
            r"must start with 'sqlite\+aiosqlite:///' or 'postgresql\+asyncpg://'",
            id="sync-postgresql",
        ),
        pytest.param(
            "mysql+aiomysql://localhost/todos",
            r"must start with 'sqlite\+aiosqlite:///' or 'postgresql\+asyncpg://'",
            id="other-scheme",
        ),
        pytest.param(
            "todos.db",
            r"must start with 'sqlite\+aiosqlite:///' or 'postgresql\+asyncpg://'",
            id="bare-path",
        ),
        pytest.param(
            "sqlite+aiosqlite:///",
            r"must name a file after 'sqlite\+aiosqlite:///'",
            id="sqlite-no-path",
        ),
        pytest.param(
            "sqlite+aiosqlite:///:memory:",
            r"each pooled connection would open its own empty database",
            id="sqlite-memory",
        ),
        pytest.param(
            "sqlite+aiosqlite:///var/data/",
            r"must name a file, not a directory",
            id="sqlite-directory",
        ),
        pytest.param(
            "postgresql+asyncpg://",
            r"must name a server after 'postgresql\+asyncpg://'",
            id="postgresql-no-server",
        ),
    ],
)
def test_settings_unsupported_database_url_raises_validation_error(
    monkeypatch, url, pattern
):
    monkeypatch.setenv("MY_APP_DATABASE_URL", url)

    with pytest.raises(ValidationError, match=pattern):
        Settings()
