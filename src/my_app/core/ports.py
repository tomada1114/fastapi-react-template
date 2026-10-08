"""The interfaces the core needs from the outside world.

They are ``Protocol`` classes so an adapter satisfies one by shape alone: it
never imports or subclasses anything from the core to plug in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from my_app.core.llm import LlmCompletion, LlmMessage
    from my_app.core.models import Todo, TodoDraft


class Clock(Protocol):
    """A source of the current time; any zero-argument callable fits.

    Injected rather than read from ``datetime.now`` so tests can fix the time.
    """

    def __call__(self) -> datetime:
        """Return the current time.

        Returns:
            A timezone-aware ``datetime``; ``Todo`` rejects a naive one.
        """


@runtime_checkable
class TodoRepository(Protocol):
    """Stores to-dos and assigns their ids.

    Every implementation must pass the shared contract suite in
    ``tests/adapters/test_repository_contract.py``. Runtime-checkable so that
    suite can also assert an adapter has every method, not only mypy.
    """

    def add(self, draft: TodoDraft) -> Todo:
        """Store a draft under a new id.

        Args:
            draft: The validated to-do to store.

        Returns:
            The stored to-do. Ids increase and are never reused, even after a
            delete, so a stale id can never name a different to-do.
        """

    def get(self, todo_id: int) -> Todo:
        """Fetch one to-do.

        Args:
            todo_id: Any integer; one never assigned is simply not found.

        Returns:
            The stored to-do.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """

    def list_all(self) -> list[Todo]:
        """Fetch every to-do.

        Returns:
            The to-dos in ascending id order, which is creation order.
        """

    def update(self, todo: Todo) -> Todo:
        """Replace the stored to-do that has ``todo.id``.

        Args:
            todo: The new value; its id selects what it replaces.

        Returns:
            ``todo``, now stored.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """

    def delete(self, todo_id: int) -> None:
        """Remove one to-do.

        Args:
            todo_id: Any integer; one never assigned is simply not found.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """


@runtime_checkable
class LlmPort(Protocol):
    """Asks a language model for one chat completion.

    Every implementation that can complete must pass the shared contract suite
    in ``tests/adapters/test_llm_contract.py``. An implementation is safe to
    call from several threads, since FastAPI runs synchronous routes in a pool.
    """

    def complete(
        self,
        messages: Sequence[LlmMessage],
        *,
        model: str | None = None,
        max_tokens: int,
        timeout: float,
    ) -> LlmCompletion:
        """Send ``messages`` and return the model's answer.

        The arguments are checked with ``core.llm.check_completion_request``
        before any request is made.

        Args:
            messages: The conversation, oldest message first.
            model: The model to ask; None means the model this adapter was
                built with.
            max_tokens: The most tokens the answer may use.
            timeout: The call's budget in seconds, retries and the waits
                between them included. It is enforced between steps, not as
                a hard cutoff: an adapter bounds each network phase by the
                budget left and checks the deadline between phases, so a
                pathologically slow server can still exceed it. A caller that
                needs a hard cutoff runs the call under its own cancellation.

        Returns:
            The answer, the model that gave it, and the tokens it used.

        Raises:
            ValueError: If an argument breaks its rule; that is a bug in the
                caller, not a domain error.
            LlmConfigurationError: If the LLM is not configured, or the
                provider rejected the key or the account.
            LlmRateLimitError: If the provider kept rate-limiting until the
                retry bound or the deadline ran out; try again later.
            LlmTimeoutError: If the call did not finish within ``timeout``.
            LlmProviderError: If the provider failed, could not be reached, or
                answered with something that is not a completion.
        """
