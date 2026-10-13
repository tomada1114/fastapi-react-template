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

`build_container` owns a `ResourceClosers` registry and passes it to adapter builders:
register cleanup with `resources.push_async_callback(adapter.aclose)`, and never close
an adapter in a service. Register only process-lifetime resources whose disposer can
run in a separate Task/Context on the resource's event loop. A context manager, task
group, cancellation scope, or context-variable token stays in its acquiring caller's
scope, which enters and exits it there; do not register its exit method as a disposer.
The registry exposes no context-manager entry or exception-suppression API, and
`Container` rejects a generic `AsyncExitStack` at construction. Registration is sealed
when the Container takes ownership.

The builder stays a plain `def` (a bad setting must fail in `create_app`), so a build
that raises runs no callback: register only an object that opens nothing when
constructed, as its docstring says. The registry moves to the frozen `Container`:
`aclose()` is idempotent, `async with container:` releases resources without suppressing
body exceptions, and a failing callback propagates after the rest run, preserving the
body error as its context. The API's lifespan awaits `aclose()` on a container its
factory built; a supplied `container=` stays caller-owned. Each `TestClient` context
runs the app on its own loop, so never reuse a container holding a loop-bound resource
across two of them. The SQL engine is registered with
`resources.push_async_callback(engine.dispose)`; **BACKGROUND:** `persisting-data`.

Cancellation does not release ownership early. Both exits await one Container-owned
cleanup task on the resource's event loop, protected from scope and direct-task
cancellation; concurrent closers share that drain. Callbacks finish once in LIFO order
before caller cancellation propagates. A cleanup failure still runs the remaining
callbacks and takes precedence over cancellation; a later close does not replay it.
Concurrent context exits each propagate their own body exception.
