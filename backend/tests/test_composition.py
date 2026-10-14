from __future__ import annotations

import asyncio
import sys
import tomllib
import uuid
from contextlib import AsyncExitStack
from contextvars import ContextVar
from datetime import UTC
from pathlib import Path

import anyio
import pytest
from alembic import command
from sqlalchemy import event

from my_app import composition
from my_app.adapters.memory import InMemoryTodoRepository
from my_app.adapters.sql.engine import make_engine
from my_app.composition import Container, build_container, utc_now
from my_app.core.models import Page
from my_app.settings import Settings

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

pytestmark = pytest.mark.anyio


@pytest.fixture
async def engine_disposals(monkeypatch):
    """Observe owned engine disposal; repair resources only if a regression leaks."""
    opened = []
    disposed = []

    def recording_make_engine(url):
        engine = make_engine(url)
        opened.append(engine)
        event.listen(
            engine.sync_engine, "engine_disposed", lambda _: disposed.append(engine)
        )
        return engine

    monkeypatch.setattr(composition, "make_engine", recording_make_engine)
    yield disposed
    for engine in opened:
        if engine not in disposed:
            await engine.dispose()


def test_build_container_postgres_url_without_asyncpg_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "asyncpg", None)
    with pytest.raises(RuntimeError, match=r"postgres.*extra") as raised:
        build_container(Settings(database_url="postgresql+asyncpg://localhost/test"))
    assert isinstance(raised.value.__cause__, ModuleNotFoundError)


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


@pytest.fixture(params=["literal", "native-uri"])
def migrated_query_file_url(request, alembic_config, sqlite_url, monkeypatch):
    """Migrate an owned file with options before starting an application loop."""
    if request.param == "native-uri":
        filename = sqlite_url.removeprefix("sqlite+aiosqlite:///")
        url = f"sqlite+aiosqlite:///file:{filename}?mode=rwc&uri=true&timeout=5"
    else:
        url = f"{sqlite_url}?timeout=5"
    monkeypatch.setenv("MY_APP_DATABASE_URL", url)
    command.upgrade(alembic_config, "head")
    return url


async def test_build_container_query_file_reopens_migrated_schema_and_data(
    migrated_query_file_url,
):
    settings = Settings(database_url=migrated_query_file_url)
    async with build_container(settings) as first:
        created = await first.todos.create("survives disposal with URL options")

    async with build_container(settings) as reopened:
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


async def test_container_cancelled_context_disposes_open_sqlite_engine_once(
    engine_disposals, migrated_sqlite_url
):
    container = build_container(Settings(database_url=migrated_sqlite_url))
    with anyio.CancelScope() as cancelled:
        async with container:
            created = await container.todos.create("opens a real pooled connection")
            assert (await container.todos.list_page()).items == (created,)
            cancelled.cancel()
            await anyio.lowlevel.checkpoint()

    assert cancelled.cancelled_caught
    assert len(engine_disposals) == 1
    await container.aclose()
    assert len(engine_disposals) == 1


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
    resources = composition.ResourceClosers()
    resources.push_async_callback(_record, closed, "resource")
    container = Container(make_container().todos, _resources=resources)

    await container.aclose()
    await container.aclose()

    assert closed == ["resource"]


async def test_container_context_cancelled_scope_finishes_callbacks_once(
    make_container,
):
    entered = []
    closed = []
    resources = composition.ResourceClosers()

    async def cleanup(name):
        entered.append(name)
        await anyio.lowlevel.checkpoint()
        closed.append(name)

    resources.push_async_callback(cleanup, "first")
    resources.push_async_callback(cleanup, "second")
    container = Container(make_container().todos, _resources=resources)

    with anyio.CancelScope() as cancelled:
        async with container:
            cancelled.cancel()
            await anyio.lowlevel.checkpoint()

    assert cancelled.cancelled_caught
    assert entered == ["second", "first"]
    assert closed == ["second", "first"]
    await container.aclose()
    assert closed == ["second", "first"]


async def test_container_aclose_cancelled_scope_finishes_before_cancellation(
    make_container,
):
    closed = []
    returned = []
    resources = composition.ResourceClosers()

    async def cleanup():
        await anyio.lowlevel.checkpoint()
        closed.append("resource")

    resources.push_async_callback(cleanup)
    container = Container(make_container().todos, _resources=resources)

    with anyio.CancelScope() as cancelled:
        cancelled.cancel()
        await container.aclose()
        returned.append("returned")

    assert cancelled.cancelled_caught
    assert returned == []
    assert closed == ["resource"]
    await container.aclose()
    assert closed == ["resource"]


@pytest.mark.parametrize(
    ("fail", "outcome"),
    [
        pytest.param(False, "cancelled", id="cancelled"),
        pytest.param(True, "failed", id="cleanup-failure"),
    ],
)
async def test_container_suspended_cleanup_finishes_before_caller_outcome(
    make_container, fail, outcome
):
    entered = anyio.Event()
    release = anyio.Event()
    done = anyio.Event()
    closed = []
    outcomes = []
    resources = composition.ResourceClosers()

    async def suspended():
        entered.set()
        await release.wait()
        closed.append("held")
        if fail:
            message = "cleanup failed"
            raise ValueError(message)

    resources.push_async_callback(_record, closed, "remaining")
    resources.push_async_callback(suspended)
    container = Container(make_container().todos, _resources=resources)

    async def close(task_status=anyio.TASK_STATUS_IGNORED):
        task_status.started(asyncio.current_task())
        try:
            await container.aclose()
        except asyncio.CancelledError:
            outcomes.append("cancelled")
        except ValueError:
            outcomes.append("failed")
        else:
            outcomes.append("returned")
        finally:
            done.set()

    async with anyio.create_task_group() as tasks:
        caller = await tasks.start(close)
        await entered.wait()
        caller.cancel()
        release.set()
        await done.wait()

    assert closed == ["held", "remaining"]
    assert outcomes == [outcome]
    await container.aclose()
    assert closed == ["held", "remaining"]


