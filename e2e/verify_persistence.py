"""Confirm, from a process of its own, that the browser's to-do is in the database.

``e2e/tests/todos.spec.ts`` runs this once the screen has created and completed a
to-do, before it deletes it. A reload in the browser cannot tell a database from
an API that keeps to-dos in memory; this process builds its own container on the
same SQLite file, so it sees only what the API stored there.

Every ``Settings`` field is passed explicitly and ``backend/.env`` is not read, so
neither an inherited ``MY_APP_*`` variable nor the developer's dotenv file can
point it at another database. The container, and so its engine, is closed
before the process exits.

Usage:
    uv run --locked python e2e/verify_persistence.py DATABASE_URL TODO_ID TITLE

Exit status: 0 when a to-do with that id is stored with exactly that title and
completed; 1 when it is missing or differs, or the database cannot be read; 2 on
a usage error.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from my_app.composition import build_container
from my_app.core.models import MAX_PAGE_LIMIT
from my_app.settings import SQLITE_URL_PREFIX, Settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from my_app.core.models import Todo

USAGE_ERROR = 2


def isolated_settings(database_url: str) -> Settings:
    """Return Settings with every field set here and no dotenv file read.

    Keep the arguments equal to ``Settings``' fields: a field left out would be
    read from the environment or ``backend/.env``
    (``backend/tests/test_e2e_persistence.py`` fails when they disagree).
    """
    # Any is limited to BaseSettings' private constructor keyword, which
    # Pydantic's mypy plugin leaves out of Settings' signature.
    no_dotenv: dict[str, Any] = {"_env_file": None}
    return Settings(
        **no_dotenv,
        database_url=database_url,
        cors_origins=[],
        log_level="INFO",
        log_format="text",
    )


async def find_todo(settings: Settings, todo_id: uuid.UUID) -> Todo | None:
    """Return the stored to-do with ``todo_id``, or None, reading every page."""
    async with build_container(settings) as container:
        cursor: str | None = None
        while True:
            page = await container.todos.list_page(cursor, MAX_PAGE_LIMIT)
            for todo in page.items:
                if todo.id == todo_id:
                    return todo
            if page.next_cursor is None:
                return None
            cursor = page.next_cursor


def _problem(todo_id: uuid.UUID, title: str, todo: Todo | None) -> str | None:
    if todo is None:
        return f"no to-do {todo_id} is stored"
    if todo.title != title:
        return f"to-do {todo_id} is stored with title {todo.title!r}, not {title!r}"
    if not todo.is_completed:
        return f"to-do {todo_id} is stored, but not completed"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Check the database and report on stdout (stored) or stderr (anything else)."""
    parser = argparse.ArgumentParser(
        description="Confirm that the e2e flow's to-do is stored and completed."
    )
    parser.add_argument("database_url", help=f"{SQLITE_URL_PREFIX}<absolute path>")
    parser.add_argument("todo_id", type=uuid.UUID)
    parser.add_argument("title", help="the normalized title the API returned")
    args = parser.parse_args(argv)
    database_url: str = args.database_url
    if not database_url.startswith(SQLITE_URL_PREFIX):
        sys.stderr.write(f"error: not a SQLite URL: {database_url!r}\n")
        return USAGE_ERROR
    # SQLite would create a missing file, and then report a missing table.
    path = Path(database_url.removeprefix(SQLITE_URL_PREFIX).partition("?")[0])
    if not path.is_file():
        sys.stderr.write(f"error: no database file at {path}\n")
        return 1
    try:
        todo = asyncio.run(find_todo(isolated_settings(database_url), args.todo_id))
    except Exception as error:  # any failure to read the database fails the check
        sys.stderr.write(f"error: could not read {path}: {error!r}\n")
        return 1
    problem = _problem(args.todo_id, args.title, todo)
    if problem is not None:
        sys.stderr.write(f"error: {problem} in {path}\n")
        return 1
    sys.stdout.write(f"to-do {args.todo_id} is stored, completed, in {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
