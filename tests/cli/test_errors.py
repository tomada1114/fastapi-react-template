from __future__ import annotations

from typer.testing import CliRunner

from my_app.cli.errors import ExitCode
from my_app.cli.main import app


def test_exit_codes_are_distinct_and_keep_typer_usage_error_at_2():
    codes = {code.name: code.value for code in ExitCode}

    assert codes == {"OK": 0, "DOMAIN_ERROR": 1, "USAGE_ERROR": 2, "CONFIG_ERROR": 3}


def test_invalid_setting_exits_3_with_one_line_on_stderr(monkeypatch):
    monkeypatch.setenv("MY_APP_DATABASE_URL", "postgresql://localhost/todos")

    result = CliRunner().invoke(app, ["todo", "list"])

    assert result.exit_code == ExitCode.CONFIG_ERROR
    assert result.stdout == ""
    assert result.stderr.count("\n") == 1
    assert result.stderr.startswith(
        "Error: invalid configuration: MY_APP_DATABASE_URL: "
    )
    assert "Traceback" not in result.output
