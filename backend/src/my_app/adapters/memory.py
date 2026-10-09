"""A process-local to-do repository, the default store and the tests' fake."""

from __future__ import annotations

from bisect import bisect_right
from typing import TYPE_CHECKING

from my_app.adapters.cursor import decode_after, page_of
from my_app.core.errors import TodoNotFoundError

if TYPE_CHECKING:
    from uuid import UUID

    from my_app.core.models import Page, Todo


class InMemoryTodoRepository:
    """Keep to-dos in a dict for the life of the process.

    Every method runs on the event loop and never awaits, so a read-modify-write
    of the dict cannot be interleaved with another task's: a duplicate-id check
    and the insert it guards happen as one step, and no lock is needed. An
    ``await`` added between reading and writing ``_todos`` would break that.
    """

    def __init__(self) -> None:
        """Start empty."""
        self._todos: dict[UUID, Todo] = {}

    async def add(self, todo: Todo) -> Todo:
        """Store a new to-do under its own id.

        Args:
            todo: The to-do to store.

        Returns:
            ``todo``, now stored.

        Raises:
            ValueError: If a to-do with this id is already stored; it is left
                unchanged.
        """
        if todo.id in self._todos:
            msg = f"A to-do with id {todo.id} is already stored"
            raise ValueError(msg)
        self._todos[todo.id] = todo
        return todo

    async def get(self, todo_id: UUID) -> Todo:
        """Fetch one to-do.

        Args:
            todo_id: The to-do to fetch.

        Returns:
            The stored to-do.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        return self._require(todo_id)

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
        ids = sorted(self._todos)
        start = 0 if cursor is None else bisect_right(ids, decode_after(cursor))
        fetched = [self._todos[todo_id] for todo_id in ids[start : start + limit + 1]]
        return page_of(fetched, limit)

    async def update(self, todo: Todo) -> Todo:
        """Replace the stored to-do that has ``todo.id``.

        Args:
            todo: The new value.

        Returns:
            ``todo``, now stored.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        self._require(todo.id)
        self._todos[todo.id] = todo
        return todo

    async def delete(self, todo_id: UUID) -> None:
        """Remove one to-do.

        Args:
            todo_id: The to-do to remove.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        self._require(todo_id)
        del self._todos[todo_id]

    def _require(self, todo_id: UUID) -> Todo:
        """Return the stored to-do or raise ``TodoNotFoundError``."""
        try:
            return self._todos[todo_id]
        except KeyError:
            raise TodoNotFoundError(todo_id) from None
