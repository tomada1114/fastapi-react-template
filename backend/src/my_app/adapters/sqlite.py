"""A to-do repository backed by a SQLite file, using only the stdlib driver."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from my_app.adapters.cursor import decode_after, page_of
from my_app.core.errors import TodoNotFoundError
from my_app.core.models import Todo

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from my_app.core.models import Page

# The id is the canonical UUID string: lowercase, fixed-width hex sorts the way
# the UUIDs do, so ORDER BY id is id order.
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    is_completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""
# Spelled out in full rather than assembled, so no query string is ever built
# at run time; _to_todo relies on this column order.
_SELECT_ONE = "SELECT id, title, is_completed, created_at FROM todos WHERE id = ?"
_SELECT_FIRST_PAGE = (
    "SELECT id, title, is_completed, created_at FROM todos ORDER BY id LIMIT ?"
)
_SELECT_PAGE_AFTER = (
    "SELECT id, title, is_completed, created_at FROM todos "
    "WHERE id > ? ORDER BY id LIMIT ?"
)
_INSERT = "INSERT INTO todos (id, title, is_completed, created_at) VALUES (?, ?, ?, ?)"
_ID_COLUMN_TYPE = "SELECT type FROM pragma_table_info('todos') WHERE name = 'id'"
_UPDATE = "UPDATE todos SET title = ?, is_completed = ?, created_at = ? WHERE id = ?"
_DELETE = "DELETE FROM todos WHERE id = ?"

type _Row = tuple[str, str, int, str]


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

        Raises:
            RuntimeError: If the file holds the integer-id table an earlier
                version of this adapter created. Nothing migrates it.
        """
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            connection.execute(_CREATE_TABLE)
            (id_type,) = connection.execute(_ID_COLUMN_TYPE).fetchone()
        if id_type != "TEXT":
            msg = (
                f"{path} holds a to-do table with integer ids from an earlier "
                "version; this adapter does not migrate it. Delete the file to "
                "start over."
            )
            raise RuntimeError(msg)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits on success, rolls back on error, then closes.

        ``sqlite3.Connection``'s own context manager only ends the transaction,
        so ``closing`` is what releases the file handle.
        """
        with closing(sqlite3.connect(self._path)) as connection, connection:
            yield connection

    async def add(self, todo: Todo) -> Todo:
        """Insert a new to-do under its own id.

        Args:
            todo: The to-do to store.

        Returns:
            ``todo``, now stored.

        Raises:
            ValueError: If a to-do with this id is already stored; the primary
                key refuses the row and the stored one is left unchanged.
        """
        await asyncio.to_thread(self._insert, todo)
        return todo

    async def get(self, todo_id: UUID) -> Todo:
        """Fetch one to-do.

        Args:
            todo_id: Any id; one never stored is simply not found.

        Returns:
            The stored to-do.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        row = await asyncio.to_thread(self._select_one, todo_id)
        if row is None:
            raise TodoNotFoundError(todo_id)
        return _to_todo(row)

    async def list_page(self, cursor: str | None, limit: int) -> Page[Todo]:
        """Fetch one page of to-dos in ascending id order.

        Args:
            cursor: ``None`` for the first page, else a ``next_cursor``.
            limit: The most to-dos the page holds.

        Returns:
            The page, with a cursor when more to-dos follow it.

        Raises:
            InvalidCursorError: If ``cursor`` is not one this store issued.
        """
        after = None if cursor is None else decode_after(cursor)
        rows = await asyncio.to_thread(self._select_page, after, limit + 1)
        return page_of([_to_todo(row) for row in rows], limit)

    async def update(self, todo: Todo) -> Todo:
        """Replace the stored to-do that has ``todo.id``.

        Args:
            todo: The new value.

        Returns:
            ``todo``, now stored.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        if await asyncio.to_thread(self._update_row, todo) == 0:
            raise TodoNotFoundError(todo.id)
        return todo

    async def delete(self, todo_id: UUID) -> None:
        """Remove one to-do.

        Args:
            todo_id: Any id; one never stored is simply not found.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        if await asyncio.to_thread(self._delete_row, todo_id) == 0:
            raise TodoNotFoundError(todo_id)

    # The blocking halves below run in a worker thread, one connection each.

    def _insert(self, todo: Todo) -> None:
        """Insert a row, translating a duplicate id into ``ValueError``."""
        try:
            with self._transaction() as connection:
                connection.execute(
                    _INSERT,
                    (
                        str(todo.id),
                        todo.title,
                        todo.is_completed,
                        todo.created_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            msg = f"A to-do with id {todo.id} is already stored"
            raise ValueError(msg) from error

    def _select_page(self, after: UUID | None, count: int) -> list[_Row]:
        """Return up to ``count`` rows in id order, after ``after`` when given."""
        with self._transaction() as connection:
            if after is None:
                rows: list[_Row] = connection.execute(
                    _SELECT_FIRST_PAGE, (count,)
                ).fetchall()
            else:
                rows = connection.execute(
                    _SELECT_PAGE_AFTER, (str(after), count)
                ).fetchall()
        return rows

    def _select_one(self, todo_id: UUID) -> _Row | None:
        """Return the row with this id, or ``None`` when there is none."""
        with self._transaction() as connection:
            row: _Row | None = connection.execute(
                _SELECT_ONE, (str(todo_id),)
            ).fetchone()
        return row

    def _update_row(self, todo: Todo) -> int:
        """Overwrite the row with ``todo.id`` and return how many rows changed."""
        with self._transaction() as connection:
            cursor = connection.execute(
                _UPDATE,
                (
                    todo.title,
                    todo.is_completed,
                    todo.created_at.isoformat(),
                    str(todo.id),
                ),
            )
        return cursor.rowcount

    def _delete_row(self, todo_id: UUID) -> int:
        """Delete the row with this id and return how many rows went."""
        with self._transaction() as connection:
            cursor = connection.execute(_DELETE, (str(todo_id),))
        return cursor.rowcount


def _to_todo(row: _Row) -> Todo:
    """Rebuild a domain to-do from a row in the ``_SELECT_*`` column order."""
    todo_id, title, is_completed, created_at = row
    return Todo(
        id=UUID(todo_id),
        title=title,
        created_at=datetime.fromisoformat(created_at),
        is_completed=bool(is_completed),
    )
