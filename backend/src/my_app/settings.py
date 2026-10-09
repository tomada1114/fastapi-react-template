"""Runtime configuration read from ``MY_APP_``-prefixed environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "MY_APP_"
SQLITE_URL_PREFIX = "sqlite:///"
SQLITE_MEMORY_PATH = ":memory:"


class Settings(BaseSettings):
    """Configuration shared by every entry point.

    Pydantic belongs here because this is a deserialization boundary: strings
    from the environment become typed, validated values before the
    composition root sees them.

    Attributes:
        database_url: ``sqlite:///<path>`` selects the SQLite repository at
            that file; unset (or set to an empty string) keeps to-dos in
            memory for the life of the process. Read from
            ``MY_APP_DATABASE_URL``.
    """

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    database_url: str | None = None

    @field_validator("database_url")
    @classmethod
    def _require_sqlite_file_url(cls, value: str | None) -> str | None:
        """Reject any URL the SQLite repository could not use as a file.

        Failing here, at startup, beats failing on the first request. An empty
        value counts as unset: ``MY_APP_DATABASE_URL=`` in a shell or an env
        file usually means "no database", not a malformed one.

        Raises:
            ValueError: If the URL is not ``sqlite:///<file path>``.
        """
        if not value:
            return None
        path = value.removeprefix(SQLITE_URL_PREFIX)
        if path == value or not path:
            msg = f"must look like '{SQLITE_URL_PREFIX}<path>', got {value!r}"
            raise ValueError(msg)
        if path == SQLITE_MEMORY_PATH:
            msg = (
                f"{value!r} is not supported: the repository opens a new "
                "connection per call, so an in-memory SQLite database would be "
                "empty every time. Unset the variable to use the in-memory store."
            )
            raise ValueError(msg)
        if path.endswith("/"):
            msg = f"must name a file, not a directory, got {value!r}"
            raise ValueError(msg)
        return value

    @property
    def sqlite_path(self) -> Path | None:
        """The SQLite file ``database_url`` names, or None for the in-memory store.

        ``sqlite:///app.db`` is relative to the working directory and
        ``sqlite:////var/lib/app.db`` is absolute, as in SQLAlchemy's URLs.
        """
        if self.database_url is None:
            return None
        return Path(self.database_url.removeprefix(SQLITE_URL_PREFIX))
