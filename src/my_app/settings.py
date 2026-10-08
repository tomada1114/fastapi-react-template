"""Runtime configuration read from ``MY_APP_``-prefixed environment variables.

The one exception is ``OPENROUTER_API_KEY``, read unprefixed (see ``Settings``).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "MY_APP_"
SQLITE_URL_PREFIX = "sqlite:///"
SQLITE_MEMORY_PATH = ":memory:"
# The model a call that names none is sent to; the integrating-llm skill cites
# where it was found in OpenRouter's catalogue.
DEFAULT_LLM_MODEL = "deepseek/deepseek-v4.1-flash"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"


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
        openrouter_api_key: The OpenRouter API key; unset (or blank) keeps the
            LLM closed. Read from ``OPENROUTER_API_KEY``, unprefixed, the name
            OpenRouter's own documentation and the sibling templates use;
            ``MY_APP_OPENROUTER_API_KEY`` is not read. A ``SecretStr`` keeps it
            out of ``repr`` and logs.
        llm_model: The OpenRouter model id a call that names none is sent to;
            unset (or blank) means ``DEFAULT_LLM_MODEL``. Not validated
            further: OpenRouter's catalogue is the authority. Read from
            ``MY_APP_LLM_MODEL``.
    """

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    database_url: str | None = None
    # pydantic-settings does not apply env_prefix to an aliased field, which is
    # what keeps the key unprefixed; the field name stays usable in code.
    openrouter_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(OPENROUTER_API_KEY_ENV, "openrouter_api_key"),
    )
    llm_model: str = DEFAULT_LLM_MODEL

    @field_validator("openrouter_api_key", mode="before")
    @classmethod
    def _blank_key_is_unset(cls, value: object) -> object:
        """Strip the key, and treat an empty one as unset.

        ``OPENROUTER_API_KEY=`` in a shell or an env file means "no key", and
        it must keep the LLM closed rather than send an empty bearer token.
        """
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("llm_model")
    @classmethod
    def _blank_model_is_the_default(cls, value: str) -> str:
        """Strip the model id, and fall back to the default when it is blank."""
        return value.strip() or DEFAULT_LLM_MODEL

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
