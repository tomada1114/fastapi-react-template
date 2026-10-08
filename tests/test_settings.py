from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from my_app.settings import DEFAULT_LLM_MODEL, Settings


def test_settings_database_url_unset_selects_in_memory_store():
    settings = Settings()

    assert settings.database_url is None
    assert settings.sqlite_path is None


@pytest.mark.parametrize(
    ("url", "expected_path"),
    [
        pytest.param("sqlite:///todos.db", Path("todos.db"), id="relative"),
        pytest.param(
            "sqlite:////var/lib/todos.db", Path("/var/lib/todos.db"), id="absolute"
        ),
    ],
)
def test_settings_database_url_from_env_selects_sqlite_path(
    monkeypatch, url, expected_path
):
    monkeypatch.setenv("MY_APP_DATABASE_URL", url)

    settings = Settings()

    assert settings.database_url == url
    assert settings.sqlite_path == expected_path


def test_settings_unprefixed_env_var_is_ignored(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///other.db")

    assert Settings().database_url is None


def test_settings_database_url_empty_counts_as_unset(monkeypatch):
    monkeypatch.setenv("MY_APP_DATABASE_URL", "")

    settings = Settings()

    assert settings.database_url is None
    assert settings.sqlite_path is None


@pytest.mark.parametrize(
    ("url", "pattern"),
    [
        pytest.param(
            "postgresql://localhost/todos",
            r"must look like 'sqlite:///<path>'",
            id="other-scheme",
        ),
        pytest.param("sqlite:///", r"must look like 'sqlite:///<path>'", id="no-path"),
        pytest.param(
            "sqlite:///:memory:",
            r"new connection per call, so an in-memory SQLite database would be empty",
            id="sqlite-memory",
        ),
        pytest.param(
            "sqlite:///var/data/", r"must name a file, not a directory", id="directory"
        ),
    ],
)
def test_settings_unsupported_database_url_raises_validation_error(
    monkeypatch, url, pattern
):
    monkeypatch.setenv("MY_APP_DATABASE_URL", url)

    with pytest.raises(ValidationError, match=pattern):
        Settings()


def test_settings_llm_unset_keeps_the_key_none_and_the_default_model():
    settings = Settings()

    assert settings.openrouter_api_key is None
    assert settings.llm_model == DEFAULT_LLM_MODEL


def test_settings_default_llm_model_is_deepseek_v4_1_flash():
    assert DEFAULT_LLM_MODEL == "deepseek/deepseek-v4.1-flash"


def test_settings_openrouter_api_key_from_env_is_a_stripped_secret(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "  sk-or-test-value \n")

    settings = Settings()

    assert isinstance(settings.openrouter_api_key, SecretStr)
    assert settings.openrouter_api_key.get_secret_value() == "sk-or-test-value"
    assert "sk-or-test-value" not in repr(settings)
    assert "sk-or-test-value" not in str(settings)


@pytest.mark.parametrize(
    "value", [pytest.param("", id="empty"), pytest.param("  ", id="whitespace")]
)
def test_settings_blank_openrouter_api_key_counts_as_unset(monkeypatch, value):
    monkeypatch.setenv("OPENROUTER_API_KEY", value)

    assert Settings().openrouter_api_key is None


def test_settings_prefixed_openrouter_api_key_is_not_read(monkeypatch):
    monkeypatch.setenv("MY_APP_OPENROUTER_API_KEY", "sk-or-test-value")

    assert Settings().openrouter_api_key is None


def test_settings_openrouter_api_key_by_field_name_is_accepted():
    settings = Settings.model_validate({"openrouter_api_key": "  k  "})

    assert settings.openrouter_api_key is not None
    assert settings.openrouter_api_key.get_secret_value() == "k"


def test_settings_openrouter_api_key_as_secret_str_is_stripped():
    settings = Settings(openrouter_api_key=SecretStr("  k  "))

    assert settings.openrouter_api_key is not None
    assert settings.openrouter_api_key.get_secret_value() == "k"


def test_settings_llm_model_from_prefixed_env_is_used(monkeypatch):
    monkeypatch.setenv("MY_APP_LLM_MODEL", " anthropic/claude-test ")

    assert Settings().llm_model == "anthropic/claude-test"


@pytest.mark.parametrize(
    "value", [pytest.param("", id="empty"), pytest.param("  ", id="whitespace")]
)
def test_settings_blank_llm_model_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv("MY_APP_LLM_MODEL", value)

    assert Settings().llm_model == DEFAULT_LLM_MODEL


def test_settings_unprefixed_llm_model_is_ignored(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "other/model")

    assert Settings().llm_model == DEFAULT_LLM_MODEL
