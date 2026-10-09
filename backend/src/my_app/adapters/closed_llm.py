"""The ``LlmPort`` an app gets when no LLM is configured: every call is refused.

Stdlib only, so an app without the optional ``ai`` extra can always build it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from my_app.core.errors import LlmConfigurationError
from my_app.core.llm import check_completion_request

if TYPE_CHECKING:
    from collections.abc import Sequence

    from my_app.core.llm import LlmCompletion, LlmMessage

LLM_NOT_CONFIGURED_MESSAGE: Final = (
    "LLM is not configured: set OPENROUTER_API_KEY to enable it"
)


class ClosedLlm:
    """Refuse every completion with ``LlmConfigurationError``.

    Closed by default: a route built on it answers 503 until a key is set,
    so no billed endpoint opens by accident.
    """

    def complete(
        self,
        messages: Sequence[LlmMessage],
        *,
        model: str | None = None,
        max_tokens: int,
        timeout: float,
    ) -> LlmCompletion:
        """Check the arguments, then refuse.

        Raises:
            ValueError: If an argument breaks ``check_completion_request``; a
                bug stays a bug even while the LLM is closed.
            LlmConfigurationError: Always, for a valid request.
        """
        check_completion_request(
            messages, model=model, max_tokens=max_tokens, timeout=timeout
        )
        raise LlmConfigurationError(LLM_NOT_CONFIGURED_MESSAGE)
