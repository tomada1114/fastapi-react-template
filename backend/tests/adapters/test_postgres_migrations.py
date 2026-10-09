"""Exercise the migrations through a shared async PostgreSQL connection."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from my_app.adapters.sql.engine import make_engine
from tests.conftest import ALEMBIC_INI

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


async def test_postgres_migrations_upgrade_check_downgrade_upgrade(
    migrated_postgres_url,
):
    engine = make_engine(migrated_postgres_url)
    try:
        async with engine.begin() as connection:
            config = Config(ALEMBIC_INI)
            config.attributes["configure_logging"] = False
            config.attributes["connection"] = connection.sync_connection
            await connection.run_sync(lambda _: command.upgrade(config, "head"))
            await connection.run_sync(lambda _: command.check(config))
            await connection.run_sync(lambda _: command.downgrade(config, "base"))
            tables = await connection.run_sync(
                lambda conn: inspect(conn).get_table_names()
            )
            assert "todos" not in tables
            await connection.run_sync(lambda _: command.upgrade(config, "head"))
            await connection.run_sync(lambda _: command.check(config))
            tables = await connection.run_sync(
                lambda conn: inspect(conn).get_table_names()
            )
            assert "todos" in tables
    finally:
        await engine.dispose()
