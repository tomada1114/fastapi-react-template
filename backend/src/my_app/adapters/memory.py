"""A process-local to-do repository, the default store and the tests' fake."""

from __future__ import annotations

from typing import TYPE_CHECKING

from my_app.core.errors import TodoNotFoundError
from my_app.core.models import Todo

if TYPE_CHECKING:
    from my_app.core.models import TodoDraft


class InMemoryTodoRepository:
    """Keep to-dos in a dict for the life of the process.

    Every method runs on the event loop and never awaits, so a read-modify-write
    of the dict cannot be interleaved with another task's: two concurrent creates
    never receive the same id, and no lock is needed. An ``await`` added between
    reading and writing ``_todos`` or ``_last_id`` would break that.
    """

    def __init__(self) -> None:
        """Start empty, with ids counting up from 1."""
        self._todos: dict[int, Todo] = {}
        self._last_id = 0

    async def add(self, draft: TodoDraft) -> Todo:
        """Store a draft under the next id.

        Args:
            draft: The validated to-do to store.

        Returns:
            The stored to-do. The counter never goes back, so a deleted id is
            never reused.
        """
        self._last_id += 1
        todo = Todo(id=self._last_id, title=draft.title, created_at=draft.created_at)
        self._todos[todo.id] = todo
        return todo

    async def get(self, todo_id: int) -> Todo:
        """Fetch one to-do.

        Args:
            todo_id: The to-do to fetch.

        Returns:
            The stored to-do.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        return self._require(todo_id)

    async def list_all(self) -> list[Todo]:
        """Fetch every to-do.

        Returns:
            The to-dos in ascending id order.
        """
        return [self._todos[todo_id] for todo_id in sorted(self._todos)]

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

    async def delete(self, todo_id: int) -> None:
        """Remove one to-do.

        Args:
            todo_id: The to-do to remove.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        self._require(todo_id)
        del self._todos[todo_id]

    def _require(self, todo_id: int) -> Todo:
        """Return the stored to-do or raise ``TodoNotFoundError``."""
        try:
            return self._todos[todo_id]
        except KeyError:
            raise TodoNotFoundError(todo_id) from None
