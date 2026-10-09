"""Fixtures shared by every layer's tests."""

from __future__ import annotations

import itertools
import os
from datetime import UTC, datetime
from uuid import UUID

import pytest

from my_app.composition import Container, build_container
from my_app.settings import Settings
from tests.settings_env import without_settings_env

FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _fixed_clock() -> datetime:
    return FIXED_NOW


def _nth_id(n: int) -> UUID:
    # A version-7, RFC 9562-variant layout with n in the low bits, so the ids
    # look like uuid.uuid7's and ascend with n.
    return UUID(f"01900000-0000-7000-8000-{n:012x}")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Run every ``anyio``-marked test on asyncio only.

    AnyIO's own fixture is module-scoped and parametrized over every installed
    backend; fixing it here keeps the run single-backend, and session scope
    lets a module- or session-scoped async fixture use it.
    """
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch):
    """Keep every settings input from the developer's shell out of tests."""
    cleaned = without_settings_env(os.environ)
    for name in set(os.environ) - cleaned.keys():
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fixed_now() -> datetime:
    """The instant ``fixed_clock`` always reads."""
    return FIXED_NOW


@pytest.fixture
def fixed_clock():
    """A ``Clock`` that always reads ``fixed_now``, so timestamps are exact."""
    return _fixed_clock


@pytest.fixture
def nth_id():
    """Return the ``n``-th id ``new_id`` hands out, counting from 1."""
    return _nth_id


@pytest.fixture
def new_id():
    """An ``IdFactory`` handing out ``nth_id(1)``, ``nth_id(2)``, ... in turn.

    One counter per test, shared by every container ``make_container`` builds
    in it, so two containers on the same SQLite file never collide on an id.
    """
    counter = itertools.count(1)
    return lambda: _nth_id(next(counter))


@pytest.fixture
def make_container(new_id):
    """Build a container through the composition root with fixed time and ids.

    Defaults to the in-memory repository; pass ``Settings`` to choose another.
    """

    def _make(settings: Settings | None = None) -> Container:
        chosen = settings if settings is not None else Settings(database_url=None)
        return build_container(chosen, clock=_fixed_clock, new_id=new_id)

    return _make
