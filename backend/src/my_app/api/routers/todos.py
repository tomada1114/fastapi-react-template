"""The to-do routes: thin HTTP wrappers around ``TodoService``.

Domain errors are left to propagate; the handler ``create_app`` registers
turns each into its status and an ``ErrorResponse`` body. ``responses=``
lists those statuses so the OpenAPI document shows them. Route docstrings stay
one line because FastAPI publishes them as the operation descriptions.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import APIRouter

from my_app.api.dependencies import TodoServiceDep
from my_app.api.schemas import ErrorResponse, TodoCreateRequest, TodoResponse

# Any: FastAPI's own type for `responses=` values is dict[str, Any].
_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    HTTPStatus.NOT_FOUND: {"model": ErrorResponse, "description": "No such to-do"},
}
_INVALID_TITLE: dict[int | str, dict[str, Any]] = {
    HTTPStatus.UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": (
            "The title is empty or too long after trimming. A body that does "
            "not parse at all gets FastAPI's list-shaped `detail` instead."
        ),
    },
}

router = APIRouter(prefix="/todos", tags=["todos"])


@router.get("")
async def list_todos(service: TodoServiceDep) -> list[TodoResponse]:
    """List every to-do, oldest first; an empty store returns `[]`."""
    return [TodoResponse.from_domain(todo) for todo in await service.list_todos()]


@router.post("", status_code=HTTPStatus.CREATED, responses=_INVALID_TITLE)
async def create_todo(body: TodoCreateRequest, service: TodoServiceDep) -> TodoResponse:
    """Create a to-do from a title."""
    return TodoResponse.from_domain(await service.create(body.title))


@router.post("/{todo_id}/complete", responses=_NOT_FOUND)
async def complete_todo(todo_id: int, service: TodoServiceDep) -> TodoResponse:
    """Mark a to-do as completed."""
    return TodoResponse.from_domain(await service.complete(todo_id))


@router.delete("/{todo_id}", status_code=HTTPStatus.NO_CONTENT, responses=_NOT_FOUND)
async def delete_todo(todo_id: int, service: TodoServiceDep) -> None:
    """Delete a to-do."""
    await service.delete(todo_id)
