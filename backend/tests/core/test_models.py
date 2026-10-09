from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from my_app.core.errors import InvalidTodoError
from my_app.core.models import MAX_TITLE_LENGTH, Todo, TodoDraft, normalize_title


@pytest.mark.parametrize(
    ("raw_title", "expected"),
    [
        pytest.param("buy milk", "buy milk", id="plain"),
        pytest.param("  buy milk\n", "buy milk", id="surrounding-whitespace"),
        pytest.param("x", "x", id="one-character"),
        pytest.param("x" * MAX_TITLE_LENGTH, "x" * MAX_TITLE_LENGTH, id="max-length"),
        pytest.param("牛乳を買う 🥛", "牛乳を買う 🥛", id="unicode"),
        pytest.param(
            f" {'x' * MAX_TITLE_LENGTH} ",
            "x" * MAX_TITLE_LENGTH,
            id="max-length-after-strip",
        ),
    ],
)
def test_normalize_title_valid_title_returns_stripped_title(raw_title, expected):
    assert normalize_title(raw_title) == expected


@pytest.mark.parametrize(
    ("raw_title", "length"),
    [
        pytest.param("", 0, id="empty"),
        pytest.param(" \t\n ", 0, id="whitespace-only"),
        pytest.param("x" * (MAX_TITLE_LENGTH + 1), MAX_TITLE_LENGTH + 1, id="too-long"),
    ],
)
def test_normalize_title_out_of_range_raises_invalid_todo_error(raw_title, length):
    with pytest.raises(InvalidTodoError, match=rf"1-200 characters .* got {length}$"):
        normalize_title(raw_title)


@pytest.fixture(params=[TodoDraft, Todo], ids=["draft", "todo"])
def make_model(request, fixed_now):
    """Build a ``TodoDraft`` or a ``Todo``; both enforce the same invariants."""

    def _make(
        title: str = "buy milk", created_at: datetime = fixed_now
    ) -> Todo | TodoDraft:
        if request.param is Todo:
            return Todo(id=1, title=title, created_at=created_at)
        return TodoDraft(title=title, created_at=created_at)

    return _make


def test_model_valid_fields_keeps_them(make_model, fixed_now):
    model = make_model("buy milk", fixed_now)

    assert (model.title, model.created_at) == ("buy milk", fixed_now)


@pytest.mark.parametrize(
    ("title", "pattern"),
    [
        pytest.param(" buy milk", r"surrounding whitespace", id="unstripped"),
        pytest.param("", r"got 0$", id="empty"),
        pytest.param("x" * (MAX_TITLE_LENGTH + 1), r"got 201$", id="too-long"),
    ],
)
def test_model_invalid_title_raises_invalid_todo_error(make_model, title, pattern):
    with pytest.raises(InvalidTodoError, match=pattern):
        make_model(title)


def test_model_naive_created_at_raises_value_error(make_model):
    naive = datetime.fromisoformat("2026-01-02T03:04:05")

    with pytest.raises(ValueError, match=r"must be timezone-aware"):
        make_model(created_at=naive)


def test_replace_with_invalid_title_raises_invalid_todo_error(fixed_now):
    todo = Todo(id=1, title="buy milk", created_at=fixed_now)

    with pytest.raises(InvalidTodoError, match=r"got 0$"):
        replace(todo, title="")
