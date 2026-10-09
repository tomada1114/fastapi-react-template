"""What the SQL schema stores, below what the repository contract can see."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import bindparam, insert, select, text
from sqlalchemy.exc import StatementError

from my_app.adapters.sql.engine import make_engine
from my_app.adapters.sql.tables import UtcDateTime, metadata, todos

pytestmark = pytest.mark.anyio

TOKYO = timezone(timedelta(hours=9))
TODO_ID = UUID("01900000-0000-7000-8000-000000000001")


@pytest.fixture
async def engine(tmp_path):
    built = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'todos.db'}")
    async with built.begin() as connection:
        await connection.run_sync(metadata.create_all)
    yield built
    await built.dispose()


def _row(created_at: datetime) -> dict[str, object]:
    return {
        "id": TODO_ID,
        "title": "buy milk",
        "is_completed": False,
        "created_at": created_at,
    }


async def test_utc_datetime_aware_value_is_stored_as_naive_utc(engine):
    async with engine.begin() as connection:
        await connection.execute(
            insert(todos), _row(datetime(2026, 1, 2, 21, 4, 5, tzinfo=TOKYO))
        )
        stored = await connection.scalar(text("SELECT created_at FROM todos"))

    assert stored == "2026-01-02 12:04:05.000000"


async def test_utc_datetime_read_back_is_the_same_instant_in_utc(engine):
    written = datetime(2026, 1, 2, 21, 4, 5, tzinfo=TOKYO)
    async with engine.begin() as connection:
        await connection.execute(insert(todos), _row(written))
        read = await connection.scalar(select(todos.c.created_at))

    assert read == written
    assert read.tzinfo is UTC


async def test_utc_datetime_naive_value_raises_and_stores_nothing(engine):
    naive = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC).replace(tzinfo=None)

    with pytest.raises(StatementError, match=r"must be timezone-aware"):
        async with engine.begin() as connection:
            await connection.execute(insert(todos), _row(naive))

    async with engine.connect() as connection:
        assert await connection.scalar(select(todos.c.id)) is None


async def test_utc_datetime_none_passes_through_both_ways(engine):
    # A nullable column of this type (none exists yet) stores and reads NULL.
    async with engine.connect() as connection:
        read = await connection.scalar(
            select(bindparam("nothing", None, type_=UtcDateTime))
        )

    assert read is None


def test_metadata_names_constraints_by_the_naming_convention():
    assert todos.primary_key.name == "pk_todos"