async def test_container_concurrent_close_callers_share_complete_lifo_cleanup(
    make_container,
):
    entered = anyio.Event()
    release = anyio.Event()
    closed = []
    snapshots = []
    resources = composition.ResourceClosers()

    async def suspended():
        entered.set()
        await release.wait()
        closed.append("held")

    resources.push_async_callback(_record, closed, "remaining")
    resources.push_async_callback(suspended)
    container = Container(make_container().todos, _resources=resources)

    async def close(task_status=anyio.TASK_STATUS_IGNORED):
        task_status.started()
        await container.aclose()
        snapshots.append(closed.copy())

    async with anyio.create_task_group() as tasks:
        await tasks.start(close)
        await entered.wait()
        await tasks.start(close)
        release.set()

    assert closed == ["held", "remaining"]
    assert snapshots == [["held", "remaining"], ["held", "remaining"]]


async def test_container_concurrent_exits_propagate_each_body_error(make_container):
    entered = anyio.Event()
    release = anyio.Event()
    outcomes = []
    closed = []
    resources = composition.ResourceClosers()

    async def close():
        entered.set()
        await release.wait()
        closed.append("resource")

    resources.push_async_callback(close)
    container = Container(make_container().todos, _resources=resources)

    async def fail(error, task_status=anyio.TASK_STATUS_IGNORED):
        task_status.started()
        try:
            async with container:
                raise error
        except (ValueError, TypeError) as caught:
            outcomes.append(caught)

    first = ValueError("first error")
    second = TypeError("second error")
    async with anyio.create_task_group() as tasks:
        await tasks.start(fail, first)
        await entered.wait()
        await tasks.start(fail, second)
        release.set()

    assert closed == ["resource"]
    assert set(outcomes) == {first, second}


@pytest.mark.parametrize(
    "affinity",
    [
        pytest.param("context", id="context-token"),
        pytest.param("task", id="owning-task"),
    ],
)
async def test_container_entered_manager_rejected_and_exits_in_caller_scope(
    make_container, affinity
):
    marker = ContextVar("synthetic_resource", default="outside")
    closed = []

    class BoundResource:
        async def __aenter__(self):
            self.owner = asyncio.current_task()
            self.token = marker.set("owned")
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            if affinity == "context":
                marker.reset(self.token)
            else:
                assert asyncio.current_task() is self.owner
            closed.append("resource")
            return False

    async with AsyncExitStack() as caller_resources:
        await caller_resources.enter_async_context(BoundResource())

        def transfer(resources):
            # Exercise runtime validation from an untyped external caller.
            return Container(make_container().todos, _resources=resources)

        with pytest.raises(TypeError, match="task-independent disposal callbacks"):
            transfer(caller_resources)
        assert closed == []

    assert closed == ["resource"]
    if affinity == "context":
        assert marker.get() == "outside"


async def test_container_context_exit_releases_registered_resource(make_container):
    closed: list[str] = []
    resources = composition.ResourceClosers()
    resources.push_async_callback(_record, closed, "resource")
    container = Container(make_container().todos, _resources=resources)

    async with container as entered:
        assert entered is container
        assert closed == []

    assert closed == ["resource"]


async def test_container_context_failure_releases_registered_resource(make_container):
    closed: list[str] = []
    resources = composition.ResourceClosers()
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
    resources = composition.ResourceClosers()
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


async def test_container_context_cleanup_failure_chains_original_body_error(
    make_container,
):
    resources = composition.ResourceClosers()
    body_error = ValueError("operation failed")
    cleanup_error = RuntimeError("cleanup failed")

    async def fail_cleanup():
        raise cleanup_error

    resources.push_async_callback(fail_cleanup)
    container = Container(make_container().todos, _resources=resources)

    with pytest.raises(RuntimeError, match="cleanup failed") as caught:
        async with container:
            raise body_error

    assert caught.value is cleanup_error
    assert cleanup_error.__context__ is body_error
    await container.aclose()


async def test_container_disposal_callbacks_cannot_suppress_body_error(make_container):
    resources = composition.ResourceClosers()
    closed = []

    async def close():
        closed.append("resource")
        return True

    resources.push_async_callback(close)
    container = Container(make_container().todos, _resources=resources)
    error = ValueError("operation failed")

    with pytest.raises(ValueError, match="operation failed") as caught:
        async with container:
            raise error

    assert caught.value is error
    assert closed == ["resource"]
    await container.aclose()


async def test_container_registration_after_ownership_transfer_rejected(make_container):
    resources = composition.ResourceClosers()
    container = Container(make_container().todos, _resources=resources)

    with pytest.raises(RuntimeError, match="before building the Container"):
        resources.push_async_callback(_record, [], "late")

    await container.aclose()
