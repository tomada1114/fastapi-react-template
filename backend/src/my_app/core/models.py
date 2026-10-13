"""The to-do domain model, the rules every to-do obeys, and the page of a listing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from my_app.core.errors import InvalidPageLimitError, InvalidTodoError

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

MIN_TITLE_LENGTH = 1
MAX_TITLE_LENGTH = 200
# Template defaults: an app changes the constants, and every entry point follows.
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100


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


def check_page_limit(limit: int) -> None:
    """Enforce how many items one page may hold.

    The rule lives here, not in a route's query parameter, so every entry point
    rejects the same limits with the same message.

    Args:
        limit: The number of items a caller asked for.

    Raises:
        InvalidPageLimitError: If ``limit`` is below 1 or above ``MAX_PAGE_LIMIT``.
    """
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        msg = f"Page limit must be 1-{MAX_PAGE_LIMIT}, got {limit}"
        raise InvalidPageLimitError(msg)


@dataclass(frozen=True, slots=True)
class Todo:
    """A to-do, with the id the application gave it when it was created.

    Frozen so a change is always a new value handed back to the repository,
    never an in-place edit that a repository could silently miss.
    """

    id: UUID
    title: str
    created_at: datetime
    is_completed: bool = False

    def __post_init__(self) -> None:
        """Refuse to exist in a state no rule allows.

        Checked on every construction, because adapters rebuild to-dos from
        storage and ``dataclasses.replace`` builds new ones.

        Raises:
            InvalidTodoError: If the title is not already normalized, as
                ``normalize_title`` returns it.
            ValueError: If ``created_at`` is naive. That is a bug in a clock or
                an adapter, not bad user input, so it is not a domain error.
        """
        if normalize_title(self.title) != self.title:
            msg = "Title must not have surrounding whitespace; pass it through normalize_title"
            raise InvalidTodoError(msg)
        if self.created_at.utcoffset() is None:
            msg = (
                f"created_at must be timezone-aware, got {self.created_at.isoformat()}"
            )
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of a listing, and where the next one starts.

    Attributes:
        items: The page's items, in the order the listing promises.
        next_cursor: Opaque to every caller; pass it back to fetch the next
            page. ``None`` exactly when no stored item follows this page.
    """

    items: tuple[T, ...]
    next_cursor: str | None
