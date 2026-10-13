"""Contract exports are deterministic and independent of runtime configuration."""

from __future__ import annotations

import json
import logging

import pytest

from my_app.api.app import create_app
from my_app.api.contract import main
from my_app.settings import Settings


def test_export_matches_app_openapi_serialized_sorted(tmp_path, make_container):
    target = tmp_path / "openapi.json"
    expected = create_app(container=make_container()).openapi()

    assert main(["--output", str(target)]) == 0

    assert target.read_bytes() == (
        json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def test_check_passes_on_current_file_without_writing(tmp_path):
    target = tmp_path / "openapi.json"
    assert main(["--output", str(target)]) == 0
    before = (target.read_bytes(), target.stat().st_mtime_ns)

    assert main(["--output", str(target), "--check"]) == 0

    assert (target.read_bytes(), target.stat().st_mtime_ns) == before


@pytest.mark.parametrize("contents", [None, b"stale\n", b"\xff"])
def test_check_fails_on_missing_or_stale_file_without_writing(
    tmp_path, capsys, contents
):
    target = tmp_path / "openapi.json"
    if contents is not None:
        target.write_bytes(contents)

    assert main(["--output", str(target), "--check"]) == 1

    assert str(target) in capsys.readouterr().err
    assert (
        target.read_bytes() == contents if contents is not None else not target.exists()
    )


def test_check_fails_on_stale_file_names_regeneration_command(tmp_path, capsys):
    target = tmp_path / "openapi.json"
    target.write_text("{}\n")

    assert main(["--output", str(target), "--check"]) == 1

    assert "run `just contract`" in capsys.readouterr().err


def test_export_missing_parent_fails_without_creating_directory(tmp_path, capsys):
    target = tmp_path / "missing" / "openapi.json"

    assert main(["--output", str(target)]) == 1

    assert str(target) in capsys.readouterr().err
    assert not target.parent.exists()


def test_export_ignores_environment_and_creates_no_database(tmp_path, monkeypatch):
    target = tmp_path / "openapi.json"
    assert main(["--output", str(target)]) == 0
    expected = target.read_bytes()
    for name, value in {
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}",
        "CORS_ORIGINS": "invalid origin",
        "LOG_LEVEL": "INVALID",
        "LOG_FORMAT": "INVALID",
    }.items():
        monkeypatch.setenv(f"MY_APP_{name}", value)

    assert main(["--output", str(target)]) == 0

    assert target.read_bytes() == expected
    assert not (tmp_path / "db.sqlite").exists()


def test_export_ignores_dotenv(tmp_path, monkeypatch):
    target = tmp_path / "openapi.json"
    assert main(["--output", str(target)]) == 0
    expected = target.read_bytes()
    dotenv = tmp_path / ".env"
    dotenv.write_text("MY_APP_LOG_LEVEL=invalid\nMY_APP_DATABASE_URL=invalid\n")
    monkeypatch.setitem(Settings.model_config, "env_file", dotenv)

    assert main(["--output", str(target)]) == 0

    assert target.read_bytes() == expected


def test_export_preserves_logging_handlers(tmp_path):
    logger = logging.getLogger("my_app")
    before = (logger.handlers[:], logger.level, logger.propagate)

    assert main(["--output", str(tmp_path / "openapi.json")]) == 0

    assert (logger.handlers, logger.level, logger.propagate) == before


def test_export_is_deterministic_and_preserves_unicode(tmp_path, monkeypatch):
    monkeypatch.setattr("my_app.api.app.APP_TITLE", "Café API")
    target = tmp_path / "openapi.json"
    assert main(["--output", str(target)]) == 0
    expected = target.read_bytes()

    assert main(["--output", str(target)]) == 0

    assert target.read_bytes() == expected
    assert "Café API".encode() in expected
    assert expected.endswith(b"}\n")
    assert not expected.endswith(b"\n\n")
