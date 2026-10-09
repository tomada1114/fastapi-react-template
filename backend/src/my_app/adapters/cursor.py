"""The page cursor the in-memory and SQLite repositories share.

A cursor names the last id of the page before, so the next page is every
to-do with a greater id, and it stays valid when that to-do is deleted. It is
opaque to the core and to clients: a store whose own paging token differs
keeps that token inside its adapter.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING
from uuid import UUID

from my_app.core.errors import InvalidCursorError
from my_app.core.models import Page

if TYPE_CHECKING:
    from collections.abc import Sequence

    from my_app.core.models import Todo

INVALID_CURSOR_MESSAGE = (
    "Invalid page cursor: pass the next_cursor of an earlier page, "
    "or no cursor for the first page"
)
_UUID_BYTES = 16


def encode_after(todo_id: UUID) -> str:
    """Return the cursor of the page that starts after ``todo_id``.

    Args:
        todo_id: The last id of the page before.

    Returns:
        The 16 id bytes as URL-safe base64 without padding: 22 characters a
        client can pass in a query string unescaped.
    """
    return base64.urlsafe_b64encode(todo_id.bytes).rstrip(b"=").decode("ascii")


def decode_after(cursor: str) -> UUID:
    """Return the id a cursor from ``encode_after`` names.

    Accepts exactly the strings ``encode_after`` returns, so one id has one
    cursor: no padding, no standard-alphabet characters, no stray bits.

    Args:
        cursor: A ``next_cursor`` a page returned.

    Returns:
        The id the page before ended on.

    Raises:
        InvalidCursorError: If ``encode_after`` could not have returned
            ``cursor``.
    """
    try:
        # A str with non-ASCII characters raises ValueError too.
        raw = base64.urlsafe_b64decode(cursor + "==")
    except ValueError:
        raise InvalidCursorError(INVALID_CURSOR_MESSAGE) from None
    if len(raw) != _UUID_BYTES:
        raise InvalidCursorError(INVALID_CURSOR_MESSAGE)
    todo_id = UUID(bytes=raw)
    if encode_after(todo_id) != cursor:
        raise InvalidCursorError(INVALID_CURSOR_MESSAGE)
    return todo_id


def page_of(fetched: Sequence[Todo], limit: int) -> Page[Todo]:
    """Build a page from up to ``limit + 1`` to-dos fetched in id order.

    Fetching one more than the page holds tells whether another page follows
    without a second query.

    Args:
        fetched: The to-dos after the cursor, ascending by id, at most
            ``limit + 1`` of them.
        limit: The most to-dos the page holds.

    Returns:
        The first ``limit`` to-dos, with a cursor after the last of them when
        ``fetched`` held more.
    """
    items = tuple(fetched[:limit])
    next_cursor = encode_after(items[-1].id) if len(fetched) > limit else None
    return Page(items=items, next_cursor=next_cursor)
