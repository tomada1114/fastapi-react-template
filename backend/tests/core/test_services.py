from __future__ import annotations

import pytest

from my_app.adapters.memory import InMemoryTodoRepository
from my_app.core.errors import InvalidTodoError, TodoNotFoundError
from my_app.core.services import TodoService

pytestmark = pytest.mark.anyio


@pytest.fixture
def service(fixed_clock):
    """A service over the in-memory repository, the core's fake."""
    return TodoService(InMemoryTodoRepository(), fixed_clock)


async def test_create_valid_title_stores_open_todo_stamped_by_clock(service, fixed_now):
    todo = await service.create("  buy milk ")

    assert todo.title == "buy milk"
    assert todo.created_at == fixed_now
    assert todo.is_completed is False
    assert await service.list_todos() == [todo]


async def test_create_empty_title_raises_and_stores_nothing(service):
    with pytest.raises(InvalidTodoError, match=r"got 0$"):
        await service.create("   ")

    assert await service.list_todos() == []


async def test_list_todos_empty_store_returns_empty_list(service):
    assert await service.list_todos() == []


async def test_list_todos_several_todos_returns_oldest_first(service):
    first = await service.create("first")
    second = await service.create("second")

    assert await service.list_todos() == [first, second]


async def test_complete_open_todo_marks_it_completed(service):
    todo = await service.create("buy milk")

    completed = await service.complete(todo.id)

    assert completed.is_completed is True
    assert await service.list_todos() == [completed]


async def test_complete_completed_todo_returns_it_unchanged(service):
    todo = await service.create("buy milk")
    first = await service.complete(todo.id)

    second = await service.complete(todo.id)

    assert second == first


async def test_complete_unknown_id_raises_todo_not_found_error(service):
    with pytest.raises(TodoNotFoundError, match=r"^To-do 999 not found$"):
        await service.complete(999)


async def test_delete_existing_todo_removes_only_that_todo(service):
    kept = await service.create("keep")
    dropped = await service.create("drop")

    await service.delete(dropped.id)

    assert await service.list_todos() == [kept]


async def test_delete_unknown_id_raises_todo_not_found_error(service):
    with pytest.raises(TodoNotFoundError, match=r"^To-do 999 not found$"):
        await service.delete(999)
