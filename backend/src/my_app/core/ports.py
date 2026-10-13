"""The interfaces the core needs from the outside world.

They are ``Protocol`` classes so an adapter satisfies one by shape alone: it
never imports or subclasses anything from the core to plug in.

The repository port is shaped so any store can implement it, a SQL database or
a key-value store alike: the application generates ids, each method is one
access pattern, and a listing pages by an opaque cursor, never by offset.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from my_app.core.models import Page, Todo


class Clock(Protocol):
    """A source of the current time; any zero-argument callable fits.

    Injected rather than read from ``datetime.now`` so tests can fix the time.
    """

    def __call__(self) -> datetime:
        """Return the current time.

        Returns:
            A timezone-aware ``datetime``; ``Todo`` rejects a naive one.
        """


class IdFactory(Protocol):
    """A source of new ids; any zero-argument callable returning a ``UUID`` fits.

    Injected rather than called as ``uuid.uuid7`` so tests get ids they can
    predict. Production passes ``uuid.uuid7``, whose ids ascend in creation
    order within a process (and to the millisecond across processes), so a
    listing in id order is a listing in creation order.
    """

    def __call__(self) -> UUID:
        """Return an id no stored to-do has.

        Returns:
            A new ``UUID``, greater than every id this factory returned before.
        """


@runtime_checkable
class TodoRepository(Protocol):
    """Stores to-dos under the ids the application gave them.

    Every method is a coroutine, so an adapter can await its driver without
    blocking the event loop the API serves requests on. Every implementation
    must pass the shared contract suite in
    ``tests/adapters/test_repository_contract.py``. Runtime-checkable so that
    suite can also assert an adapter has every method, not only mypy.
    """

    async def add(self, todo: Todo) -> Todo:
        """Store a new to-do under its own id.

        Args:
            todo: The to-do to store; the application generated its id.

        Returns:
            ``todo``, now stored.

        Raises:
            ValueError: If a to-do with this id is already stored, which is a
                bug in the id factory, not bad input. The stored to-do is left
                unchanged: ``add`` never overwrites.
        """

    async def get(self, todo_id: UUID) -> Todo:
        """Fetch one to-do.

        Args:
            todo_id: Any id; one never stored is simply not found.

        Returns:
            The stored to-do.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """

    async def list_page(self, cursor: str | None, limit: int) -> Page[Todo]:
        """Fetch one page of to-dos in ascending id order, which is creation order.

        Args:
            cursor: ``None`` for the first page, else the ``next_cursor`` of
                the page before. A cursor stays valid after the to-do it
                points at is deleted: the page starts after that id anyway.
            limit: The most to-dos the page holds; at least 1. The service
                enforces the upper bound, so an adapter accepts any positive
                limit.

        Returns:
            The page. Its ``next_cursor`` is ``None`` exactly when no stored
            to-do follows the page's last one.

        Raises:
            InvalidCursorError: If ``cursor`` is not one this repository
                issued.
        """

    async def update(self, todo: Todo) -> Todo:
        """Replace the stored to-do that has ``todo.id``.

        Args:
            todo: The new value; its id selects what it replaces.

        Returns:
            ``todo``, now stored.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """

    async def delete(self, todo_id: UUID) -> None:
        """Remove one to-do.

        Args:
            todo_id: Any id; one never stored is simply not found.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
