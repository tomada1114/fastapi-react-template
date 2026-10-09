"""The composition root: the one place adapters are wired into services.

The API gets its services from ``build_container`` and from nowhere else,
so swapping a repository is a change to this module only.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

from my_app.adapters.memory import InMemoryTodoRepository
from my_app.adapters.sqlite import SqliteTodoRepository
from my_app.core.services import TodoService

if TYPE_CHECKING:
    from types import TracebackType

    from my_app.core.ports import Clock, TodoRepository
    from my_app.settings import Settings


@dataclass(frozen=True, slots=True)
class Container:
    """The services an entry point may call, built once per process."""

    todos: TodoService
    _resources: AsyncExitStack = field(
        default_factory=AsyncExitStack, repr=False, compare=False
    )

    async def aclose(self) -> None:
        """Release every resource the composition root registered, at most once."""
        await self._resources.aclose()

    async def __aenter__(self) -> Self:
        """Keep ownership until the surrounding context exits."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Forward exception details and suppression to registered resources."""
        return bool(await self._resources.__aexit__(exc_type, exc_value, traceback))


def utc_now() -> datetime:
    """Return the current time in UTC; the production ``Clock``."""
    return datetime.now(tz=UTC)


def build_container(settings: Settings, clock: Clock = utc_now) -> Container:
    """Choose the adapters ``settings`` asks for and wire them into services.

    A plain function, not a coroutine: nothing here awaits, and a bad setting
    must still fail in ``create_app``, before any request is served. Being
    synchronous, it cannot await the cleanup of a partly built stack, so a build
    that raises leaves registered callbacks un-run. An adapter builder therefore
    registers cleanup with ``resources.push_async_callback(...)`` only for an
    object that opens nothing when constructed (an engine that connects on
    first use, say), so an error later in the build leaves nothing open.

    Args:
        settings: Selects the repository through ``database_url``.
        clock: Stamps new to-dos; tests pass a fixed one.

    Returns:
        The services and their owned resources, ready for an entry point to
        call. Await ``aclose()``, or use it with ``async with``, when done.
    """
    resources = AsyncExitStack()
    repository = _build_repository(settings, resources)
    todos = TodoService(repository, clock)
    return Container(todos=todos, _resources=resources)


def _build_repository(settings: Settings, _resources: AsyncExitStack) -> TodoRepository:
    """Return the SQLite repository when a path is configured, else memory.

    Neither current adapter holds a resource between calls. A resource-holding
    adapter registers its cleanup on ``_resources`` before returning, under the
    rule ``build_container`` states.
    """
    if (path := settings.sqlite_path) is not None:
        return SqliteTodoRepository(path)
    return InMemoryTodoRepository()
