from __future__ import annotations

import pickle

import pytest

from my_app.core.errors import (
    AppError,
    InvalidTodoError,
    LlmConfigurationError,
    LlmError,
    LlmProviderError,
    LlmRateLimitError,
    LlmTimeoutError,
    TodoNotFoundError,
)

LLM_ERRORS = [
    pytest.param(LlmError("llm failed"), id="llm"),
    pytest.param(LlmConfigurationError("not configured"), id="llm-configuration"),
    pytest.param(LlmRateLimitError("rate-limited"), id="llm-rate-limit"),
    pytest.param(LlmTimeoutError("timed out"), id="llm-timeout"),
    pytest.param(LlmProviderError("provider failed"), id="llm-provider"),
]


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TodoNotFoundError(7), id="not-found"),
        pytest.param(InvalidTodoError("bad title"), id="invalid"),
        *LLM_ERRORS,
    ],
)
def test_domain_error_is_an_app_error(error):
    assert isinstance(error, AppError)


def test_todo_not_found_error_keeps_the_missing_id_and_names_it():
    error = TodoNotFoundError(42)

    assert error.todo_id == 42
    assert str(error) == "To-do 42 not found"


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TodoNotFoundError(42), id="not-found"),
        pytest.param(InvalidTodoError("bad title"), id="invalid"),
        *LLM_ERRORS,
    ],
)
def test_domain_error_pickle_round_trip_keeps_type_message_and_args(error):
    restored = pickle.loads(pickle.dumps(error))  # noqa: S301 - our own bytes, made one line above

    assert type(restored) is type(error)
    assert str(restored) == str(error)
    assert restored.args == error.args


def test_todo_not_found_error_pickle_round_trip_keeps_the_id():
    restored = pickle.loads(pickle.dumps(TodoNotFoundError(42)))  # noqa: S301 - our own bytes

    assert restored.todo_id == 42


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(LlmConfigurationError("not configured"), id="configuration"),
        pytest.param(LlmRateLimitError("rate-limited"), id="rate-limit"),
        pytest.param(LlmTimeoutError("timed out"), id="timeout"),
        pytest.param(LlmProviderError("provider failed"), id="provider"),
    ],
)
def test_llm_error_subclass_is_an_llm_error(error):
    assert isinstance(error, LlmError)
