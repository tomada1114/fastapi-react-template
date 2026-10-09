"""Request and response bodies: the API's wire format, kept apart from the domain.

A domain field can be renamed without breaking a client, because only the
``from_domain`` classmethods map one onto the other.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel

if TYPE_CHECKING:
    from my_app.core.models import Page, Todo


class ErrorResponse(BaseModel):
    """Body of every error a domain rule produces (404, 422, and 400).

    ``detail`` is a single message here. FastAPI's own 422 for a request that
    does not parse (a missing field, an id that is not a UUID, a non-integer
    limit) keeps its list-shaped ``detail`` instead, so a client tells the two
    apart by type.
    """

    detail: str


class HealthResponse(BaseModel):
    """Body of ``GET /healthz``."""

    status: Literal["ok"] = "ok"


class TodoCreateRequest(BaseModel):
    """Body of ``POST /todos``.

    The title is left unconstrained here on purpose: the core owns the length
    rule, and its ``InvalidTodoError`` becomes the 422 response.
    """

    title: str


class TodoResponse(BaseModel):
    """A to-do as clients see it; ``id`` travels as the canonical UUID string."""

    id: UUID
    title: str
    completed: bool
    created_at: datetime

    @classmethod
    def from_domain(cls, todo: Todo) -> TodoResponse:
        """Map a domain to-do onto the wire format."""
        return cls(
            id=todo.id,
            title=todo.title,
            completed=todo.is_completed,
            created_at=todo.created_at,
        )


class TodoPageResponse(BaseModel):
    """Body of ``GET /todos``: one page of to-dos, oldest first.

    ``next_cursor`` is opaque: a client passes it back as ``cursor`` to fetch
    the next page, and it is ``null`` on the last page.
    """

    items: list[TodoResponse]
    next_cursor: str | None

    @classmethod
    def from_domain(cls, page: Page[Todo]) -> TodoPageResponse:
        """Map a domain page onto the wire format."""
        return cls(
            items=[TodoResponse.from_domain(todo) for todo in page.items],
            next_cursor=page.next_cursor,
        )
