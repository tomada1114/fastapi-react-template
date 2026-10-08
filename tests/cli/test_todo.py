from __future__ import annotations

from contextlib import ExitStack
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from my_app.cli import context
from my_app.cli.errors import ExitCode
from my_app.cli.main import app
from my_app.composition import Container

if TYPE_CHECKING:
    from typer.testing import Result


@pytest.fixture
def run(make_container):
    """Invoke ``my-app`` against one in-memory container shared across calls.

    Passing the container as ``obj`` mirrors one long-lived process, so a
    to-do added by one invocation is visible to the next.
    """
    runner = CliRunner()
    container = make_container()

    def _run(*args: str) -> Result:
        return runner.invoke(app, list(args), obj=container)

    return _run


def test_todo_add_then_list_shows_the_todo(run):
    added = run("todo", "add", "buy milk")
    listed = run("todo", "list")

    assert added.exit_code == ExitCode.OK
    assert added.stdout == "Added 1 [ ] buy milk\n"
    assert listed.exit_code == ExitCode.OK
    assert listed.stdout == "1 [ ] buy milk\n"


def test_todo_list_empty_store_says_so(run):
    result = run("todo", "list")

    assert result.exit_code == ExitCode.OK
    assert result.stdout == "No to-dos yet.\n"


@pytest.mark.parametrize(
    "title",
    [pytest.param("", id="empty"), pytest.param("   ", id="whitespace-only")],
)
def test_todo_add_empty_title_exits_1_with_error_on_stderr(run, title):
    result = run("todo", "add", title)

    assert result.exit_code == ExitCode.DOMAIN_ERROR
    assert result.stdout == ""
    assert result.stderr.startswith("Error: Title must be 1-200 characters")
    assert run("todo", "list").stdout == "No to-dos yet.\n"


def test_todo_complete_existing_id_marks_it_completed(run):
    run("todo", "add", "buy milk")

    result = run("todo", "complete", "1")

    assert result.exit_code == ExitCode.OK
    assert result.stdout == "Completed 1 [x] buy milk\n"
    assert run("todo", "list").stdout == "1 [x] buy milk\n"


def test_todo_delete_existing_id_removes_it(run):
    run("todo", "add", "buy milk")

    result = run("todo", "delete", "1")

    assert result.exit_code == ExitCode.OK
    assert result.stdout == "Deleted to-do 1\n"
    assert run("todo", "list").stdout == "No to-dos yet.\n"


@pytest.mark.parametrize("command", ["complete", "delete"])
def test_todo_command_unknown_id_exits_1_with_error_on_stderr(run, command):
    result = run("todo", command, "999")

    assert result.exit_code == ExitCode.DOMAIN_ERROR
    assert result.stdout == ""
    assert result.stderr == "Error: To-do 999 not found\n"


@pytest.mark.parametrize("command", ["complete", "delete"])
def test_todo_command_non_integer_id_exits_with_usage_error(run, command):
    result = run("todo", command, "abc")

    assert result.exit_code == ExitCode.USAGE_ERROR


def test_todo_without_supplied_container_reads_settings_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_APP_DATABASE_URL", f"sqlite:///{tmp_path / 'todos.db'}")
    runner = CliRunner()

    runner.invoke(app, ["todo", "add", "buy milk"])
    result = runner.invoke(app, ["todo", "list"])

    assert result.exit_code == ExitCode.OK
    assert result.stdout == "1 [ ] buy milk\n"


@pytest.mark.parametrize("command", ["add", "list", "complete", "delete"])
def test_todo_subcommand_help_sqlite_url_creates_no_database(
    command, tmp_path, monkeypatch
):
    database = tmp_path / "sub" / "help.db"
    monkeypatch.setenv("MY_APP_DATABASE_URL", f"sqlite:///{database}")

    result = CliRunner().invoke(app, ["todo", command, "--help"])

    assert result.exit_code == ExitCode.OK
    assert "Usage:" in result.stdout
    assert result.stderr == ""
    assert not database.parent.exists()


@pytest.mark.parametrize("command", ["add", "list", "complete", "delete"])
def test_todo_subcommand_help_invalid_setting_prints_help(command, monkeypatch):
    monkeypatch.setenv("MY_APP_DATABASE_URL", "postgresql://x")

    result = CliRunner().invoke(app, ["todo", command, "--help"])

    assert result.exit_code == ExitCode.OK
    assert "Usage:" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("args", "exit_code"),
    [
        pytest.param(["todo", "list"], ExitCode.OK, id="success"),
        pytest.param(
            ["todo", "delete", "999"], ExitCode.DOMAIN_ERROR, id="domain-error"
        ),
    ],
)
def test_todo_command_exit_closes_built_container(
    monkeypatch, make_container, args, exit_code
):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "built")
    container = Container(make_container().todos, _resources=resources)
    monkeypatch.setattr(context, "build_container", lambda _: container)

    result = CliRunner().invoke(app, args)

    assert result.exit_code == exit_code
    assert closed == ["built"]


def test_todo_command_exit_leaves_supplied_container_caller_owned(make_container):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "supplied")
    container = Container(make_container().todos, _resources=resources)

    result = CliRunner().invoke(app, ["todo", "list"], obj=container)

    assert result.exit_code == ExitCode.OK
    assert closed == []
    container.close()
    assert closed == ["supplied"]
