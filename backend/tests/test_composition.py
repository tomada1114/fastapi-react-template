from __future__ import annotations

import tomllib
from contextlib import ExitStack, suppress
from datetime import UTC
from pathlib import Path

import pytest

from my_app import composition
from my_app.adapters.memory import InMemoryTodoRepository
from my_app.composition import Container, build_container, utc_now
from my_app.settings import Settings

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_build_container_default_settings_uses_an_independent_memory_store(
    make_container,
):
    first = make_container()
    second = make_container()

    first.todos.create("only in first")

    assert second.todos.list_todos() == []


def test_build_container_sqlite_settings_shares_the_file(make_container, tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'todos.db'}")
    created = make_container(settings).todos.create("buy milk")

    reopened = make_container(settings)

    assert reopened.todos.list_todos() == [created]


def test_build_container_injected_clock_stamps_created_at(make_container, fixed_now):
    todo = make_container().todos.create("buy milk")

    assert todo.created_at == fixed_now


def test_utc_now_returns_timezone_aware_utc_time():
    assert utc_now().tzinfo is UTC


def test_pyproject_httpx_is_not_a_runtime_dependency():
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    runtime = [dep for dep in project["dependencies"] if dep.startswith("httpx")]

    assert runtime == []


def test_container_close_releases_registered_resource_once(make_container):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "resource")
    container = Container(make_container().todos, _resources=resources)

    container.close()
    container.close()

    assert closed == ["resource"]


def test_container_context_exit_releases_registered_resource(make_container):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "resource")
    container = Container(make_container().todos, _resources=resources)

    with container as entered:
        assert entered is container
        assert closed == []

    assert closed == ["resource"]


def test_container_context_failure_releases_registered_resource(make_container):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "resource")
    container = Container(make_container().todos, _resources=resources)

    message = "operation failed"
    with pytest.raises(ValueError, match="operation failed"), container:
        raise ValueError(message)

    assert closed == ["resource"]


def test_container_cleanup_failure_runs_remaining_callbacks_and_propagates(
    make_container,
):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "remaining")

    def fail_cleanup():
        message = "cleanup failed"
        raise ValueError(message)

    resources.callback(fail_cleanup)
    container = Container(make_container().todos, _resources=resources)

    with pytest.raises(ValueError, match="cleanup failed"):
        container.close()
    container.close()

    assert closed == ["remaining"]


def test_build_container_failure_closes_partially_registered_resources(monkeypatch):
    closed: list[str] = []

    def fail_build(settings, resources=None):
        if resources is not None:
            resources.callback(closed.append, "partial")
        message = "build failed"
        raise ValueError(message)

    monkeypatch.setattr(composition, "_build_repository", fail_build)

    with pytest.raises(ValueError, match="build failed"):
        build_container(Settings())

    assert closed == ["partial"]


def test_build_container_success_keeps_registered_resources_until_close(monkeypatch):
    closed: list[str] = []

    def build_repository(settings, resources):
        resources.callback(closed.append, "owned")
        return InMemoryTodoRepository()

    monkeypatch.setattr(composition, "_build_repository", build_repository)

    container = build_container(Settings())
    assert closed == []
    container.close()
    container.close()

    assert closed == ["owned"]


def test_container_context_failure_forwards_exception_details_to_resource(
    make_container,
):
    exits: list[tuple[object, object, object]] = []

    class RecordingResource:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            exits.append((exc_type, exc_value, traceback))
            return False

    resources = ExitStack()
    resources.enter_context(RecordingResource())
    container = Container(make_container().todos, _resources=resources)
    error = ValueError("operation failed")

    with pytest.raises(ValueError, match="operation failed"), container:
        raise error

    assert exits == [(ValueError, error, error.__traceback__)]
    container.close()
    assert len(exits) == 1


def test_container_context_failure_preserves_resource_suppression(make_container):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "remaining")
    resources.enter_context(suppress(ValueError))
    container = Container(make_container().todos, _resources=resources)
    message = "intentionally suppressed"

    with container:
        raise ValueError(message)

    container.close()
    assert closed == ["remaining"]
