"""my-app: a framework-free core with a FastAPI API and a Typer CLI over it.

The layers depend inward only: ``api`` and ``cli`` call ``core`` services that
``composition`` wires to an ``adapters`` repository; ``core`` imports none of
them.
"""
