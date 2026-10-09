from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest

from my_app.core.llm import (
    DEFAULT_LLM_TIMEOUT_SECONDS,
    LLM_ROLES,
    LlmCompletion,
    LlmUsage,
    check_completion_request,
)

if TYPE_CHECKING:
    from my_app.core.llm import LlmMessage

VALID_MESSAGES: list[LlmMessage] = [{"role": "user", "content": "hello"}]


def _check(messages=None, *, model=None, max_tokens=16, timeout=5.0):
    check_completion_request(
        VALID_MESSAGES if messages is None else messages,
        model=model,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def test_llm_roles_are_system_user_and_assistant():
    assert frozenset({"system", "user", "assistant"}) == LLM_ROLES


def test_default_llm_timeout_is_sixty_seconds():
    assert DEFAULT_LLM_TIMEOUT_SECONDS == 60.0


@pytest.mark.parametrize(
    "messages",
    [
        pytest.param(
            (
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ),
            id="tuple-of-every-role",
        ),
        pytest.param([{"role": "user", "content": ""}], id="empty-content"),
        pytest.param([{"role": "user", "content": "こんにちは 👋"}], id="unicode"),
    ],
)
def test_check_completion_request_valid_request_passes(messages):
    _check(messages, model=None)


def test_check_completion_request_returns_the_messages_as_a_tuple():
    # Any: an untyped caller's one-shot iterator of plain dicts, with an extra key.
    messages: Any = iter([{"role": "user", "content": "hello", "name": "extra"}])

    checked = check_completion_request(
        messages,
        model=None,
        max_tokens=1,
        timeout=1,
    )

    assert checked == ({"role": "user", "content": "hello"},)


@pytest.mark.parametrize(
    ("model", "max_tokens", "timeout"),
    [
        pytest.param("x", 1, 0.001, id="smallest-values"),
        pytest.param(None, 4096, 60, id="int-timeout"),
    ],
)
def test_check_completion_request_boundary_values_pass(model, max_tokens, timeout):
    _check(model=model, max_tokens=max_tokens, timeout=timeout)


@pytest.mark.parametrize(
    ("messages", "pattern"),
    [
        pytest.param([], r"^messages must not be empty$", id="empty-list"),
        pytest.param((), r"^messages must not be empty$", id="empty-tuple"),
        pytest.param(
            [{"role": "tool", "content": "x"}],
            r"^messages\[0\] role must be one of assistant, system, user, got 'tool'$",
            id="unknown-role",
        ),
        pytest.param(
            [{"role": "user", "content": "a"}, {"content": "x"}],
            r"^messages\[1\] role must be one of assistant, system, user, got None$",
            id="missing-role",
        ),
        pytest.param(
            [{"role": "user", "content": 42}],
            r"^messages\[0\] content must be a string, got int$",
            id="int-content",
        ),
        pytest.param(
            [{"role": "user"}],
            r"^messages\[0\] content must be a string, got NoneType$",
            id="missing-content",
        ),
    ],
)
def test_check_completion_request_bad_messages_raise_value_error(messages, pattern):
    with pytest.raises(ValueError, match=pattern):
        _check(messages)


@pytest.mark.parametrize(
    ("model", "pattern"),
    [
        pytest.param("", r"^model must be a non-blank model id, got ''$", id="empty"),
        pytest.param(
            "   ", r"^model must be a non-blank model id, got '   '$", id="whitespace"
        ),
    ],
)
def test_check_completion_request_blank_model_raises_value_error(model, pattern):
    with pytest.raises(ValueError, match=pattern):
        _check(model=model)


@pytest.mark.parametrize(
    ("max_tokens", "shown"),
    [
        pytest.param(0, "0", id="zero"),
        pytest.param(-1, "-1", id="negative"),
        pytest.param(True, "True", id="bool"),
        pytest.param(1.5, "1.5", id="float"),
    ],
)
def test_check_completion_request_bad_max_tokens_raises_value_error(max_tokens, shown):
    with pytest.raises(
        ValueError, match=rf"^max_tokens must be a positive integer, got {shown}$"
    ):
        _check(max_tokens=max_tokens)


@pytest.mark.parametrize(
    ("timeout", "shown"),
    [
        pytest.param(0, "0", id="zero"),
        pytest.param(-1, "-1", id="negative"),
        pytest.param(float("nan"), "nan", id="nan"),
        pytest.param(float("inf"), "inf", id="inf"),
        pytest.param(True, "True", id="bool"),
        pytest.param("5", "'5'", id="string"),
    ],
)
def test_check_completion_request_bad_timeout_raises_value_error(timeout, shown):
    with pytest.raises(
        ValueError,
        match=rf"^timeout must be a positive finite number of seconds, got {shown}$",
    ):
        _check(timeout=timeout)


def test_check_completion_request_checks_messages_before_the_other_arguments():
    with pytest.raises(ValueError, match=r"^messages must not be empty$"):
        _check([], model="", max_tokens=0, timeout=0)


def test_llm_usage_total_tokens_adds_prompt_and_completion():
    assert LlmUsage(prompt_tokens=3, completion_tokens=1).total_tokens == 4


def test_llm_usage_zero_tokens_is_allowed():
    assert LlmUsage(0, 0).total_tokens == 0


@pytest.mark.parametrize(
    ("prompt_tokens", "completion_tokens", "pattern"),
    [
        pytest.param(
            -1,
            0,
            r"^prompt_tokens must be a non-negative integer, got -1$",
            id="negative-prompt",
        ),
        pytest.param(
            0,
            -1,
            r"^completion_tokens must be a non-negative integer, got -1$",
            id="negative-completion",
        ),
        pytest.param(
            True,
            0,
            r"^prompt_tokens must be a non-negative integer, got True$",
            id="bool-prompt",
        ),
        pytest.param(
            0,
            1.0,
            r"^completion_tokens must be a non-negative integer, got 1.0$",
            id="float-completion",
        ),
    ],
)
def test_llm_usage_invalid_count_raises_value_error(
    prompt_tokens, completion_tokens, pattern
):
    with pytest.raises(ValueError, match=pattern):
        LlmUsage(prompt_tokens, completion_tokens)


def test_llm_completion_is_frozen():
    completion = LlmCompletion(
        text="hi", model="x", finish_reason="stop", usage=LlmUsage(3, 1)
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        completion.text = "changed"  # type: ignore[misc]  # assigning is the point
