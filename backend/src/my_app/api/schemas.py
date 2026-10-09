"""Request and response bodies: the API's wire format, kept apart from the domain.

A domain field can be renamed without breaking a client, because only
``TodoResponse.from_domain`` maps one onto the other.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from my_app.core.models import Todo


class ErrorResponse(BaseModel):
    """Body of every error a domain rule produces (404, 422, and 400).

    ``detail`` is a single message here. FastAPI's own 422 for a request that
    does not parse (a missing field, a non-integer id) keeps its list-shaped
    ``detail`` instead, so a client tells the two apart by type.
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
    """A to-do as clients see it."""

    id: int
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
