"""The interfaces the core needs from the outside world.

They are ``Protocol`` classes so an adapter satisfies one by shape alone: it
never imports or subclasses anything from the core to plug in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from my_app.core.models import Todo, TodoDraft


class Clock(Protocol):
    """A source of the current time; any zero-argument callable fits.

    Injected rather than read from ``datetime.now`` so tests can fix the time.
    """

    def __call__(self) -> datetime:
        """Return the current time.

        Returns:
            A timezone-aware ``datetime``; ``Todo`` rejects a naive one.
        """


@runtime_checkable
class TodoRepository(Protocol):
    """Stores to-dos and assigns their ids.

    Every implementation must pass the shared contract suite in
    ``tests/adapters/test_repository_contract.py``. Runtime-checkable so that
    suite can also assert an adapter has every method, not only mypy.
    """

    def add(self, draft: TodoDraft) -> Todo:
        """Store a draft under a new id.

        Args:
            draft: The validated to-do to store.

        Returns:
            The stored to-do. Ids increase and are never reused, even after a
            delete, so a stale id can never name a different to-do.
        """

    def get(self, todo_id: int) -> Todo:
        """Fetch one to-do.

        Args:
            todo_id: Any integer; one never assigned is simply not found.

        Returns:
            The stored to-do.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """

    def list_all(self) -> list[Todo]:
        """Fetch every to-do.

        Returns:
            The to-dos in ascending id order, which is creation order.
        """

    def update(self, todo: Todo) -> Todo:
        """Replace the stored to-do that has ``todo.id``.

        Args:
            todo: The new value; its id selects what it replaces.

        Returns:
            ``todo``, now stored.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """

    def delete(self, todo_id: int) -> None:
        """Remove one to-do.

        Args:
            todo_id: Any integer; one never assigned is simply not found.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
