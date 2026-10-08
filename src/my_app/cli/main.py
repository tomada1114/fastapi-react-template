"""The ``my-app`` root command: the ``todo`` group and ``serve``."""

from __future__ import annotations

import typer

from my_app.cli import todo
from my_app.cli.serve import serve

app = typer.Typer(help="Manage to-dos and serve the HTTP API.", no_args_is_help=True)
app.add_typer(todo.app, name="todo")
app.command()(serve)  # drop this line and cli/serve.py to ship without the API
