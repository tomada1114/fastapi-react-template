"""Request and response bodies: the API's wire format, kept apart from the domain.

A domain field can be renamed without breaking a client, because only the
``from_domain`` classmethods map one onto the other.
"""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import BaseModel

if TYPE_CHECKING:
    from my_app.core.models import Page, Todo


PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemFieldError(BaseModel):
    """A request parsing failure, without raw input or server context."""

    loc: list[str | int]
    message: str
    type: str


class ProblemDetails(BaseModel):
    """RFC 9457 error body with a stable application code."""

    type: Literal["about:blank"] = "about:blank"
    title: str
    status: int
    detail: str
    code: str
    request_id: str
    errors: list[ProblemFieldError] | None = None


def status_phrase(status: int) -> str:
    """Keep valid extension statuses usable when the stdlib has no phrase."""
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Unknown Status"


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Register error models; the factory publishes their Problem media type.

    ``Any`` matches FastAPI's ``responses=`` declaration type.
    """
    return {
        status: {"model": ProblemDetails, "description": status_phrase(status)}
        for status in statuses
    }


class HealthResponse(BaseModel):
    """Body of ``GET /healthz``."""

    status: Literal["ok"] = "ok"


class TodoCreateRequest(BaseModel):
    """Body of ``POST /api/todos``.

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
    """Body of ``GET /api/todos``: one page of to-dos, oldest first.

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
