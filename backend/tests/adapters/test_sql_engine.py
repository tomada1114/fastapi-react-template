"""How the shared engine connects, below what the repository contract can see."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from my_app.adapters.sql.engine import SQLITE_BUSY_TIMEOUT_SECONDS, make_engine

pytestmark = pytest.mark.anyio


async def test_make_engine_sqlite_waits_out_a_locked_file_instead_of_failing(tmp_path):
    # 200 concurrent adds on one file (the contract suite) queue for SQLite's
    # write lock; a connection that gives up early fails with "database is
    # locked", so every connection waits out the busy timeout first.
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'todos.db'}")
    try:
        async with engine.connect() as connection:
            busy_timeout_ms = await connection.scalar(text("PRAGMA busy_timeout"))
    finally:
        await engine.dispose()

    assert busy_timeout_ms == SQLITE_BUSY_TIMEOUT_SECONDS * 1000
