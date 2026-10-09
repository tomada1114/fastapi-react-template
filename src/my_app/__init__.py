"""my-app: a framework-free core with a FastAPI API over it.

The layers depend inward only: ``api`` calls ``core`` services that
``composition`` wires to an ``adapters`` repository; ``core`` imports none of
them.
"""
