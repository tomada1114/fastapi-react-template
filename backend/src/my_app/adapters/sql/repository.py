"""A to-do repository on SQLAlchemy's asyncio Core."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Integer, bindparam, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from my_app.adapters.cursor import decode_after, page_of
from my_app.adapters.sql.tables import todos
from my_app.core.errors import TodoNotFoundError
from my_app.core.models import Todo

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncEngine

    from my_app.core.models import Page

# Built once at import, never per call: each is compiled and cached by its
# shape, and only the bound values change. The bound names differ from the
# column names, which SQLAlchemy reserves for an UPDATE's SET values.
_SELECT_ONE = select(todos).where(todos.c.id == bindparam("todo_id"))
_SELECT_FIRST_PAGE = (
    select(todos).order_by(todos.c.id).limit(bindparam("count", type_=Integer))
)
_SELECT_PAGE_AFTER = (
    select(todos)
    .where(todos.c.id > bindparam("after"))
    .order_by(todos.c.id)
    .limit(bindparam("count", type_=Integer))
)
_INSERT = insert(todos)
# No .values(): the SET clause comes from the column-named values passed with
# the statement, so one constant writes every column.
_UPDATE = update(todos).where(todos.c.id == bindparam("todo_id"))
_DELETE = delete(todos).where(todos.c.id == bindparam("todo_id"))


class SqlTodoRepository:
    """Store to-dos in the ``todos`` table through an ``AsyncEngine``.

    Each method checks out a pooled connection, runs one statement in its own
    transaction, and returns it, so concurrent calls never share a
    transaction. The engine belongs to the caller (``build_container``), which
    disposes of it; the schema belongs to the migrations, which must have run
    before the first call.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        """Use ``engine`` for every call.

        Args:
            engine: An engine on a database migrated to the head revision.
        """
        self._engine = engine

    async def add(self, todo: Todo) -> Todo:
        """Insert a new to-do under its own id.

        Args:
            todo: The to-do to store.

        Returns:
            ``todo``, now stored.

        Raises:
            ValueError: If a to-do with this id is already stored; the primary
                key refuses the row and the stored one is left unchanged.
        """
        try:
            async with self._engine.begin() as connection:
                await connection.execute(_INSERT, _values_of(todo))
        except IntegrityError as error:
            msg = f"A to-do with id {todo.id} is already stored"
            raise ValueError(msg) from error
        return todo

    async def get(self, todo_id: UUID) -> Todo:
        """Fetch one to-do.

        Args:
            todo_id: Any id; one never stored is simply not found.

        Returns:
            The stored to-do.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        async with self._engine.connect() as connection:
            result = await connection.execute(_SELECT_ONE, {"todo_id": todo_id})
            row = result.one_or_none()
        if row is None:
            raise TodoNotFoundError(todo_id)
        return _to_todo(row)

    async def list_page(self, cursor: str | None, limit: int) -> Page[Todo]:
        """Fetch one page of to-dos in ascending id order.

        Args:
            cursor: ``None`` for the first page, else a ``next_cursor``.
            limit: The most to-dos the page holds.

        Returns:
            The page, with a cursor when more to-dos follow it.

        Raises:
            InvalidCursorError: If ``cursor`` is not one this store issued.
        """
        # Decoded before any connection is taken, so a bad cursor costs none.
        after = None if cursor is None else decode_after(cursor)
        async with self._engine.connect() as connection:
            if after is None:
                result = await connection.execute(
                    _SELECT_FIRST_PAGE, {"count": limit + 1}
                )
            else:
                result = await connection.execute(
                    _SELECT_PAGE_AFTER, {"after": after, "count": limit + 1}
                )
            rows = result.all()
        return page_of([_to_todo(row) for row in rows], limit)

    async def update(self, todo: Todo) -> Todo:
        """Replace the stored to-do that has ``todo.id``.

        Args:
            todo: The new value.

        Returns:
            ``todo``, now stored.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        values = _values_of(todo)
        del values["id"]
        async with self._engine.begin() as connection:
            result = await connection.execute(_UPDATE, {"todo_id": todo.id, **values})
        if result.rowcount == 0:
            raise TodoNotFoundError(todo.id)
        return todo

    async def delete(self, todo_id: UUID) -> None:
        """Remove one to-do.

        Args:
            todo_id: Any id; one never stored is simply not found.

        Raises:
            TodoNotFoundError: If no to-do has this id.
        """
        async with self._engine.begin() as connection:
            result = await connection.execute(_DELETE, {"todo_id": todo_id})
        if result.rowcount == 0:
            raise TodoNotFoundError(todo_id)


def _values_of(todo: Todo) -> dict[str, Any]:
    """Return a to-do's column values, keyed by column name."""
    return {
        "id": todo.id,
        "title": todo.title,
        "is_completed": todo.is_completed,
        "created_at": todo.created_at,
    }


def _to_todo(row: Row[Any]) -> Todo:
    """Rebuild a domain to-do from a ``todos`` row, so no row leaves the adapter."""
    return Todo(
        id=row.id,
        title=row.title,
        created_at=row.created_at,
        is_completed=row.is_completed,
    )
