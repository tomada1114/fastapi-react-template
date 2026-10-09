"""FastAPI dependencies that hand routes the services from the composition root."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from my_app.core.services import TodoService

if TYPE_CHECKING:
    from my_app.composition import Container


def get_todo_service(request: Request) -> TodoService:
    """Hand a route the to-do service from the container ``create_app`` stored.

    Reading it from the app, not a module global, lets every ``create_app``
    call — one per test — own an independent store.

    Args:
        request: The current request, which carries its application.

    Returns:
        The application's ``TodoService``.
    """
    container: Container = request.app.state.container
    return container.todos


TodoServiceDep = Annotated[TodoService, Depends(get_todo_service)]
"""Declare a route parameter with this type to receive the ``TodoService``."""
