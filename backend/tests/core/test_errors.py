from __future__ import annotations

import pickle
import re
from uuid import UUID

import pytest

from my_app.core.errors import (
    AppError,
    InvalidCursorError,
    InvalidPageLimitError,
    InvalidTodoError,
    TodoNotFoundError,
)

SOME_ID = UUID("01900000-0000-7000-8000-00000000002a")


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TodoNotFoundError(SOME_ID), id="not-found"),
        pytest.param(InvalidTodoError("bad title"), id="invalid"),
        pytest.param(InvalidCursorError("bad cursor"), id="invalid-cursor"),
        pytest.param(InvalidPageLimitError("bad limit"), id="invalid-page-limit"),
    ],
)
def test_domain_error_is_an_app_error(error):
    assert isinstance(error, AppError)


def test_todo_not_found_error_keeps_the_missing_id_and_names_it():
    error = TodoNotFoundError(SOME_ID)

    assert error.todo_id == SOME_ID
    assert str(error) == "To-do 01900000-0000-7000-8000-00000000002a not found"


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TodoNotFoundError(SOME_ID), id="not-found"),
        pytest.param(InvalidTodoError("bad title"), id="invalid"),
        pytest.param(InvalidCursorError("bad cursor"), id="invalid-cursor"),
        pytest.param(InvalidPageLimitError("bad limit"), id="invalid-page-limit"),
    ],
)
def test_domain_error_pickle_round_trip_keeps_type_message_and_args(error):
    restored = pickle.loads(pickle.dumps(error))  # noqa: S301 - our own bytes, made one line above

    assert type(restored) is type(error)
    assert str(restored) == str(error)
    assert restored.args == error.args


def test_todo_not_found_error_pickle_round_trip_keeps_the_id():
    restored = pickle.loads(pickle.dumps(TodoNotFoundError(SOME_ID)))  # noqa: S301 - our own bytes

    assert restored.todo_id == SOME_ID


def test_every_app_error_declares_its_own_unique_code():
    pending = [AppError]
    codes: set[str] = set()
    while pending:
        error_type = pending.pop()
        pending.extend(error_type.__subclasses__())
        if not error_type.__module__.startswith("my_app."):
            continue
        assert "code" in error_type.__dict__, error_type.__name__
        code = error_type.code
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code), error_type.__name__
        assert code not in codes, code
        codes.add(code)
