from __future__ import annotations

import pytest

from my_app.adapters.memory import InMemoryTodoRepository
from my_app.core.errors import InvalidTodoError, TodoNotFoundError
from my_app.core.services import TodoService


@pytest.fixture
def service(fixed_clock):
    """A service over the in-memory repository, the core's fake."""
    return TodoService(InMemoryTodoRepository(), fixed_clock)


def test_create_valid_title_stores_open_todo_stamped_by_clock(service, fixed_now):
    todo = service.create("  buy milk ")

    assert todo.title == "buy milk"
    assert todo.created_at == fixed_now
    assert todo.is_completed is False
    assert service.list_todos() == [todo]


def test_create_empty_title_raises_and_stores_nothing(service):
    with pytest.raises(InvalidTodoError, match=r"got 0$"):
        service.create("   ")

    assert service.list_todos() == []


def test_list_todos_empty_store_returns_empty_list(service):
    assert service.list_todos() == []


def test_list_todos_several_todos_returns_oldest_first(service):
    first = service.create("first")
    second = service.create("second")

    assert service.list_todos() == [first, second]


def test_complete_open_todo_marks_it_completed(service):
    todo = service.create("buy milk")

    completed = service.complete(todo.id)

    assert completed.is_completed is True
    assert service.list_todos() == [completed]


def test_complete_completed_todo_returns_it_unchanged(service):
    todo = service.create("buy milk")
    first = service.complete(todo.id)

    second = service.complete(todo.id)

    assert second == first


def test_complete_unknown_id_raises_todo_not_found_error(service):
    with pytest.raises(TodoNotFoundError, match=r"^To-do 999 not found$"):
        service.complete(999)


def test_delete_existing_todo_removes_only_that_todo(service):
    kept = service.create("keep")
    dropped = service.create("drop")

    service.delete(dropped.id)

    assert service.list_todos() == [kept]


def test_delete_unknown_id_raises_todo_not_found_error(service):
    with pytest.raises(TodoNotFoundError, match=r"^To-do 999 not found$"):
        service.delete(999)
