"""The one contract every ``TodoRepository`` implementation must pass.

A new adapter joins by adding one ``pytest.param`` to ``REPOSITORY_FACTORIES``;
the core relies on nothing beyond what these tests pin down. Ids come from the
application (the ``new_id`` fixture here), never from the store.
"""

from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

import anyio
import pytest

from my_app.adapters.memory import InMemoryTodoRepository
from my_app.adapters.sql.engine import make_engine
from my_app.adapters.sql.repository import SqlTodoRepository
from my_app.adapters.sql.tables import metadata
from my_app.core.errors import InvalidCursorError, TodoNotFoundError
from my_app.core.models import Page, Todo
from my_app.core.ports import TodoRepository
from tests.conftest import POSTGRES_URL

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@asynccontextmanager
async def _in_memory(_: Path) -> AsyncIterator[TodoRepository]:
    yield InMemoryTodoRepository()


@asynccontextmanager
async def _sql_sqlite(tmp_path: Path) -> AsyncIterator[TodoRepository]:
    # A fresh file per test, its schema built straight from the table metadata
    # (test_sql_migrations.py holds the migrations to that same metadata).
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'todos.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        yield SqlTodoRepository(engine)
    finally:
        await engine.dispose()


@asynccontextmanager
async def _sql_postgres(_: Path) -> AsyncIterator[TodoRepository]:
    engine = make_engine(POSTGRES_URL or "")
    try:
        async with engine.begin() as connection:
            await connection.execute(metadata.tables["todos"].delete())
        yield SqlTodoRepository(engine)
    finally:
        await engine.dispose()


def _urlsafe_unpadded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _with_nonzero_padding_bits(cursor: str) -> str:
    # 16 bytes leave 4 unused bits in the last of 22 characters; a decoder that
    # ignores them would accept 16 spellings of one cursor.
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    last = alphabet.index(cursor[-1])
    return cursor[:-1] + alphabet[last | 1]


CONCURRENT_ADDS = 200
# A v7-shaped id the new_id fixture never reaches in one test.
NEVER_ASSIGNED_ID = UUID("01900000-0000-7000-8000-ffffffffffff")
VALID_CURSOR = _urlsafe_unpadded(NEVER_ASSIGNED_ID.bytes)

REPOSITORY_FACTORIES = [
    pytest.param(_in_memory, id="in-memory"),
    pytest.param(_sql_sqlite, id="sql-sqlite"),
    pytest.param(_sql_postgres, marks=pytest.mark.postgres, id="sql-postgres"),
]
UNKNOWN_IDS = [
    pytest.param(UUID(int=0), id="nil"),
    pytest.param(UUID(int=2**128 - 1), id="max"),
    pytest.param(NEVER_ASSIGNED_ID, id="never-assigned"),
]
INVALID_CURSORS = [
    pytest.param("", id="empty"),
    pytest.param("!!!!", id="not-base64"),
    pytest.param(VALID_CURSOR[:21], id="21-characters"),
    pytest.param(VALID_CURSOR + "A", id="23-characters"),
    pytest.param(_urlsafe_unpadded(bytes(15)), id="15-bytes"),
    pytest.param(_with_nonzero_padding_bits(VALID_CURSOR), id="padding-bits"),
    pytest.param(VALID_CURSOR + "==", id="padded"),
    pytest.param(
        base64.b64encode(b"\xfb\xff" * 8).rstrip(b"=").decode("ascii"),
        id="standard-alphabet",
    ),
    pytest.param("é" * 22, id="non-ascii"),
]

pytestmark = pytest.mark.anyio


@pytest.fixture(params=REPOSITORY_FACTORIES)
async def repository(request, tmp_path, migrated_postgres_url):
    """Each implementation in turn, released after the test."""
    async with request.param(tmp_path) as built:
        yield built


@pytest.fixture
def make_todo(new_id, fixed_now):
    """Build an unstored to-do with the next id ``new_id`` hands out."""

    def _make(title: str = "buy milk") -> Todo:
        return Todo(id=new_id(), title=title, created_at=fixed_now)

    return _make


@pytest.fixture
def add_many(repository, make_todo):
    """Store ``count`` new to-dos, oldest first, and return them."""

    async def _add(count: int) -> list[Todo]:
        return [await repository.add(make_todo(f"todo {n}")) for n in range(count)]

    return _add


async def test_repository_implements_every_port_method(repository):
    assert isinstance(repository, TodoRepository)


async def test_add_new_todo_returns_it_unchanged(repository, make_todo):
    todo = make_todo("buy milk")

    assert await repository.add(todo) == todo


async def test_get_added_todo_round_trips_every_field(repository, make_todo):
    added = await repository.add(make_todo("牛乳を買う 🥛"))

    fetched = await repository.get(added.id)

    assert fetched == added
    assert fetched.created_at.utcoffset() is not None


async def test_add_duplicate_id_raises_value_error_and_keeps_the_stored_todo(
    repository, make_todo
):
    stored = await repository.add(make_todo("original"))
    duplicate = replace(stored, title="impostor", is_completed=True)

    with pytest.raises(ValueError, match=str(stored.id)):
        await repository.add(duplicate)

    assert await repository.get(stored.id) == stored
    assert (await repository.list_page(None, 10)).items == (stored,)


