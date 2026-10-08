"""An ``LlmPort`` that answers from a script: the fake for tests of LLM-using code."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from my_app.core.llm import (
    LlmCompletion,
    LlmUsage,
    check_completion_request,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from my_app.core.errors import LlmError
    from my_app.core.llm import LlmMessage


@dataclass(frozen=True, slots=True)
class FakeLlmCall:
    """One valid request ``FakeLlm`` received, with the model it resolved to."""

    messages: tuple[LlmMessage, ...]
    model: str
    max_tokens: int
    timeout: float


class FakeLlm:
    """Answer every call with the same scripted reply, or raise a scripted error.

    It runs the same argument check as every real adapter, so a test that
    passes against the fake does not send a request a real adapter rejects.
    Calls are recorded under a lock, as FastAPI may call it from several
    threads at once.
    """

    def __init__(
        self,
        reply: str = "",
        *,
        model: str = "fake/model",
        usage: LlmUsage | None = None,
        error: LlmError | None = None,
    ) -> None:
        """Script the answer.

        Args:
            reply: The text every completion returns.
            model: The configured model, used when a call passes none.
            usage: The usage every completion reports; zero tokens when None.
            error: Raised by every call, after it is recorded, instead of
                answering; lets a test drive its error path.
        """
        self._reply = reply
        self._model = model
        self._usage = usage if usage is not None else LlmUsage(0, 0)
        self._error = error
        self._calls: list[FakeLlmCall] = []
        self._lock = threading.Lock()

    @property
    def calls(self) -> list[FakeLlmCall]:
        """Every valid request so far, oldest first; a copy the caller may change."""
        with self._lock:
            return list(self._calls)

    def complete(
        self,
        messages: Sequence[LlmMessage],
        *,
        model: str | None = None,
        max_tokens: int,
        timeout: float,
    ) -> LlmCompletion:
        """Record the request, then raise the scripted error or return the reply.

        Raises:
            ValueError: If an argument breaks ``check_completion_request``;
                nothing is recorded.
            LlmError: The scripted ``error``, when one was given.
        """
        checked = check_completion_request(
            messages, model=model, max_tokens=max_tokens, timeout=timeout
        )
        resolved = self._model if model is None else model
        call = FakeLlmCall(
            messages=checked,
            model=resolved,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        with self._lock:
            self._calls.append(call)
        if self._error is not None:
            # One instance is raised on every call: drop the traceback the
            # last raise left on it, or it grows by one frame per call.
            raise self._error.with_traceback(None)
        return LlmCompletion(
            text=self._reply, model=resolved, finish_reason="stop", usage=self._usage
        )
