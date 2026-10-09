"""Domain errors, each a subclass of one package base exception.

An entry point translates these into its own vocabulary (the API into an
HTTP status), so the core never needs to know which one called it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class AppError(Exception):
    """Base class for every error the application raises on purpose.

    Catching it separates an expected domain failure, which an entry point
    reports to its user, from a bug, which should surface as a traceback.
    """


class TodoNotFoundError(AppError):
    """Raised when no to-do has the requested id."""

    def __init__(self, todo_id: UUID) -> None:
        """Keep the missing id so callers can report it without parsing text.

        The id is the exception's only argument, so pickling (as process
        pools and some task queues do) rebuilds an equal error.

        Args:
            todo_id: The id that matched no stored to-do.
        """
        super().__init__(todo_id)
        self.todo_id = todo_id

    def __str__(self) -> str:
        """Return the message entry points show their users.

        A ``UUID`` formats as its canonical hyphenated form, whatever spelling
        the caller parsed it from.
        """
        return f"To-do {self.todo_id} not found"


class InvalidTodoError(AppError):
    """Raised when input would create a to-do that breaks a domain rule."""


class InvalidCursorError(AppError):
    """Raised when a page cursor is not one the store issued.

    The message never echoes the cursor: it is client input of any length.
    """


class InvalidPageLimitError(AppError):
    """Raised when a page would hold fewer than one item or more than the maximum."""
