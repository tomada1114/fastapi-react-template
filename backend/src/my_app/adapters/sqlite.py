"""A to-do repository backed by a SQLite file, using only the stdlib driver."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from typing import TYPE_CHECKING

from my_app.core.errors import TodoNotFoundError
from my_app.core.models import Todo

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from my_app.core.models import TodoDraft

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    is_completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""
# Spelled out in full rather than assembled, so no query string is ever built
# at run time; _to_todo relies on this column order.
_SELECT_ONE = "SELECT id, title, is_completed, created_at FROM todos WHERE id = ?"
_SELECT_ALL = "SELECT id, title, is_completed, created_at FROM todos ORDER BY id"
_INSERT = "INSERT INTO todos (title, created_at) VALUES (?, ?) RETURNING id"
_UPDATE = "UPDATE todos SET title = ?, is_completed = ?, created_at = ? WHERE id = ?"
_DELETE = "DELETE FROM todos WHERE id = ?"
# SQLite stores INTEGER as signed 64-bit; binding anything outside raises
# OverflowError, so such an id is answered as "not found" before any query.
SQLITE_MIN_INTEGER = -(2**63)
SQLITE_MAX_INTEGER = 2**63 - 1


class SqliteTodoRepository:
    """Store to-dos in one SQLite table.

    The stdlib driver blocks, so each method runs its database work in a worker
    thread through ``asyncio.to_thread`` and the event loop keeps serving other
    requests meanwhile. Each call opens and closes its own connection in that
    thread: ``sqlite3`` refuses a connection used from a thread other than the
    one that opened it, and the worker threads differ from call to call.
    """

    def __init__(self, path: Path) -> None:
        """Create the database file, its directory, and the table if missing.

        Synchronous on purpose: ``build_container`` builds this at startup,
        before any event loop serves a request, and must fail there on a bad
        path.

        Args:
            path: The SQLite file; created on first use.
        """
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            connection.execute(_CREATE_TABLE)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits on success, rolls back on error, then closes.

        ``sqlite3.Connection``'s own context manager only ends the transaction,
        so ``closing`` is what releases the file handle.
        """
        with closing(sqlite3.connect(self._path)) as connection, connection:
            yield connection

    async def add(self, draft: TodoDraft) -> Todo:
        """Insert a draft.

        Args:
            draft: The validated to-do to store.

        Returns:
            The stored to-do. ``AUTOINCREMENT`` keeps SQLite from reusing the
            id of a deleted row.
        """
        todo_id = await asyncio.to_thread(self._insert, draft)
        return Todo(id=todo_id, title=draft.title, created_at=draft.created_at)

    async def get(self, todo_id: int) -> Todo:
        """Fetch one to-do.

        Args:
            todo_id: Any integer, including one SQLite cannot store.

        Returns:
            The stored to-do.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        _require_storable_id(todo_id)
        row = await asyncio.to_thread(self._select_one, todo_id)
        if row is None:
            raise TodoNotFoundError(todo_id)
        return _to_todo(row)

    async def list_all(self) -> list[Todo]:
        """Fetch every to-do.

        Returns:
            The to-dos in ascending id order.
        """
        rows = await asyncio.to_thread(self._select_all)
        return [_to_todo(row) for row in rows]

    async def update(self, todo: Todo) -> Todo:
        """Replace the stored to-do that has ``todo.id``.

        Args:
            todo: The new value.

        Returns:
            ``todo``, now stored.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        _require_storable_id(todo.id)
        if await asyncio.to_thread(self._update_row, todo) == 0:
            raise TodoNotFoundError(todo.id)
        return todo

    async def delete(self, todo_id: int) -> None:
        """Remove one to-do.

        Args:
            todo_id: Any integer, including one SQLite cannot store.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        _require_storable_id(todo_id)
        if await asyncio.to_thread(self._delete_row, todo_id) == 0:
            raise TodoNotFoundError(todo_id)

    # The blocking halves below run in a worker thread, one connection each.

    def _insert(self, draft: TodoDraft) -> int:
        """Insert a row and return the id SQLite assigned it."""
        with self._transaction() as connection:
            (todo_id,) = connection.execute(
                _INSERT, (draft.title, draft.created_at.isoformat())
            ).fetchone()
        return int(todo_id)

    def _select_one(self, todo_id: int) -> tuple[int, str, int, str] | None:
        """Return the row with this id, or ``None`` when there is none."""
        with self._transaction() as connection:
            row: tuple[int, str, int, str] | None = connection.execute(
                _SELECT_ONE, (todo_id,)
            ).fetchone()
        return row

    def _select_all(self) -> list[tuple[int, str, int, str]]:
        """Return every row in id order."""
        with self._transaction() as connection:
            rows: list[tuple[int, str, int, str]] = connection.execute(
                _SELECT_ALL
            ).fetchall()
        return rows

    def _update_row(self, todo: Todo) -> int:
        """Overwrite the row with ``todo.id`` and return how many rows changed."""
        with self._transaction() as connection:
            cursor = connection.execute(
                _UPDATE,
                (todo.title, todo.is_completed, todo.created_at.isoformat(), todo.id),
            )
        return cursor.rowcount

    def _delete_row(self, todo_id: int) -> int:
        """Delete the row with this id and return how many rows went."""
        with self._transaction() as connection:
            cursor = connection.execute(_DELETE, (todo_id,))
        return cursor.rowcount


def _require_storable_id(todo_id: int) -> None:
    """Answer an id SQLite cannot even bind the way the in-memory store does.

    Raises:
        TodoNotFoundError: If the id is outside SQLite's signed 64-bit range,
            where no row can exist.
    """
    if not SQLITE_MIN_INTEGER <= todo_id <= SQLITE_MAX_INTEGER:
        raise TodoNotFoundError(todo_id)


def _to_todo(row: tuple[int, str, int, str]) -> Todo:
    """Rebuild a domain to-do from a row in the ``_SELECT_*`` column order."""
    todo_id, title, is_completed, created_at = row
    return Todo(
        id=todo_id,
        title=title,
        created_at=datetime.fromisoformat(created_at),
        is_completed=bool(is_completed),
    )
