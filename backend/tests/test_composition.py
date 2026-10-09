from __future__ import annotations

import tomllib
import uuid
from contextlib import AsyncExitStack, suppress
from datetime import UTC
from pathlib import Path

import pytest
from sqlalchemy import event

from my_app import composition
from my_app.adapters.memory import InMemoryTodoRepository
from my_app.adapters.sql.engine import make_engine
from my_app.composition import Container, build_container, utc_now
from my_app.core.models import Page
from my_app.settings import Settings

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

pytestmark = pytest.mark.anyio


async def _record(log: list[str], name: str) -> None:
    """An async cleanup callback that records that it ran."""
    log.append(name)


async def test_build_container_default_settings_uses_an_independent_memory_store(
    make_container,
):
    first = make_container()
    second = make_container()

    await first.todos.create("only in first")

    assert await second.todos.list_page() == Page(items=(), next_cursor=None)


async def test_build_container_sql_settings_shares_the_database(
    make_container, migrated_sqlite_url
):
    settings = Settings(database_url=migrated_sqlite_url)
    created = await make_container(settings).todos.create("buy milk")

    reopened = make_container(settings)

    assert (await reopened.todos.list_page()).items == (created,)


async def test_build_container_sql_settings_disposes_the_engine_on_aclose(
    monkeypatch, migrated_sqlite_url, fixed_clock, new_id
):
    disposed: list[str] = []

    def recording_make_engine(url):
        engine = make_engine(url)
        event.listen(
            engine.sync_engine, "engine_disposed", lambda _: disposed.append(url)
        )
        return engine

    monkeypatch.setattr(composition, "make_engine", recording_make_engine)
    container = build_container(
        Settings(database_url=migrated_sqlite_url), clock=fixed_clock, new_id=new_id
    )
    await container.todos.create("opens a pooled connection")
    assert disposed == []

    await container.aclose()

    assert disposed == [migrated_sqlite_url]


async def test_build_container_injected_clock_stamps_created_at(
    make_container, fixed_now
):
    todo = await make_container().todos.create("buy milk")

    assert todo.created_at == fixed_now


async def test_build_container_injected_id_factory_gives_new_todos_their_ids(
    make_container, nth_id
):
    container = make_container()

    first = await container.todos.create("first")
    second = await container.todos.create("second")

    assert (first.id, second.id) == (nth_id(1), nth_id(2))


async def test_build_container_default_id_factory_gives_ascending_uuid7_ids():
    container = build_container(Settings(database_url=None))

    first = await container.todos.create("first")
    second = await container.todos.create("second")

    assert (first.id.version, second.id.version) == (7, 7)
    assert first.id < second.id


@pytest.mark.parametrize("n", [1, 2, 255, 2**48 - 1])
def test_nth_id_is_shaped_like_a_uuid7(nth_id, n):
    todo_id = nth_id(n)

    assert todo_id.version == 7
    assert todo_id.variant == uuid.RFC_4122
    assert nth_id(n - 1) < todo_id


def test_utc_now_returns_timezone_aware_utc_time():
    assert utc_now().tzinfo is UTC


def test_pyproject_httpx_is_not_a_runtime_dependency():
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    runtime = [dep for dep in project["dependencies"] if dep.startswith("httpx")]

    assert runtime == []


async def test_container_aclose_releases_registered_resource_once(make_container):
    closed: list[str] = []
    resources = AsyncExitStack()
    resources.push_async_callback(_record, closed, "resource")
    container = Container(make_container().todos, _resources=resources)

    await container.aclose()
    await container.aclose()

    assert closed == ["resource"]


async def test_container_context_exit_releases_registered_resource(make_container):
    closed: list[str] = []
    resources = AsyncExitStack()
    resources.push_async_callback(_record, closed, "resource")
    container = Container(make_container().todos, _resources=resources)

    async with container as entered:
        assert entered is container
        assert closed == []

    assert closed == ["resource"]


async def test_container_context_failure_releases_registered_resource(make_container):
    closed: list[str] = []
    resources = AsyncExitStack()
    resources.push_async_callback(_record, closed, "resource")
    container = Container(make_container().todos, _resources=resources)

    message = "operation failed"
    with pytest.raises(ValueError, match="operation failed"):
        async with container:
            raise ValueError(message)

    assert closed == ["resource"]


async def test_container_cleanup_failure_runs_remaining_callbacks_and_propagates(
    make_container,
):
    closed: list[str] = []
    resources = AsyncExitStack()
    resources.push_async_callback(_record, closed, "remaining")

    async def fail_cleanup():
        message = "cleanup failed"
        raise ValueError(message)

    resources.push_async_callback(fail_cleanup)
    container = Container(make_container().todos, _resources=resources)

    with pytest.raises(ValueError, match="cleanup failed"):
        await container.aclose()
    await container.aclose()

    assert closed == ["remaining"]


def test_build_container_failure_propagates_the_builder_error(monkeypatch):
    def fail_build(settings, resources):
        message = "build failed"
        raise ValueError(message)

    monkeypatch.setattr(composition, "_build_repository", fail_build)

    with pytest.raises(ValueError, match="build failed"):
        build_container(Settings())


async def test_build_container_success_keeps_registered_resources_until_aclose(
    monkeypatch,
):
    closed: list[str] = []

    def build_repository(settings, resources):
        resources.push_async_callback(_record, closed, "owned")
        return InMemoryTodoRepository()

    monkeypatch.setattr(composition, "_build_repository", build_repository)

    container = build_container(Settings())
    assert closed == []
    await container.aclose()
    await container.aclose()

    assert closed == ["owned"]


async def test_container_context_failure_forwards_exception_details_to_resource(
    make_container,
):
    exits: list[tuple[object, object, object]] = []

    class RecordingResource:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            exits.append((exc_type, exc_value, traceback))
            return False

    resources = AsyncExitStack()
    await resources.enter_async_context(RecordingResource())
    container = Container(make_container().todos, _resources=resources)
    error = ValueError("operation failed")

    with pytest.raises(ValueError, match="operation failed"):
        async with container:
            raise error

    assert exits == [(ValueError, error, error.__traceback__)]
    await container.aclose()
    assert len(exits) == 1


async def test_container_context_failure_preserves_resource_suppression(
    make_container,
):
    closed: list[str] = []
    resources = AsyncExitStack()
    resources.push_async_callback(_record, closed, "remaining")
    resources.enter_context(suppress(ValueError))
    container = Container(make_container().todos, _resources=resources)
    message = "intentionally suppressed"

    async with container:
        raise ValueError(message)

    await container.aclose()
    assert closed == ["remaining"]
