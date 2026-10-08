"""The one contract every ``TodoRepository`` implementation must pass.

A new adapter joins by adding one ``pytest.param`` to ``REPOSITORY_FACTORIES``;
the core relies on nothing beyond what these tests pin down.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from my_app.adapters.memory import InMemoryTodoRepository
from my_app.adapters.sqlite import SqliteTodoRepository
from my_app.core.errors import TodoNotFoundError
from my_app.core.models import Todo, TodoDraft
from my_app.core.ports import TodoRepository

if TYPE_CHECKING:
    from pathlib import Path


def _in_memory(_: Path) -> TodoRepository:
    return InMemoryTodoRepository()


def _sqlite(tmp_path: Path) -> TodoRepository:
    return SqliteTodoRepository(tmp_path / "todos.db")


CONCURRENT_ADDS = 200
WORKERS = 8

REPOSITORY_FACTORIES = [
    pytest.param(_in_memory, id="in-memory"),
    pytest.param(_sqlite, id="sqlite"),
]
# Beyond 64 bits SQLite cannot even bind the id; every adapter must still
# answer "not found", never a driver error.
UNKNOWN_IDS = [
    pytest.param(0, id="zero"),
    pytest.param(-1, id="negative"),
    pytest.param(999, id="never-assigned"),
    pytest.param(2**63, id="above-int64"),
    pytest.param(-(2**63) - 1, id="below-int64"),
]


@pytest.fixture(params=REPOSITORY_FACTORIES)
def repository(request, tmp_path):
    return request.param(tmp_path)


@pytest.fixture
def make_draft(fixed_now):
    def _make(title: str = "buy milk") -> TodoDraft:
        return TodoDraft(title=title, created_at=fixed_now)

    return _make


def test_repository_implements_every_port_method(repository):
    assert isinstance(repository, TodoRepository)


def test_add_draft_returns_open_todo_with_draft_fields(repository, make_draft):
    draft = make_draft("buy milk")

    todo = repository.add(draft)

    assert todo == Todo(id=todo.id, title="buy milk", created_at=draft.created_at)
    assert todo.is_completed is False


def test_add_several_drafts_assigns_increasing_ids(repository, make_draft):
    ids = [repository.add(make_draft(f"todo {n}")).id for n in range(3)]

    assert ids == sorted(set(ids))


def test_add_after_delete_never_reuses_an_id(repository, make_draft):
    deleted = repository.add(make_draft())
    repository.delete(deleted.id)

    added = repository.add(make_draft())

    assert added.id > deleted.id


def test_get_added_todo_round_trips_every_field(repository, make_draft):
    added = repository.add(make_draft("牛乳を買う 🥛"))

    fetched = repository.get(added.id)

    assert fetched == added
    assert fetched.created_at.utcoffset() is not None


@pytest.mark.parametrize("todo_id", UNKNOWN_IDS)
def test_get_unknown_id_raises_todo_not_found_error(repository, todo_id):
    with pytest.raises(TodoNotFoundError, match=rf"^To-do {todo_id} not found$"):
        repository.get(todo_id)


def test_list_all_empty_store_returns_empty_list(repository):
    assert repository.list_all() == []


def test_list_all_several_todos_returns_them_in_id_order(repository, make_draft):
    added = [repository.add(make_draft(title)) for title in ("a", "b", "c")]

    assert repository.list_all() == added


def test_update_existing_todo_persists_the_change(repository, make_draft):
    added = repository.add(make_draft())
    changed = replace(added, title="buy oat milk", is_completed=True)

    returned = repository.update(changed)

    assert returned == changed
    assert repository.get(added.id) == changed


@pytest.mark.parametrize("todo_id", UNKNOWN_IDS)
def test_update_unknown_id_raises_and_stores_nothing(repository, fixed_now, todo_id):
    ghost = Todo(id=todo_id, title="ghost", created_at=fixed_now)

    with pytest.raises(TodoNotFoundError, match=rf"^To-do {todo_id} not found$"):
        repository.update(ghost)

    assert repository.list_all() == []


def test_delete_existing_todo_removes_only_that_todo(repository, make_draft):
    kept = repository.add(make_draft("keep"))
    dropped = repository.add(make_draft("drop"))

    repository.delete(dropped.id)

    assert repository.list_all() == [kept]


@pytest.mark.parametrize("todo_id", UNKNOWN_IDS)
def test_delete_unknown_id_raises_todo_not_found_error(repository, todo_id):
    with pytest.raises(TodoNotFoundError, match=rf"^To-do {todo_id} not found$"):
        repository.delete(todo_id)


def test_delete_same_id_twice_raises_on_the_second_call(repository, make_draft):
    todo = repository.add(make_draft())
    repository.delete(todo.id)

    with pytest.raises(TodoNotFoundError, match=r"not found"):
        repository.delete(todo.id)


def test_repository_concurrent_adds_assign_unique_ids(repository, fixed_now):
    drafts = [TodoDraft(f"todo {n}", fixed_now) for n in range(CONCURRENT_ADDS)]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        added = list(pool.map(repository.add, drafts))

    ids = sorted(todo.id for todo in added)
    assert len(set(ids)) == CONCURRENT_ADDS
    assert all(todo_id > 0 for todo_id in ids)
    assert len(repository.list_all()) == CONCURRENT_ADDS
