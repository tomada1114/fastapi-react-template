"""The to-do routes: thin HTTP wrappers around ``TodoService``.

Domain errors are left to propagate; the handler ``create_app`` registers
turns each into its status and a ``ProblemDetails`` body. ``responses=``
lists those statuses so the OpenAPI document shows them. Route docstrings stay
one line because FastAPI publishes them as the operation descriptions.
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter

from my_app.api.dependencies import TodoServiceDep
from my_app.api.schemas import (
    TodoCreateRequest,
    TodoPageResponse,
    TodoResponse,
    problem_responses,
)
from my_app.core.models import DEFAULT_PAGE_LIMIT

router = APIRouter(prefix="/todos", tags=["todos"])


# No Query(ge=, le=) on limit: the core owns the range, and its
# InvalidPageLimitError becomes the 422 with the one message every entry
# point shares.
@router.get("", responses=problem_responses(422))
async def list_todos(
    service: TodoServiceDep,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> TodoPageResponse:
    """List one page of to-dos, oldest first; `next_cursor` fetches the next one."""
    return TodoPageResponse.from_domain(await service.list_page(cursor, limit))


@router.post("", status_code=HTTPStatus.CREATED, responses=problem_responses(422))
async def create_todo(body: TodoCreateRequest, service: TodoServiceDep) -> TodoResponse:
    """Create a to-do from a title."""
    return TodoResponse.from_domain(await service.create(body.title))


@router.post("/{todo_id}/complete", responses=problem_responses(404))
async def complete_todo(todo_id: UUID, service: TodoServiceDep) -> TodoResponse:
    """Mark a to-do as completed."""
    return TodoResponse.from_domain(await service.complete(todo_id))


@router.delete(
    "/{todo_id}", status_code=HTTPStatus.NO_CONTENT, responses=problem_responses(404)
)
async def delete_todo(todo_id: UUID, service: TodoServiceDep) -> None:
    """Delete a to-do."""
    await service.delete(todo_id)
