"""The SQL schema, declared once as Core ``Table`` metadata.

Alembic compares migrations against ``metadata`` (``backend/migrations/env.py``),
so a change here is followed by a revision (``just backend db-revision``). No
ORM class maps these tables: rows become core models inside the repositories.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, override

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    TypeDecorator,
    Uuid,
)

from my_app.core.models import MAX_TITLE_LENGTH

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect

# Every constraint and index gets a predictable name, so a later migration can
# drop or alter it by name on every database.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator[datetime]):
    """A timezone-aware ``datetime`` stored as naive UTC.

    SQLite has no timezone-aware type and PostgreSQL's converts on the way
    in, so storing naive UTC behaves the same on both: an aware value is
    converted to UTC and stored without its offset, and a value read back has
    UTC attached. A naive value is refused rather than guessed at: it is a bug
    in a clock or a caller, as ``Todo`` treats it.
    """

    impl = DateTime
    cache_ok = True

    @override
    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Convert an aware value to naive UTC for storage.

        Raises:
            ValueError: If ``value`` is naive.
        """
        if value is None:
            return None
        if value.utcoffset() is None:
            msg = f"{value.isoformat()} must be timezone-aware to be stored"
            raise ValueError(msg)
        return value.astimezone(UTC).replace(tzinfo=None)

    @override
    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Attach UTC to the naive UTC value the database returns."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


metadata = MetaData(naming_convention=NAMING_CONVENTION)

todos = Table(
    "todos",
    metadata,
    # The application generates ids (UUIDv7, ascending in creation order);
    # pages read in id order.
    Column("id", Uuid, primary_key=True),
    Column("title", String(MAX_TITLE_LENGTH), nullable=False),
    Column("is_completed", Boolean, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
)
