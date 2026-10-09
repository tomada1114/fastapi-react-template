"""Use cases: the operations every entry point offers on to-dos."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from my_app.core.models import (
    DEFAULT_PAGE_LIMIT,
    Todo,
    check_page_limit,
    normalize_title,
)

if TYPE_CHECKING:
    from uuid import UUID

    from my_app.core.models import Page
    from my_app.core.ports import Clock, IdFactory, TodoRepository


class TodoService:
    """Create, list, complete, and delete to-dos.

    The API calls this class and nothing below it, so a rule added here holds
    for every entry point.
    """

    def __init__(
        self, repository: TodoRepository, clock: Clock, new_id: IdFactory
    ) -> None:
        """Bind the service to its storage, its source of time, and its ids.

        Args:
            repository: Where to-dos are stored.
            clock: Stamps ``created_at``; injected so tests can fix the time.
            new_id: Gives each new to-do its id; injected so tests can predict
                it. No store assigns an id.
        """
        self._repository = repository
        self._clock = clock
        self._new_id = new_id

    async def create(self, raw_title: str) -> Todo:
        """Store a new, open to-do.

        Args:
            raw_title: The title as the user typed it; surrounding whitespace
                is stripped before the length rule applies.

        Returns:
            The stored to-do, with its new id and ``created_at`` set.

        Raises:
            InvalidTodoError: If the stripped title is empty or too long.
        """
        title = normalize_title(raw_title)
        todo = Todo(id=self._new_id(), title=title, created_at=self._clock())
        return await self._repository.add(todo)

    async def list_page(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_LIMIT
    ) -> Page[Todo]:
        """List one page of to-dos, oldest first.

        Args:
            cursor: ``None`` for the first page, else the ``next_cursor`` of
                the page before.
            limit: The most to-dos the page holds.

        Returns:
            The page; ``Page(items=(), next_cursor=None)`` when there are none.

        Raises:
            InvalidPageLimitError: If ``limit`` is below 1 or above
                ``MAX_PAGE_LIMIT``.
            InvalidCursorError: If ``cursor`` is not one a page returned.
        """
        check_page_limit(limit)
        return await self._repository.list_page(cursor, limit)

    async def complete(self, todo_id: UUID) -> Todo:
        """Mark a to-do as completed.

        Completing it again changes nothing, so a retried request is safe.

        Args:
            todo_id: The to-do to complete.

        Returns:
            The completed to-do.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        todo = await self._repository.get(todo_id)
        if todo.is_completed:
            return todo
        return await self._repository.update(replace(todo, is_completed=True))

    async def delete(self, todo_id: UUID) -> None:
        """Remove a to-do.

        Args:
            todo_id: The to-do to remove.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        await self._repository.delete(todo_id)
