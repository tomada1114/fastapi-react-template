"""The to-do domain model and the rules every to-do obeys."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from my_app.core.errors import InvalidTodoError

if TYPE_CHECKING:
    from datetime import datetime

MIN_TITLE_LENGTH = 1
MAX_TITLE_LENGTH = 200


def normalize_title(raw_title: str) -> str:
    """Strip a title and enforce its length rule.

    The rule lives here, not in an API request model, so every entry point
    rejects the same titles with the same message.

    Args:
        raw_title: The title as the user typed it.

    Returns:
        The title without surrounding whitespace.

    Raises:
        InvalidTodoError: If the stripped title is empty or too long.
    """
    title = raw_title.strip()
    if not MIN_TITLE_LENGTH <= len(title) <= MAX_TITLE_LENGTH:
        msg = (
            f"Title must be {MIN_TITLE_LENGTH}-{MAX_TITLE_LENGTH} characters "
            f"after stripping whitespace, got {len(title)}"
        )
        raise InvalidTodoError(msg)
    return title


def _check_invariants(title: str, created_at: datetime) -> None:
    """Enforce the rules every draft and stored to-do obeys.

    Raises:
        InvalidTodoError: If the title is not already normalized.
        ValueError: If ``created_at`` is naive. That is a bug in a clock or
            an adapter, not bad user input, so it is not a domain error.
    """
    if normalize_title(title) != title:
        msg = "Title must not have surrounding whitespace; pass it through normalize_title"
        raise InvalidTodoError(msg)
    if created_at.utcoffset() is None:
        msg = f"created_at must be timezone-aware, got {created_at.isoformat()}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TodoDraft:
    """A validated to-do that the repository has not yet assigned an id to."""

    title: str
    created_at: datetime

    def __post_init__(self) -> None:
        """Refuse to exist in a state no rule allows.

        Raises:
            InvalidTodoError: If the title is unnormalized or out of range.
            ValueError: If ``created_at`` is naive.
        """
        _check_invariants(self.title, self.created_at)


@dataclass(frozen=True, slots=True)
class Todo:
    """A stored to-do.

    Frozen so a change is always a new value handed back to the repository,
    never an in-place edit that a repository could silently miss.
    """

    id: int
    title: str
    created_at: datetime
    is_completed: bool = False

    def __post_init__(self) -> None:
        """Refuse to exist in a state no rule allows.

        Checked again here, not only on the draft, because adapters rebuild
        to-dos from storage and ``dataclasses.replace`` builds new ones.

        Raises:
            InvalidTodoError: If the title is unnormalized or out of range.
            ValueError: If ``created_at`` is naive.
        """
        _check_invariants(self.title, self.created_at)
