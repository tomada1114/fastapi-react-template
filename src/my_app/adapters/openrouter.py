"""An ``LlmPort`` over OpenRouter's OpenAI-compatible chat completions endpoint.

The only module that imports ``httpx`` outside the tests. ``httpx`` comes with
the optional ``ai`` extra, so ``composition.build_llm`` imports this module only
when a key is set. The wire format, the status meanings, and ``Retry-After``
follow OpenRouter's API reference; the ``integrating-llm`` skill cites it.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeGuard

import httpx

from my_app.adapters.closed_llm import LLM_NOT_CONFIGURED_MESSAGE
from my_app.core.errors import (
    LlmConfigurationError,
    LlmError,
    LlmProviderError,
    LlmRateLimitError,
    LlmTimeoutError,
)
from my_app.core.llm import LlmCompletion, LlmUsage, check_completion_request

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from my_app.core.llm import LlmMessage

OPENROUTER_CHAT_COMPLETIONS_URL: Final = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MAX_RETRIES: Final = 2
BASE_BACKOFF_SECONDS: Final = 0.5
MAX_BACKOFF_SECONDS: Final = 8.0
# A longer Retry-After ends the call at once rather than being shortened:
# retrying before the provider asked would only be refused again.
MAX_RETRY_AFTER_SECONDS: Final = 8.0
MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
RETRYABLE_STATUSES: Final = frozenset({429, 502, 503})
_RETRY_AFTER_STATUSES: Final = frozenset({429, 503})
_KEY_REJECTED_STATUSES: Final = frozenset({401, 402})
_TIMEOUT_STATUSES: Final = frozenset({408, 504})
_UNREACHABLE_MESSAGE: Final = "The LLM provider could not be reached"
_NOT_A_COMPLETION_MESSAGE: Final = (
    "The LLM provider returned a response that is not a chat completion"
)
_UNREADABLE_MESSAGE: Final = "The LLM provider's response could not be read"
_KEY_NOT_A_HEADER_VALUE_MESSAGE: Final = (
    "OPENROUTER_API_KEY is not a usable API key: "
    "it must contain only visible ASCII characters"
)
# The characters an Authorization header value may carry: visible ASCII.
_FIRST_VISIBLE_ASCII: Final = 0x21
_LAST_VISIBLE_ASCII: Final = 0x7E


@dataclass(frozen=True, slots=True)
class _Failure:
    """One failed attempt: the error to raise, its cause, and whether to retry.

    ``retry_after`` is the wait the provider asked for, when it asked for one
    within ``MAX_RETRY_AFTER_SECONDS``; otherwise the computed backoff applies.
    """

    error: LlmError
    cause: Exception | None = None
    is_retryable: bool = False
    retry_after: float | None = None


class OpenRouterLlm:
    """Ask OpenRouter for chat completions, with bounded retries and a deadline.

    Every call opens its own ``httpx.Client`` and holds no other state, so it
    is safe across threads, as ``SqliteTodoRepository``'s connection per call is.
    """

    def __init__(  # noqa: PLR0913 - the clock and transport are injected for tests
        self,
        api_key: str | None,
        *,
        model: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind the adapter to a key and a default model.

        Args:
            api_key: The OpenRouter API key; surrounding whitespace is dropped.
            model: The model a call that names none is sent to.
            max_retries: Retries after the first attempt, for the outcomes
                that may be retried.
            transport: The ``httpx`` transport; tests pass a ``MockTransport``.
            sleep: Waits between attempts; tests pass a fake.
            monotonic: Reads the clock the deadline is measured on.

        Raises:
            LlmConfigurationError: If ``api_key`` is None, empty, or blank, or
                holds a character an HTTP header cannot carry; the message
                never contains the key.
            ValueError: If ``model`` is blank or ``max_retries`` is not a
                non-negative integer.
        """
        if api_key is None or not api_key.strip():
            raise LlmConfigurationError(LLM_NOT_CONFIGURED_MESSAGE)
        if not _is_header_value(api_key.strip()):
            # httpx would fail at request time with the whole key in its
            # error's args; refuse it here, with nothing chained that holds it.
            raise LlmConfigurationError(_KEY_NOT_A_HEADER_VALUE_MESSAGE) from None
        if not model.strip():
            msg = f"model must be a non-blank model id, got {model!r}"
            raise ValueError(msg)
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries < 0
        ):
            msg = f"max_retries must be a non-negative integer, got {max_retries!r}"
            raise ValueError(msg)
        self._api_key = api_key.strip()
        self._model = model
        self._max_retries = max_retries
        self._transport = transport
        self._sleep = sleep
        self._monotonic = monotonic

    @property
    def model(self) -> str:
        """The model a call that names none is sent to."""
        return self._model

    def complete(
        self,
        messages: Sequence[LlmMessage],
        *,
        model: str | None = None,
        max_tokens: int,
        timeout: float,
    ) -> LlmCompletion:
        """Send one chat completion request, retrying what may be retried.

        ``timeout`` is one budget for every attempt and every wait between
        attempts. Each network phase (connect, TLS, each write, each socket
        read, the headers included) is bounded separately by the budget left
        when its attempt began; the deadline itself is checked between
        attempts, once the headers arrive, and after each body chunk. So
        ordinary phases can add up to several times ``timeout``, and a server
        that trickles bytes can hold the call indefinitely: a caller that
        needs a hard cutoff runs the call under its own cancellation. A retry
        happens only on a 429, 502, or 503, or a connection that never
        reached the provider, and only while a retry is left and its wait ends
        before the deadline.

        Raises:
            ValueError: If an argument breaks ``check_completion_request``.
            LlmConfigurationError: If the provider rejected the key or account.
            LlmRateLimitError: If rate limiting outlasted the retries.
            LlmTimeoutError: If the deadline passed, or the provider timed out.
            LlmProviderError: If the provider failed, could not be reached, or
                did not answer with a chat completion.
        """
        checked = check_completion_request(
            messages, model=model, max_tokens=max_tokens, timeout=timeout
        )
        resolved = self._model if model is None else model
        payload = {
            "model": resolved,
            "messages": [dict(message) for message in checked],
            "max_tokens": max_tokens,
            "stream": False,
        }
        deadline = self._monotonic() + timeout
        retry_index = 0
        while True:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise LlmTimeoutError(_timeout_message(timeout))
            outcome = self._attempt(payload, remaining, deadline, timeout, resolved)
            if isinstance(outcome, LlmCompletion):
                return outcome
            delay = (
                outcome.retry_after
                if outcome.retry_after is not None
                else _backoff(retry_index)
            )
            if (
                not outcome.is_retryable
                or retry_index >= self._max_retries
                or self._monotonic() + delay >= deadline
            ):
                raise outcome.error from outcome.cause
            self._sleep(delay)
            retry_index += 1

    def _attempt(
        self,
        payload: dict[str, object],
        remaining: float,
        deadline: float,
        timeout: float,
        requested_model: str,
    ) -> LlmCompletion | _Failure:
        """Send the request once and classify what came back."""
        client = self._client(remaining)
        if isinstance(client, _Failure):
            return client
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            with (
                client,
                client.stream(
                    "POST",
                    OPENROUTER_CHAT_COMPLETIONS_URL,
                    headers=headers,
                    json=payload,
                ) as response,
            ):
                if not response.is_success:
                    return _failure_for_status(response)
                body = self._read_body(response, deadline, timeout)
        except httpx.RequestError as error:
            return _failure_for_request_error(error, timeout)
        if isinstance(body, _Failure):
            return body
        return _parse_completion(body, requested_model)

    def _client(self, remaining: float) -> httpx.Client | _Failure:
        """Open the attempt's client, each network phase bounded by ``remaining``.

        Without an injected transport, httpx reads proxy settings from the
        environment here, and refuses one it cannot use.
        """
        try:
            return httpx.Client(
                transport=self._transport,
                timeout=httpx.Timeout(remaining),
                follow_redirects=False,
            )
        except (ImportError, ValueError) as error:
            # Name only the cause's class: a proxy URL can carry credentials.
            msg = (
                "The HTTP client for the LLM provider could not be built from "
                f"the environment's proxy settings ({type(error).__name__})"
            )
            return _Failure(LlmConfigurationError(msg), error)

    def _read_body(
        self, response: httpx.Response, deadline: float, timeout: float
    ) -> bytes | _Failure:
        """Read a 2xx body, stopping at the deadline or the size cap.

        ``httpx`` has no whole-response timeout, so the deadline is checked
        once the headers have arrived and again after every chunk; one read
        can still block for the attempt's budget.
        """
        if self._monotonic() > deadline:
            # The headers arrived late: skip a body there is no time for.
            return _Failure(LlmTimeoutError(_timeout_message(timeout)))
        body = bytearray()
        for chunk in response.iter_bytes():
            if self._monotonic() > deadline:
                return _Failure(LlmTimeoutError(_timeout_message(timeout)))
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                msg = f"The LLM provider's response exceeded {MAX_RESPONSE_BYTES} bytes"
                return _Failure(LlmProviderError(msg))
        return bytes(body)


