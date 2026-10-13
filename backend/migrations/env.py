"""Alembic's environment: how every ``alembic`` command reaches its database.

The URL comes from ``MY_APP_DATABASE_URL`` through ``Settings``, never from
``alembic.ini``, so no URL is ever committed. A caller that already holds a
connection hands it over in ``config.attributes["connection"]`` instead (the
Alembic cookbook's "Sharing a Connection"). The app itself never runs this:
migrations run explicitly (``just backend db-upgrade``), never at start-up.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING, Literal

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from my_app.adapters.sql.tables import UtcDateTime, metadata
from my_app.settings import Settings

if TYPE_CHECKING:
    from alembic.autogenerate.api import AutogenContext
    from sqlalchemy.engine import Connection

config = context.config

# The command line logs as alembic.ini says; a caller with logging of its own,
# such as a test run, sets config.attributes["configure_logging"] = False.
if config.config_file_name is not None and config.attributes.get(
    "configure_logging", True
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    """Return the URL ``MY_APP_DATABASE_URL`` names, validated by ``Settings``.

    Raises:
        RuntimeError: If the variable is unset or empty: there is no database
            to migrate.
    """
    url = Settings().database_url
    if url is None:
        msg = "MY_APP_DATABASE_URL must be set to run migrations"
        raise RuntimeError(msg)
    return url


def _render_item(
    type_: str, obj: object, _autogen_context: AutogenContext
) -> str | Literal[False]:
    """Render ``UtcDateTime`` as the ``DateTime`` it stores.

    A revision then imports nothing from the app, so a later change to
    ``tables.py`` cannot change what an old revision does. Every other item
    renders as Alembic's default.
    """
    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime()"
    return False


def run_migrations_offline() -> None:
    """Emit the migrations as SQL (``alembic upgrade head --sql``)."""
    context.configure(
        url=_database_url(),
        target_metadata=metadata,
        render_as_batch=True,
        render_item=_render_item,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations on an open connection.

    ``render_as_batch`` makes autogenerate write ``batch_alter_table`` blocks:
    SQLite has almost no ``ALTER TABLE``, so Alembic rebuilds the table there,
    and runs plain ``ALTER`` statements on every other database.
    """
    context.configure(
        connection=connection,
        target_metadata=metadata,
        render_as_batch=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open the configured database through its async driver and migrate it."""
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Migrate the caller's connection, else the database the URL names."""
    connection: Connection | None = config.attributes.get("connection")
    if connection is None:
        asyncio.run(run_async_migrations())
    else:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
