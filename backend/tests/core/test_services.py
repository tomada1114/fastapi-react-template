from __future__ import annotations

from uuid import UUID

import pytest

from my_app.adapters.memory import InMemoryTodoRepository
from my_app.core.errors import (
    InvalidPageLimitError,
    InvalidTodoError,
    TodoNotFoundError,
)
from my_app.core.models import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, Page, Todo
from my_app.core.services import TodoService

pytestmark = pytest.mark.anyio

UNKNOWN_ID = UUID("01900000-0000-7000-8000-0000000003e7")


@pytest.fixture
def service(fixed_clock, new_id):
    """A service over the in-memory repository, the core's fake."""
    return TodoService(InMemoryTodoRepository(), fixed_clock, new_id)


@pytest.fixture
def create_many(service):
    """Create ``count`` to-dos through the service, oldest first."""

    async def _create(count: int) -> list[Todo]:
        return [await service.create(f"todo {n}") for n in range(count)]

    return _create


async def test_create_valid_title_stores_open_todo_with_new_id_and_clock_time(
    service, nth_id, fixed_now
):
    todo = await service.create("  buy milk ")

    assert todo == Todo(id=nth_id(1), title="buy milk", created_at=fixed_now)
    assert await service.list_page() == Page(items=(todo,), next_cursor=None)


async def test_create_several_todos_gives_each_the_next_id(service, nth_id):
    first = await service.create("first")
    second = await service.create("second")

    assert (first.id, second.id) == (nth_id(1), nth_id(2))


async def test_create_empty_title_raises_and_stores_nothing(service):
    with pytest.raises(InvalidTodoError, match=r"got 0$"):
        await service.create("   ")

    assert await service.list_page() == Page(items=(), next_cursor=None)


async def test_list_page_empty_store_returns_empty_last_page(service):
    assert await service.list_page() == Page(items=(), next_cursor=None)


async def test_list_page_several_todos_returns_oldest_first(service, create_many):
    created = await create_many(3)

    page = await service.list_page()

    assert page == Page(items=tuple(created), next_cursor=None)


async def test_list_page_default_limit_returns_a_full_page_and_a_cursor(
    service, create_many
):
    created = await create_many(DEFAULT_PAGE_LIMIT + 1)

    page = await service.list_page()

    assert page.items == tuple(created[:DEFAULT_PAGE_LIMIT])
    assert page.next_cursor is not None


async def test_list_page_following_cursors_returns_every_todo_once(
    service, create_many
):
    created = await create_many(5)

    first = await service.list_page(limit=2)
    second = await service.list_page(first.next_cursor, 2)
    third = await service.list_page(second.next_cursor, 2)

    assert first.items + second.items + third.items == tuple(created)
    assert third.next_cursor is None


@pytest.mark.parametrize(
    ("limit", "expected_count"),
    [
        pytest.param(1, 1, id="min"),
        pytest.param(MAX_PAGE_LIMIT, MAX_PAGE_LIMIT, id="max"),
    ],
)
async def test_list_page_limit_at_a_bound_returns_that_many_and_a_cursor(
    service, create_many, limit, expected_count
):
    await create_many(MAX_PAGE_LIMIT + 1)

    page = await service.list_page(limit=limit)

    assert len(page.items) == expected_count
    assert page.next_cursor is not None


@pytest.mark.parametrize(
    "limit",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(MAX_PAGE_LIMIT + 1, id="above-max"),
    ],
)
async def test_list_page_limit_out_of_range_raises_invalid_page_limit_error(
    service, limit
):
    with pytest.raises(
        InvalidPageLimitError, match=rf"^Page limit must be 1-100, got {limit}$"
    ):
        await service.list_page(limit=limit)


async def test_complete_open_todo_marks_it_completed(service):
    todo = await service.create("buy milk")

    completed = await service.complete(todo.id)

    assert completed.is_completed is True
    assert (await service.list_page()).items == (completed,)


async def test_complete_completed_todo_returns_it_unchanged(service):
    todo = await service.create("buy milk")
    first = await service.complete(todo.id)

    second = await service.complete(todo.id)

    assert second == first


async def test_complete_unknown_id_raises_todo_not_found_error(service):
    with pytest.raises(TodoNotFoundError, match=rf"^To-do {UNKNOWN_ID} not found$"):
        await service.complete(UNKNOWN_ID)


async def test_delete_existing_todo_removes_only_that_todo(service):
    kept = await service.create("keep")
    dropped = await service.create("drop")

    await service.delete(dropped.id)

    assert (await service.list_page()).items == (kept,)


async def test_delete_unknown_id_raises_todo_not_found_error(service):
    with pytest.raises(TodoNotFoundError, match=rf"^To-do {UNKNOWN_ID} not found$"):
        await service.delete(UNKNOWN_ID)
