"""Lazy services shared across one CLI invocation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from my_app.cli.errors import load_settings
from my_app.composition import build_container

if TYPE_CHECKING:
    import typer

    from my_app.composition import Container


def get_container(ctx: typer.Context) -> Container:
    """Reuse supplied services or build them only when a command needs them."""
    if ctx.obj is not None:
        supplied: Container = ctx.obj
        return supplied
    owner = ctx.parent or ctx
    while owner.obj is None and owner.parent is not None:
        owner = owner.parent
    if owner.obj is None:
        owner.obj = build_container(load_settings())
        owner.call_on_close(owner.obj.close)
    container: Container = owner.obj
    return container
