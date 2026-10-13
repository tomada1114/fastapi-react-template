# Adding a port and its adapters

Read when the core needs a new outside dependency — another store, a remote service, a
source of randomness — or when an adapter must hold a resource (a connection pool, an
engine, a client) between calls. `SKILL.md` holds the rules these steps apply.

## The steps

1. A `Protocol` in `core/ports.py`, typed with core models only, its I/O methods
   `async def`, whose docstrings state what each method returns and raises. A store's
   port follows `SKILL.md`'s "Ports any store can implement": ids from `IdFactory`,
   one access pattern per method, cursor pages.
2. One adapter per technology in `adapters/`, satisfying the port by shape, translating
   its driver's failures into the domain errors the port names, never blocking the loop.
3. A contract suite for the port in `backend/tests/adapters/test_<port>_contract.py`,
   written once and parametrized over every implementation the way
   `REPOSITORY_FACTORIES` is, plus `backend/tests/adapters/test_<adapter>.py` for what
   only one adapter does.
4. An in-memory adapter that passes the same suite and serves as the core tests' fake.
5. The service that needs it takes it as a constructor parameter; `build_container`
   builds the adapter (choosing between implementations by a `Settings` field when
   there is more than one) and passes it in, and a new service gets its `Container`
   field.
6. An adapter retaining a resource follows "An adapter that holds a resource" below.
7. A new setting follows `SKILL.md`'s "Settings are read once, at the boundary"; a new
   driver follows its "The direction dependencies point".

## An adapter that holds a resource

`build_container` owns an `AsyncExitStack` and passes it to adapter builders: register
cleanup with `resources.push_async_callback(adapter.aclose)`, and never close an adapter
in a service. It stays a plain `def` (a bad setting must fail in `create_app`), so a
build that raises runs no callback: register only an object that opens nothing when
constructed, as its docstring says. The stack moves to the frozen `Container`: its
`aclose()` is idempotent, `async with container:` forwards exception details to
registered context managers and keeps their suppression decision, and a failing callback
propagates after the rest run. The API's lifespan awaits `aclose()` on a container its
factory built; a supplied `container=` stays caller-owned. Each `TestClient` context
runs the app on its own loop, so never reuse a container holding a loop-bound resource
across two of them. The SQL repository's engine is registered this way
(`resources.push_async_callback(engine.dispose)`; **BACKGROUND:** `persisting-data`).
