"""The composition root: the one place adapters are wired into services.

The API gets its services from ``build_container`` and from nowhere else,
so swapping a repository is a change to this module only.
"""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

from my_app.adapters.memory import InMemoryTodoRepository
from my_app.adapters.sql.engine import make_engine
from my_app.adapters.sql.repository import SqlTodoRepository
from my_app.core.services import TodoService

if TYPE_CHECKING:
    from types import TracebackType

    from my_app.core.ports import Clock, IdFactory, TodoRepository
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


def build_container(
    settings: Settings, clock: Clock = utc_now, new_id: IdFactory = uuid.uuid7
) -> Container:
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
        new_id: Gives new to-dos their ids; ``uuid.uuid7``, whose ids ascend
            in creation order, unless a test passes a predictable factory.

    Returns:
        The services and their owned resources, ready for an entry point to
        call. Await ``aclose()``, or use it with ``async with``, when done.
    """
    resources = AsyncExitStack()
    repository = _build_repository(settings, resources)
    todos = TodoService(repository, clock, new_id)
    return Container(todos=todos, _resources=resources)


def _build_repository(settings: Settings, resources: AsyncExitStack) -> TodoRepository:
    """Return the SQL repository when a database URL is configured, else memory.

    The SQL repository's engine is the one resource the container owns: it
    connects on first use, so registering ``engine.dispose`` here leaves
    nothing open if the build fails later, under the rule ``build_container``
    states. The database must already be migrated; nothing here creates a
    table.
    """
    if settings.database_url is None:
        return InMemoryTodoRepository()
    engine = make_engine(settings.database_url)
    resources.push_async_callback(engine.dispose)
    return SqlTodoRepository(engine)
