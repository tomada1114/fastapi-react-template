"""How the CLI reports failures: one line on stderr and a distinct exit code.

Expected failures — a domain error, a bad setting — are the user's to fix, so
they get a message rather than a traceback. Anything else is a bug and keeps
its traceback.
"""

from __future__ import annotations

from contextlib import contextmanager
from enum import IntEnum
from typing import TYPE_CHECKING

import typer
from pydantic import ValidationError

from my_app.core.errors import AppError
from my_app.settings import ENV_PREFIX, Settings

if TYPE_CHECKING:
    from collections.abc import Iterator


class ExitCode(IntEnum):
    """Every exit status ``my-app`` uses, so scripts can branch on the cause."""

    OK = 0
    DOMAIN_ERROR = 1  # an unknown id, an invalid title
    USAGE_ERROR = 2  # Typer's own: a missing or malformed argument
    CONFIG_ERROR = 3  # a MY_APP_* variable that does not validate


@contextmanager
def exit_on_domain_error() -> Iterator[None]:
    """Turn an ``AppError`` raised in the block into stderr and exit code 1.

    Only ``AppError`` is caught; it is reported, not logged, because it is the
    user's mistake rather than the program's.

    Raises:
        typer.Exit: With ``ExitCode.DOMAIN_ERROR`` when the block raised an
            ``AppError``.
    """
    try:
        yield
    except AppError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=ExitCode.DOMAIN_ERROR) from error


def load_settings() -> Settings:
    """Read ``Settings`` from the environment, or exit with code 3.

    Returns:
        The validated settings.

    Raises:
        typer.Exit: With ``ExitCode.CONFIG_ERROR`` and one line on stderr
            naming each invalid variable, instead of Pydantic's traceback.
    """
    try:
        return Settings()
    except ValidationError as error:
        problems = "; ".join(
            f"{ENV_PREFIX}{'_'.join(str(part) for part in detail['loc']).upper()}: "
            f"{detail['msg']}"
            for detail in error.errors()
        )
        typer.echo(f"Error: invalid configuration: {problems}", err=True)
        raise typer.Exit(code=ExitCode.CONFIG_ERROR) from error
