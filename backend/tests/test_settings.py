from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import make_url
from sqlalchemy.dialects.sqlite.aiosqlite import SQLiteDialect_aiosqlite

import my_app
from my_app import composition
from my_app import settings as settings_module
from my_app.settings import Settings
from tests.settings_env import settings_from_env_file


@pytest.mark.parametrize("value", ["", "INFO", "info", "DEBUG", "warning", "ERROR"])
def test_settings_log_level_normalizes_or_defaults(monkeypatch, value):
    monkeypatch.setenv("MY_APP_LOG_LEVEL", value)
    assert Settings().log_level == (value.upper() or "INFO")


@pytest.mark.parametrize("value", ["", "text", "json"])
def test_settings_log_format_defaults_or_preserves(monkeypatch, value):
    monkeypatch.setenv("MY_APP_LOG_FORMAT", value)
    assert Settings().log_format == (value or "text")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MY_APP_LOG_LEVEL", "TRACE"),
        ("MY_APP_LOG_FORMAT", "xml"),
        ("MY_APP_LOG_FORMAT", "JSON"),
    ],
)
def test_settings_invalid_logging_value_fails(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


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


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("sqlite+aiosqlite:///:memory:?timeout=5", id="memory-options"),
        pytest.param("sqlite+aiosqlite:///%3Amemory%3A?timeout=5", id="encoded-memory"),
        pytest.param(
            "sqlite+aiosqlite:///file:review-memory?mode=memory&cache=shared&uri=true",
            id="uri-memory-mode",
        ),
        pytest.param(
            "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true",
            id="uri-memory-name",
        ),
        pytest.param(
            "sqlite+aiosqlite:///file:review%3Fmode=memory?uri=true",
            id="embedded-uri-query",
        ),
        pytest.param(
            "sqlite+aiosqlite:///file:%253Amemory%253A?uri=true", id="uri-double-escape"
        ),
        pytest.param(
            "sqlite+aiosqlite:///file:review?%6Dode=memory&uri=true",
            id="encoded-option-name",
        ),
        pytest.param(
            "sqlite+aiosqlite:///file:review?mode=memory%26cache%3Dshared&uri=true",
            id="decoded-uri-options",
        ),
        pytest.param(
            "sqlite+aiosqlite:///file:review?uri=false&uri=false&mode=memory",
            id="repeated-uri-flag",
        ),
        pytest.param("sqlite+aiosqlite:///?timeout=5", id="empty-options"),
        pytest.param(
            "sqlite+aiosqlite:////tmp/review-dir/?timeout=5", id="directory-options"
        ),
        pytest.param(
            "sqlite+aiosqlite:///relative%2F?timeout=5", id="encoded-directory"
        ),
        pytest.param("sqlite+aiosqlite:///file:?uri=true", id="empty-uri"),
        pytest.param(
            "sqlite+aiosqlite:///file:/tmp/review-dir/?uri=true&mode=rw",
            id="directory-uri",
        ),
    ],
)
def test_settings_effective_nonfile_sqlite_target_fails_before_engine_build(
    monkeypatch, url
):
    reached = []

    def forbid_engine(value):
        reached.append(value)
        message = "invalid Settings reached the engine builder"
        raise AssertionError(message)

    monkeypatch.setattr(composition, "make_engine", forbid_engine)
    with pytest.raises(ValidationError, match="database_url"):
        composition.build_container(Settings(database_url=url))
    assert reached == []


@pytest.mark.parametrize(
    "kind",
    [
        "relative",
        "absolute",
        "uri-relative",
        "uri-absolute",
        "literal-question",
        "uri-escape",
    ],
)
def test_settings_file_options_preserve_actual_driver_target(tmp_path, kind):
    absolute = str(tmp_path / "todos.db")
    cases = {
        "relative": (
            "relative.db?timeout=5",
            str(Path("relative.db").absolute()),
            False,
        ),
        "absolute": (f"{absolute}?timeout=5", absolute, False),
        "uri-relative": (
            "file:relative.db?mode=rwc&uri=true&timeout=5",
            "file:relative.db?mode=rwc",
            True,
        ),
        "uri-absolute": (
            f"file:{absolute}?mode=rwc&uri=1&timeout=5",
            f"file:{absolute}?mode=rwc",
            True,
        ),
        "literal-question": (
            "data%3Fname.db?timeout=5",
            str(Path("data?name.db").absolute()),
            False,
        ),
        "uri-escape": (
            "file:dir%2520name.db?uri=true&mode=rwc",
            "file:dir%20name.db?mode=rwc",
            True,
        ),
    }
    target, expected, uri = cases[kind]
    url = f"sqlite+aiosqlite:///{target}"

    settings = Settings(database_url=url)
    args, options = SQLiteDialect_aiosqlite().create_connect_args(make_url(url))

    assert settings.database_url == url
    assert args == [expected]
    assert options.get("uri", False) is uri
    assert not (tmp_path / "todos.db").exists()


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
            r"migrations and the application use separate engine/process lifetimes",
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


@pytest.mark.parametrize(
    "value", [pytest.param("", id="blank"), pytest.param(" , ", id="empty-items")]
)
def test_settings_blank_cors_origins_disable_cors(monkeypatch, value):
    monkeypatch.setenv("MY_APP_CORS_ORIGINS", value)

    assert Settings().cors_origins == []


def test_settings_cors_origins_are_stripped_and_deduplicated(monkeypatch):
    monkeypatch.setenv(
        "MY_APP_CORS_ORIGINS",
        "http://localhost:5173, https://app.example.com, ,http://localhost:5173",
    )

    assert Settings().cors_origins == [
        "http://localhost:5173",
        "https://app.example.com",
    ]


