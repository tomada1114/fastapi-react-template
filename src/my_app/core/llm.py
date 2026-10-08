"""The values an ``LlmPort`` takes and returns, and the check every call runs first.

Kept free of any HTTP library, like the rest of the core: an adapter turns these
values into a provider's wire format and back.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal, TypedDict, TypeGuard, cast

type LlmRole = Literal["system", "user", "assistant"]
LLM_ROLES: Final = frozenset({"system", "user", "assistant"})
# What a caller passes as `timeout` when it has no reason to pick another bound.
DEFAULT_LLM_TIMEOUT_SECONDS: Final = 60.0


class LlmMessage(TypedDict):
    """One chat message, in the shape OpenAI-compatible providers take."""

    role: LlmRole
    content: str


@dataclass(frozen=True, slots=True)
class LlmUsage:
    """The tokens one completion consumed, as the provider counted them."""

    prompt_tokens: int
    completion_tokens: int

    def __post_init__(self) -> None:
        """Refuse a count no provider could report.

        Raises:
            ValueError: If either count is negative, a bool, or not an int.
        """
        for name in ("prompt_tokens", "completion_tokens"):
            count = getattr(self, name)
            if not _is_int(count) or count < 0:
                msg = f"{name} must be a non-negative integer, got {count!r}"
                raise ValueError(msg)

    @property
    def total_tokens(self) -> int:
        """The prompt and completion tokens together."""
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class LlmCompletion:
    """A model's answer to one ``LlmPort.complete`` call.

    Attributes:
        text: The answer; may be empty.
        model: The model that answered, which can differ from the one asked
            for when the provider routes the request.
        finish_reason: Why generation stopped (``"stop"``, ``"length"``, ...)
            as the provider said it; passed through, not judged.
        usage: The tokens the call consumed.
    """

    text: str
    model: str
    finish_reason: str | None
    usage: LlmUsage


def check_completion_request(
    messages: Iterable[LlmMessage],
    *,
    model: str | None,
    max_tokens: int,
    timeout: float,
) -> tuple[LlmMessage, ...]:
    """Reject arguments no ``LlmPort`` may send, before any request is made.

    Every adapter calls this first and sends the messages it returns, so a bad
    argument fails the same way whichever adapter is wired in, and a one-shot
    iterator is read once, here. The arguments come from code, not from a
    user, so a bad one is a bug: a ``ValueError`` with its traceback, never an
    ``AppError``. A service that forwards user input validates it first.

    Args:
        messages: The conversation; at least one message.
        model: A model id, or None for the adapter's configured model.
        max_tokens: The most tokens the answer may use; at least 1.
        timeout: The call's budget in seconds; positive and finite.

    Returns:
        The messages, read once into a tuple holding only each message's
        ``role`` and ``content``.

    Raises:
        ValueError: On the first argument that breaks its rule, checked in
            the order above; a string that cannot be encoded as UTF-8 (a lone
            surrogate) is refused, as no provider could be sent it.
    """
    checked = _check_messages(messages)
    if model is not None:
        if not _is_str(model):
            msg = f"model must be a string or None, got {type(model).__name__}"
            raise ValueError(msg)
        if not model.strip():
            msg = f"model must be a non-blank model id, got {model!r}"
            raise ValueError(msg)
        if not _is_utf8(model):
            msg = "model must be encodable as UTF-8"
            raise ValueError(msg)
    if not _is_int(max_tokens) or max_tokens < 1:
        msg = f"max_tokens must be a positive integer, got {max_tokens!r}"
        raise ValueError(msg)
    if not _is_positive_finite_number(timeout):
        msg = f"timeout must be a positive finite number of seconds, got {timeout!r}"
        raise ValueError(msg)
    return checked


def _check_messages(messages: Iterable[LlmMessage]) -> tuple[LlmMessage, ...]:
    """Read ``messages`` once and check each one; see ``check_completion_request``.

    Read as untrusted: the type says LlmMessage, but nothing checks a caller
    that builds its messages from JSON or plain dicts.
    """
    untrusted: object = messages
    if not _is_message_iterable(untrusted):
        msg = f"messages must be a sequence of messages, got {type(untrusted).__name__}"
        raise ValueError(msg)
    elements: tuple[object, ...] = tuple(untrusted)
    if not elements:
        msg = "messages must not be empty"
        raise ValueError(msg)
    checked: list[LlmMessage] = []
    for index, element in enumerate(elements):
        if not _is_mapping(element):
            msg = f"messages[{index}] must be a mapping, got {type(element).__name__}"
            raise ValueError(msg)
        role = element.get("role")
        if role not in LLM_ROLES:
            allowed = ", ".join(sorted(LLM_ROLES))
            msg = f"messages[{index}] role must be one of {allowed}, got {role!r}"
            raise ValueError(msg)
        content = element.get("content")
        if not _is_str(content):
            msg = (
                f"messages[{index}] content must be a string, "
                f"got {type(content).__name__}"
            )
            raise ValueError(msg)
        if not _is_utf8(content):
            msg = f"messages[{index}] content must be encodable as UTF-8"
            raise ValueError(msg)
        checked.append(LlmMessage(role=cast("LlmRole", role), content=content))
    return tuple(checked)


def _is_message_iterable(value: object) -> TypeGuard[Iterable[object]]:
    """Return whether ``value`` can hold messages: an iterable, but no string.

    A str or bytes is iterable, but its characters are not messages. Like
    ``_is_str``, a helper keeps the caller's ``ValueError`` unprompted.
    """
    return isinstance(value, Iterable) and not isinstance(
        value, str | bytes | bytearray
    )


def _is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    """Return whether ``value`` is a mapping, as a message must be."""
    return isinstance(value, Mapping)


def _is_utf8(value: str) -> bool:
    """Return whether ``value`` encodes as UTF-8; a lone surrogate does not."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_str(value: object) -> TypeGuard[str]:
    """Return whether ``value`` is a string.

    A bad argument is a ``ValueError`` here whatever its kind, so this stays a
    helper rather than an inline ``isinstance`` that asks for a ``TypeError``.
    """
    return isinstance(value, str)


def _is_int(value: object) -> bool:
    """Return whether ``value`` is an int and not a bool, which subclasses int."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_positive_finite_number(value: object) -> bool:
    """Return whether ``value`` is an int or float above zero, not NaN or infinite."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value) and value > 0
