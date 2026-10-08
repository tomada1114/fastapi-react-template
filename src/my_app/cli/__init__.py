"""The command-line entry point: a Typer app over the core services.

``my_app.cli.main:app`` is the ``my-app`` console script. Commands translate
arguments to service calls and domain errors to exit code 1, and hold no rules
of their own.
"""
