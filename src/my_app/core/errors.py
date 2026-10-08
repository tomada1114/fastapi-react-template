"""Domain errors, each a subclass of one package base exception.

Entry points translate these into their own vocabulary (an HTTP status, an
exit code), so the core never needs to know which one called it.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for every error the application raises on purpose.

    Catching it separates an expected domain failure, which an entry point
    reports to its user, from a bug, which should surface as a traceback.
    """


class TodoNotFoundError(AppError):
    """Raised when no to-do has the requested id."""

    def __init__(self, todo_id: int) -> None:
        """Keep the missing id so callers can report it without parsing text.

        The id is the exception's only argument, so pickling (as process
        pools and some task queues do) rebuilds an equal error.

        Args:
            todo_id: The id that matched no stored to-do.
        """
        super().__init__(todo_id)
        self.todo_id = todo_id

    def __str__(self) -> str:
        """Return the message entry points show their users."""
        return f"To-do {self.todo_id} not found"


class InvalidTodoError(AppError):
    """Raised when input would create a to-do that breaks a domain rule."""


# The LLM family. Each is message-only: the message is the one argument, so
# pickling rebuilds an equal error. Every message is client-safe: it never
# carries the API key, a prompt, a model's output, or the provider's own error
# text, which can echo the prompt.


class LlmError(AppError):
    """Base for every failure an ``LlmPort`` reports."""


class LlmConfigurationError(LlmError):
    """The LLM is not usable as configured.

    No key, the ``ai`` extra missing, or a key or account the provider rejected.
    """


class LlmRateLimitError(LlmError):
    """The provider is rate-limiting requests and the retry bound or deadline ran out."""


class LlmTimeoutError(LlmError):
    """The call did not finish within its timeout, or the provider timed out."""


class LlmProviderError(LlmError):
    """The provider failed or answered with something that is not a usable completion."""
