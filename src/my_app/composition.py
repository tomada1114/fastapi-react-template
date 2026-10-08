"""The composition root: the one place adapters are wired into services.

Both entry points get their services from ``build_container`` and from
nowhere else, so swapping a repository is a change to this module only.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

from my_app.adapters.closed_llm import ClosedLlm
from my_app.adapters.memory import InMemoryTodoRepository
from my_app.adapters.sqlite import SqliteTodoRepository
from my_app.core.errors import LlmConfigurationError
from my_app.core.services import TodoService

if TYPE_CHECKING:
    from types import TracebackType

    from my_app.core.ports import Clock, LlmPort, TodoRepository
    from my_app.settings import Settings


@dataclass(frozen=True, slots=True)
class Container:
    """The services an entry point may call, built once per process."""

    todos: TodoService
    _resources: ExitStack = field(default_factory=ExitStack, repr=False, compare=False)

    def close(self) -> None:
        """Release every resource the composition root registered, at most once."""
        self._resources.close()

    def __enter__(self) -> Self:
        """Keep ownership until the surrounding context exits."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Forward exception details and suppression to registered resources."""
        return bool(self._resources.__exit__(exc_type, exc_value, traceback))


def utc_now() -> datetime:
    """Return the current time in UTC; the production ``Clock``."""
    return datetime.now(tz=UTC)


def build_container(settings: Settings, clock: Clock = utc_now) -> Container:
    """Choose the adapters ``settings`` asks for and wire them into services.

    Args:
        settings: Selects the repository through ``database_url``.
        clock: Stamps new to-dos; tests pass a fixed one.

    Returns:
        The services and their owned resources, ready for an entry point to
        call. Close the container, or use it as a context manager, when done.
    """
    with ExitStack() as resources:
        repository = _build_repository(settings, resources)
        todos = TodoService(repository, clock)
        return Container(todos=todos, _resources=resources.pop_all())


def _build_repository(settings: Settings, _resources: ExitStack) -> TodoRepository:
    """Return the SQLite repository when a path is configured, else memory.

    Neither current adapter holds a resource between calls. A resource-holding
    adapter registers its cleanup on ``_resources`` before returning.
    """
    if (path := settings.sqlite_path) is not None:
        return SqliteTodoRepository(path)
    return InMemoryTodoRepository()


def build_llm(settings: Settings) -> LlmPort:
    """Return the ``LlmPort`` the settings ask for: closed unless a key is set.

    Not wired into ``Container``: no service consumes an LLM yet. A service
    that does takes ``llm: LlmPort`` in its constructor, and
    ``build_container`` passes it ``build_llm(settings)``.

    Args:
        settings: Opens the LLM through ``openrouter_api_key``, and picks the
            default model through ``llm_model``.

    Returns:
        ``ClosedLlm`` when no key is set, so neither the OpenRouter adapter nor
        ``httpx`` is imported; otherwise ``OpenRouterLlm``.

    Raises:
        LlmConfigurationError: If a key is set but ``httpx`` is not installed,
            because the ``ai`` extra was left out.
    """
    if settings.openrouter_api_key is None:
        return ClosedLlm()
    try:
        from my_app.adapters.openrouter import (  # noqa: PLC0415 - httpx comes only with the optional `ai` extra
            OpenRouterLlm,
        )
    except ModuleNotFoundError as error:
        if error.name != "httpx":
            raise
        msg = (
            "OPENROUTER_API_KEY is set but httpx is not installed: "
            "install the 'ai' extra (uv sync --extra ai)"
        )
        raise LlmConfigurationError(msg) from error
    return OpenRouterLlm(
        settings.openrouter_api_key.get_secret_value(), model=settings.llm_model
    )