def _timeout_message(timeout: float) -> str:
    return f"The LLM request did not finish within {timeout:g} seconds"


def _failure_for_request_error(error: httpx.RequestError, timeout: float) -> _Failure:
    """Classify an ``httpx`` failure raised while sending or reading."""
    if isinstance(error, httpx.TimeoutException):
        return _Failure(LlmTimeoutError(_timeout_message(timeout)), error)
    if isinstance(error, httpx.ConnectError):
        # Nothing reached the provider, so nothing was billed: safe to retry.
        failure = LlmProviderError(_UNREACHABLE_MESSAGE)
        return _Failure(failure, error, is_retryable=True)
    if isinstance(error, httpx.TransportError):
        # The request may have been processed and billed: never retried.
        return _Failure(LlmProviderError(_UNREACHABLE_MESSAGE), error)
    # Not a transport failure: a 2xx body that failed to decode, or a redirect
    # loop. The request was answered, so it is not retried.
    return _Failure(LlmProviderError(_UNREADABLE_MESSAGE), error)


def _backoff(retry_index: int) -> float:
    """Return the wait before retry ``retry_index`` (0-based): 0.5 s, 1.0 s, ...

    No jitter: with at most a couple of retries per call, a thundering herd is
    not a template-scale problem, and an exact wait keeps the tests exact.
    """
    return min(BASE_BACKOFF_SECONDS * 2.0**retry_index, MAX_BACKOFF_SECONDS)


