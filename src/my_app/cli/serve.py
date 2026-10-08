"""``my-app serve``: the CLI's only bridge to the HTTP API.

It is a module of its own so that dropping the API means deleting it and its
one registration line in ``cli/main.py``. FastAPI and uvicorn are imported
inside the command, so ``my-app todo ...`` never loads the server stack.
"""

from __future__ import annotations

from typing import Annotated

import typer

from my_app.cli.errors import load_settings

# Loopback by default: exposing the server beyond this machine is an explicit
# `--host 0.0.0.0`, never an accident.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def serve(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = DEFAULT_HOST,
    port: Annotated[int, typer.Option(help="Port to listen on.")] = DEFAULT_PORT,
) -> None:
    """Serve the HTTP API with uvicorn until interrupted."""
    # Deferred imports: only this command needs the server stack.
    import uvicorn  # noqa: PLC0415 - keeps `my-app todo` from importing uvicorn

    from my_app.api.app import create_app  # noqa: PLC0415 - and FastAPI

    uvicorn.run(create_app(load_settings()), host=host, port=port)
