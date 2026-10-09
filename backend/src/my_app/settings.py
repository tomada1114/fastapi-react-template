"""Runtime configuration read from ``MY_APP_``-prefixed environment variables."""

from __future__ import annotations

import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ENV_PREFIX = "MY_APP_"
SQLITE_URL_PREFIX = "sqlite+aiosqlite:///"
POSTGRESQL_URL_PREFIX = "postgresql+asyncpg://"
# The blocking driver's form, refused with a pointer to the async one.
SYNC_SQLITE_URL_PREFIX = "sqlite:///"
SQLITE_MEMORY_PATH = ":memory:"
CORS_ORIGIN_PATTERN = re.compile(r"^https?://[^/\s]+$")


class Settings(BaseSettings):
    """Configuration shared by every entry point.

    Pydantic belongs here because this is a deserialization boundary: strings
    from the environment become typed, validated values before the
    composition root sees them.

    Attributes:
        database_url: A SQLAlchemy URL for an async driver —
            ``sqlite+aiosqlite:///<path>`` for a SQLite file or
            ``postgresql+asyncpg://...`` for a PostgreSQL server — selects the
            SQL repository; unset (or set to an empty string) keeps to-dos in
            memory for the life of the process. Read from
            ``MY_APP_DATABASE_URL``. The database must already be migrated
            (``just backend db-upgrade``): the app never creates its schema.
        cors_origins: Exact HTTP(S) origins allowed to call the API, from
            comma-separated ``MY_APP_CORS_ORIGINS``; empty disables CORS.
    """

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    database_url: str | None = None
    cors_origins: Annotated[list[str], NoDecode] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        """Accept exact browser origins, with blanks meaning CORS is disabled.

        Raises:
            ValueError: If an item has no HTTP scheme or includes a path.
        """
        items = value.split(",") if isinstance(value, str) else value
        origins: list[str] = []
        for item in items:
            origin = item.strip()
            if not origin:
                continue
            if not _is_browser_origin(origin):
                msg = f"invalid CORS origin {origin!r}: use http(s)://host[:port] without a path"
                raise ValueError(msg)
            if origin not in origins:
                origins.append(origin)
        return origins

    @field_validator("database_url")
    @classmethod
    def _require_async_database_url(cls, value: str | None) -> str | None:
        """Reject any URL the SQL repository could not open.

        String rules only, so this module imports no database library. Failing
        here, at startup, beats failing on the first request. An empty value
        counts as unset: ``MY_APP_DATABASE_URL=`` in a shell or an env file
        usually means "no database", not a malformed one.

        Raises:
            ValueError: If the URL names no supported async driver, or a
                SQLite target that is not a file.
        """
        if not value:
            return None
        if value.startswith(SQLITE_URL_PREFIX):
            _check_sqlite_path(value, value.removeprefix(SQLITE_URL_PREFIX))
        elif value.startswith(POSTGRESQL_URL_PREFIX):
            if value == POSTGRESQL_URL_PREFIX:
                msg = (
                    f"must name a server after '{POSTGRESQL_URL_PREFIX}', got {value!r}"
                )
                raise ValueError(msg)
        elif value.startswith(SYNC_SQLITE_URL_PREFIX):
            msg = (
                f"{value!r} names the blocking sqlite driver; use "
                f"'{SQLITE_URL_PREFIX}<path>' instead"
            )
            raise ValueError(msg)
        else:
            msg = (
                f"must start with '{SQLITE_URL_PREFIX}' or "
                f"'{POSTGRESQL_URL_PREFIX}', got {value!r}"
            )
            raise ValueError(msg)
        return value


def _check_sqlite_path(url: str, path: str) -> None:
    """Refuse a SQLite target that is not a file the pool can share.

    Raises:
        ValueError: If ``path`` is empty, the in-memory database, or a
            directory.
    """
    if not path:
        msg = f"must name a file after '{SQLITE_URL_PREFIX}', got {url!r}"
        raise ValueError(msg)
    if path == SQLITE_MEMORY_PATH:
        msg = (
            f"{url!r} is not supported: each pooled connection would open its "
            "own empty database. Unset the variable to use the in-memory store."
        )
        raise ValueError(msg)
    if path.endswith("/"):
        msg = f"must name a file, not a directory, got {url!r}"
        raise ValueError(msg)


def _is_browser_origin(origin: str) -> bool:
    """Reject origin strings a browser cannot send in its Origin header."""
    if CORS_ORIGIN_PATTERN.fullmatch(origin) is None or "*" in origin or "\\" in origin:
        return False
    try:
        parsed = urlsplit(origin)
        # Access validates both the port range and its numeric spelling.
        _ = parsed.port
    except ValueError:
        return False
    return bool(parsed.hostname) and not (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.netloc.endswith(":")
    )
