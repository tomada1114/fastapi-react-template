"""Behavior only the SQLite repository has: the data outlives the object."""

from __future__ import annotations

import pytest

from my_app.adapters.sqlite import SqliteTodoRepository
from my_app.core.models import TodoDraft

pytestmark = pytest.mark.anyio


async def test_sqlite_repository_reopened_on_same_file_keeps_todos(tmp_path, fixed_now):
    path = tmp_path / "todos.db"
    added = await SqliteTodoRepository(path).add(TodoDraft("buy milk", fixed_now))

    reopened = SqliteTodoRepository(path)

    assert await reopened.list_all() == [added]


def test_sqlite_repository_missing_parent_directory_creates_it(tmp_path):
    path = tmp_path / "nested" / "dir" / "todos.db"

    SqliteTodoRepository(path)

    assert path.is_file()
