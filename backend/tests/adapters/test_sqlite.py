"""Behavior only the SQLite repository has: the data outlives the object."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from my_app.adapters.sqlite import SqliteTodoRepository
from my_app.core.models import Page, Todo

pytestmark = pytest.mark.anyio

# The table an earlier version of this adapter created, with integer ids.
INTEGER_ID_TABLE = """
CREATE TABLE todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    is_completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""


async def test_sqlite_repository_reopened_on_same_file_keeps_todos(
    tmp_path, new_id, fixed_now
):
    path = tmp_path / "todos.db"
    added = await SqliteTodoRepository(path).add(
        Todo(id=new_id(), title="buy milk", created_at=fixed_now)
    )

    reopened = SqliteTodoRepository(path)

    assert await reopened.list_page(None, 10) == Page(items=(added,), next_cursor=None)


def test_sqlite_repository_missing_parent_directory_creates_it(tmp_path):
    path = tmp_path / "nested" / "dir" / "todos.db"

    SqliteTodoRepository(path)

    assert path.is_file()


def test_sqlite_repository_file_with_integer_ids_raises_naming_the_fix(tmp_path):
    path = tmp_path / "todos.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(INTEGER_ID_TABLE)

    with pytest.raises(RuntimeError, match=r"integer ids.*Delete the file"):
        SqliteTodoRepository(path)