@pytest.mark.parametrize(
    "origin",
    [
        pytest.param("http://localhost:5173/", id="slash"),
        pytest.param("https://app.example.com/path", id="path"),
        pytest.param("*", id="wildcard"),
        pytest.param("null", id="null"),
        pytest.param("localhost:5173", id="no-scheme"),
        pytest.param("ftp://app.example.com", id="wrong-scheme"),
        pytest.param("https://bad host", id="whitespace"),
        pytest.param("https://app.example.com?x=1", id="query"),
        pytest.param("https://app.example.com?", id="empty-query"),
        pytest.param("https://app.example.com#", id="empty-fragment"),
        pytest.param("https://app.example.com#fragment", id="fragment"),
        pytest.param("https://app.example.com:abc", id="non-numeric-port"),
        pytest.param("https://app.example.com:65536", id="out-of-range-port"),
        pytest.param("https://app.example.com:", id="empty-port"),
        pytest.param("https://:", id="missing-host"),
        pytest.param("https://user@app.example.com", id="userinfo"),
        pytest.param("https://*.example.com", id="wildcard-host"),
    ],
)
def test_settings_invalid_cors_origin_names_the_item(monkeypatch, origin):
    monkeypatch.setenv("MY_APP_CORS_ORIGINS", origin)

    with pytest.raises(ValidationError, match="invalid CORS origin") as caught:
        Settings()

    assert origin in str(caught.value)


def test_settings_programmatic_cors_origins_use_the_same_rules():
    assert Settings(
        cors_origins=[" https://app.example.com ", "https://app.example.com"]
    ).cors_origins == ["https://app.example.com"]

    with pytest.raises(ValidationError, match="invalid CORS origin"):
        Settings(cors_origins=["https://app.example.com/"])


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        pytest.param(
            "https://APP.EXAMPLE.COM", "https://app.example.com", id="lowercase-host"
        ),
        pytest.param(
            "https://app.example.com:443",
            "https://app.example.com",
            id="default-https-port",
        ),
        pytest.param(
            "http://app.example.com:80",
            "http://app.example.com",
            id="default-http-port",
        ),
        pytest.param("https://éxample.com", "https://xn--xample-9ua.com", id="idn"),
        pytest.param("http://[::1]:5173", "http://[::1]:5173", id="ipv6-port"),
    ],
)
def test_settings_cors_origins_match_browser_serialization(origin, expected):
    assert Settings(cors_origins=[origin]).cors_origins == [expected]


def test_settings_cors_origins_deduplicate_after_normalization():
    assert Settings(
        cors_origins=["https://APP.EXAMPLE.COM:443", "https://app.example.com"]
    ).cors_origins == ["https://app.example.com"]


def test_settings_env_file_value_is_read(tmp_path):
    file = tmp_path / ".env"
    file.write_text(
        'MY_APP_DATABASE_URL="sqlite+aiosqlite:///./var/from-file.db"\nMY_APP_CORS_ORIGINS="https://app.example.com"\n',
        encoding="utf-8",
    )

    settings = settings_from_env_file(file)

    assert settings.database_url == "sqlite+aiosqlite:///./var/from-file.db"
    assert settings.cors_origins == ["https://app.example.com"]


@pytest.mark.parametrize("value", ["sqlite+aiosqlite:///from-env.db", ""])
def test_settings_environment_wins_over_env_file(tmp_path, monkeypatch, value):
    file = tmp_path / ".env"
    file.write_text(
        "MY_APP_DATABASE_URL=sqlite+aiosqlite:///from-file.db\n", encoding="utf-8"
    )
    monkeypatch.setenv("MY_APP_DATABASE_URL", value)

    assert settings_from_env_file(file).database_url == (value or None)


def test_settings_env_file_unknown_prefixed_key_fails(tmp_path):
    file = tmp_path / ".env"
    file.write_text(
        "MY_APP_DATABASE_LINK=sqlite+aiosqlite:///x.db\nVITE_PORT=5174\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="database_link") as raised:
        settings_from_env_file(file)

    assert [error["loc"] for error in raised.value.errors()] == [("database_link",)]


def test_settings_env_file_unknown_unprefixed_key_is_ignored(tmp_path):
    file = tmp_path / ".env"
    file.write_text(
        "VITE_PORT=5174\nDATABASE_URL=sqlite+aiosqlite:///foreign.db\n",
        encoding="utf-8",
    )

    assert (
        settings_from_env_file(file).model_dump()
        == settings_from_env_file(None).model_dump()
    )


def test_settings_env_file_path_is_backend_relative_after_chdir(tmp_path, monkeypatch):
    expected = Path(my_app.__file__).resolve().parents[2] / ".env"
    assert expected == settings_module.ENV_FILE
    monkeypatch.chdir(tmp_path)
    assert expected == settings_module.ENV_FILE


def test_settings_tests_disable_the_developer_env_file():
    assert Settings.model_config["env_file"] is None


def test_settings_missing_env_file_uses_defaults(tmp_path):
    assert (
        settings_from_env_file(tmp_path / "missing.env").model_dump()
        == settings_from_env_file(None).model_dump()
    )


def test_settings_blank_env_file_values_use_defaults(tmp_path):
    file = tmp_path / ".env"
    file.write_text("MY_APP_DATABASE_URL=\nMY_APP_CORS_ORIGINS=\n", encoding="utf-8")

    assert (
        settings_from_env_file(file).model_dump()
        == settings_from_env_file(None).model_dump()
    )