@pytest.mark.parametrize("todo_id", UNKNOWN_IDS)
async def test_get_unknown_id_raises_todo_not_found_error(repository, todo_id):
    with pytest.raises(TodoNotFoundError, match=rf"^To-do {todo_id} not found$"):
        await repository.get(todo_id)


async def test_list_page_empty_store_returns_empty_last_page(repository):
    assert await repository.list_page(None, 50) == Page(items=(), next_cursor=None)


async def test_list_page_more_todos_than_limit_pages_through_them_in_id_order(
    repository, add_many
):
    added = await add_many(3)

    first = await repository.list_page(None, 2)
    second = await repository.list_page(first.next_cursor, 2)

    assert first.items == tuple(added[:2])
    assert first.next_cursor is not None
    assert second == Page(items=(added[2],), next_cursor=None)


async def test_list_page_exactly_limit_todos_returns_them_all_without_cursor(
    repository, add_many
):
    added = await add_many(3)

    assert await repository.list_page(None, 3) == Page(
        items=tuple(added), next_cursor=None
    )


async def test_list_page_limit_one_visits_every_todo_once(repository, add_many):
    added = await add_many(3)

    first = await repository.list_page(None, 1)
    second = await repository.list_page(first.next_cursor, 1)
    third = await repository.list_page(second.next_cursor, 1)

    assert [first.items, second.items, third.items] == [(todo,) for todo in added]
    assert third.next_cursor is None


async def test_list_page_orders_by_id_not_by_insertion(repository, make_todo):
    first, second, third = make_todo("a"), make_todo("b"), make_todo("c")
    for todo in (third, first, second):
        await repository.add(todo)

    page = await repository.list_page(None, 10)

    assert page.items == (first, second, third)


async def test_list_page_cursor_of_deleted_todo_returns_the_todos_after_it(
    repository, add_many
):
    added = await add_many(3)
    first = await repository.list_page(None, 1)
    await repository.delete(added[0].id)

    rest = await repository.list_page(first.next_cursor, 10)

    assert rest == Page(items=tuple(added[1:]), next_cursor=None)


async def test_list_page_cursor_of_never_stored_id_returns_the_todos_after_it(
    repository, make_todo, new_id
):
    first = await repository.add(make_todo("a"))
    skipped = new_id()
    second = await repository.add(make_todo("b"))
    assert first.id < skipped < second.id

    page = await repository.list_page(_urlsafe_unpadded(skipped.bytes), 10)

    assert page == Page(items=(second,), next_cursor=None)


@pytest.mark.parametrize(
    ("cursor_id", "expected_titles"),
    [
        pytest.param(UUID(int=0), ("a", "b"), id="below-every-id"),
        pytest.param(UUID(int=2**128 - 1), (), id="above-every-id"),
    ],
)
async def test_list_page_cursor_outside_stored_ids_returns_the_todos_after_it(
    repository, make_todo, cursor_id, expected_titles
):
    for title in ("a", "b"):
        await repository.add(make_todo(title))

    page = await repository.list_page(_urlsafe_unpadded(cursor_id.bytes), 10)

    assert tuple(todo.title for todo in page.items) == expected_titles
    assert page.next_cursor is None


@pytest.mark.parametrize("cursor", INVALID_CURSORS)
async def test_list_page_cursor_not_issued_raises_invalid_cursor_error(
    repository, add_many, cursor
):
    await add_many(1)

    with pytest.raises(InvalidCursorError):
        await repository.list_page(cursor, 10)


async def test_update_existing_todo_persists_the_change(repository, make_todo):
    added = await repository.add(make_todo())
    changed = replace(added, title="buy oat milk", is_completed=True)

    returned = await repository.update(changed)

    assert returned == changed
    assert await repository.get(added.id) == changed


@pytest.mark.parametrize("todo_id", UNKNOWN_IDS)
async def test_update_unknown_id_raises_and_stores_nothing(
    repository, fixed_now, todo_id
):
    ghost = Todo(id=todo_id, title="ghost", created_at=fixed_now)

    with pytest.raises(TodoNotFoundError, match=rf"^To-do {todo_id} not found$"):
        await repository.update(ghost)

    assert await repository.list_page(None, 10) == Page(items=(), next_cursor=None)


async def test_delete_existing_todo_removes_only_that_todo(repository, make_todo):
    kept = await repository.add(make_todo("keep"))
    dropped = await repository.add(make_todo("drop"))

    await repository.delete(dropped.id)

    assert (await repository.list_page(None, 10)).items == (kept,)


@pytest.mark.parametrize("todo_id", UNKNOWN_IDS)
async def test_delete_unknown_id_raises_todo_not_found_error(repository, todo_id):
    with pytest.raises(TodoNotFoundError, match=rf"^To-do {todo_id} not found$"):
        await repository.delete(todo_id)


async def test_delete_same_id_twice_raises_on_the_second_call(repository, make_todo):
    todo = await repository.add(make_todo())
    await repository.delete(todo.id)

    with pytest.raises(TodoNotFoundError, match=r"not found"):
        await repository.delete(todo.id)


async def test_repository_concurrent_adds_store_every_todo(repository, make_todo):
    todos = [make_todo(f"todo {n}") for n in range(CONCURRENT_ADDS)]

    async with anyio.create_task_group() as task_group:
        for todo in todos:
            task_group.start_soon(repository.add, todo)

    page = await repository.list_page(None, CONCURRENT_ADDS)
    assert page == Page(items=tuple(todos), next_cursor=None)