def _error_for_status(status: int, *, in_body: bool = False) -> LlmError:
    """Map an HTTP status, or a status-like error code, to the error it means.

    ``in_body`` marks a code read from an error object inside a 2xx: it need
    not be an HTTP status at all, so the fallback message does not call it one.
    """
    if status in _KEY_REJECTED_STATUSES:
        msg = f"The LLM provider rejected the configured key or account (HTTP {status})"
        return LlmConfigurationError(msg)
    if status in _TIMEOUT_STATUSES:
        return LlmTimeoutError(f"The LLM provider timed out (HTTP {status})")
    if status == httpx.codes.TOO_MANY_REQUESTS:
        return LlmRateLimitError(
            "The LLM provider is rate-limiting requests (HTTP 429)"
        )
    if in_body:
        return LlmProviderError(f"The LLM provider returned error code {status}")
    return LlmProviderError(f"The LLM provider returned HTTP {status}")


def _failure_for_status(response: httpx.Response) -> _Failure:
    """Classify a non-2xx answer, honoring ``Retry-After`` on a 429 or 503."""
    status = response.status_code
    error = _error_for_status(status)
    if status not in RETRYABLE_STATUSES:
        return _Failure(error)
    if status not in _RETRY_AFTER_STATUSES:
        return _Failure(error, is_retryable=True)
    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
    if retry_after is not None and retry_after > MAX_RETRY_AFTER_SECONDS:
        return _Failure(error)
    return _Failure(error, is_retryable=True, retry_after=retry_after)


def _parse_retry_after(value: str | None) -> float | None:
    """Return ``Retry-After`` as seconds, or None when it is not delta-seconds.

    An HTTP-date is treated as unparsable: the computed backoff applies.
    """
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    if math.isnan(seconds) or seconds < 0:
        return None
    return seconds


def _parse_completion(body: bytes, requested_model: str) -> LlmCompletion | _Failure:
    """Turn a 2xx body into a completion, or the failure it reports.

    An error inside a 2xx is never retried: the request was accepted and may
    have been billed.
    """
    try:
        data = json.loads(body)
    except ValueError, RecursionError:
        # RecursionError: a body nested deeper than the parser can follow.
        return _Failure(LlmProviderError(_NOT_A_COMPLETION_MESSAGE))
    if not isinstance(data, dict):
        return _Failure(LlmProviderError(_NOT_A_COMPLETION_MESSAGE))
    if isinstance(error := data.get("error"), dict):
        code = error.get("code")
        if isinstance(code, bool) or not isinstance(code, int):
            return _Failure(LlmProviderError("The LLM provider returned an error"))
        return _Failure(_error_for_status(code, in_body=True))
    completion = _completion_from(data, requested_model)
    if completion is None:
        return _Failure(LlmProviderError(_NOT_A_COMPLETION_MESSAGE))
    return completion


def _completion_from(
    data: dict[str, object], requested_model: str
) -> LlmCompletion | None:
    """Read the fields a chat completion must have, or None if one is missing."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    message = choice.get("message")
    if not isinstance(message, dict) or not isinstance(
        text := message.get("content"), str
    ):
        return None
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if not (_is_count(prompt_tokens) and _is_count(completion_tokens)):
        return None
    answered = data.get("model")
    finish_reason = choice.get("finish_reason")
    return LlmCompletion(
        text=text,
        model=answered
        if isinstance(answered, str) and answered.strip()
        else requested_model,
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        usage=LlmUsage(prompt_tokens, completion_tokens),
    )


def _is_header_value(value: str) -> bool:
    """Return whether ``value`` holds only visible ASCII, as a header value must."""
    return all(
        _FIRST_VISIBLE_ASCII <= ord(character) <= _LAST_VISIBLE_ASCII
        for character in value
    )


def _is_count(value: object) -> TypeGuard[int]:
    """Return whether ``value`` is a token count: a non-negative int, not a bool."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
