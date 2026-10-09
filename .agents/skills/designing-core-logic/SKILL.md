---
name: designing-core-logic
description: >
  Covers what goes where beneath the entry points: models, rules, and services in
  backend/src/my_app/core/, ports as typing.Protocol any store can implement (app-made
  UUIDv7 ids, cursor pages), the injected Clock and IdFactory, adapters in
  backend/src/my_app/adapters/ and the shared repository contract suite, Settings in
  settings.py, and the composition root's build_container and Container. Use when
  adding a use case, a domain rule or model, a port, a repository or other adapter, or
  a MY_APP_ setting, or when ruff TID251 or backend/tests/core/test_imports.py rejects
  core code.
---

# Designing Core Logic

**Owns:** the layers beneath the entry points — what belongs in `core/`, how a port and
its adapters are shaped and tested, how configuration is read, and how
`composition.py` wires adapters into services. **Does not own:** the layer map
(`backend/AGENTS.md`'s "Architecture"); removing the API (`building-api-routes`); the
`AppError` hierarchy and its mapping (`designing-errors`); exposing a service over
HTTP (`building-api-routes`); module-level Python style (`writing-python`).

## The direction dependencies point

`api/` calls services from `core/`, which it receives only from
`composition.build_container`; `adapters/` implement the ports `core/` declares; `core/`
imports only itself and the deterministic standard-library modules allowed by
`ALLOWED_STDLIB` in `backend/tests/core/test_imports.py`.

- Enforced by: `backend/tests/core/test_imports.py`, the authoritative allowlist. It
  rejects every import outside the core and the allowlist, including third-party
  modules, other application layers, relative escapes, and imports inside
  `TYPE_CHECKING`, in subpackages too. Adding an allowed module is a reviewed decision:
  it must do no I/O and read no clock, randomness, or environment; otherwise use a port.
- Enforced by: `backend/pyproject.toml`'s `[tool.ruff.lint.flake8-tidy-imports.banned-api]`
  (`TID251`), a fast subset for common framework and driver mistakes. Its
  per-file-ignores let the outer layers use those dependencies.
- Enforced by: the AST call check in `backend/tests/core/test_imports.py`, which rejects
  bare calls to `open`, `input`, `print`, `breakpoint`, `exec`, `eval`, `compile`, and
  `__import__`; `now`, `utcnow`, or `today` on a receiver name or attribute ending in
  `datetime` or `date`; and `uuid1`, `uuid4`, `uuid6`, or `uuid7`, bare or on a `uuid`
  receiver (the `UUID` type is allowed; ids come from `IdFactory`). It also rejects
  `date.fromtimestamp` on recognizable `date` receivers, `datetime.fromtimestamp` on
  recognizable `datetime` receivers without an explicit timezone, and any attribute
  call to `astimezone` without an explicit timezone. Positional or keyword `tz`
  arguments count as explicit unless they are literal `None`. This is a structural
  check, not alias or data-flow/type analysis: review must ensure supplied timezones
  are non-None and `astimezone` receivers are timezone-aware.

A new framework or driver the core must not touch gets a `banned-api` entry in the same
change that adds it; the per-file-ignores already let the outer layers use it.

## Models hold the invariants

A domain value is a frozen dataclass whose `__post_init__` refuses any state no rule
allows. The check runs on every construction — an adapter rebuilding a row,
`dataclasses.replace` producing a changed copy — so no code path can hold an invalid
value. A `Todo` has its id from the start: the service takes it from `IdFactory` before
any repository sees the value.

A rule lives once, in the core, as a function every entry point reaches through a
service. `normalize_title` strips and length-checks a title; the API's request model
leaves the title as a plain `str`, so every entry point rejects the same input with
the same message.

## Services are the use cases

A service class groups the operations an entry point offers on one part of the domain.
Its constructor takes the ports, the clock, and the id factory it needs; its methods
take what a user supplies (`raw_title: str`, `todo_id: UUID`) and return domain models.
Entry points call a service and nothing below it, so a rule added to a service holds for
every entry point. A method's docstring records the behavior a caller may rely on —
`complete` returns an already-completed to-do unchanged, so a retried request is safe.

```python
async def create(self, raw_title: str) -> Todo:
    # ... docstring elided
    title = normalize_title(raw_title)
    todo = Todo(id=self._new_id(), title=title, created_at=self._clock())
    return await self._repository.add(todo)
```

The repository path is async end to end: port methods, service methods, and routes are
`async def`, awaiting the layer below; a rule, a calculation, `Clock`, and `IdFactory`
stay `def`.

## Ports describe what the core needs from outside

A port is a `typing.Protocol` in `core/ports.py`, typed with core models only, its I/O
methods `async def`. An adapter satisfies it by shape and never imports or subclasses
it. The port's docstrings are the contract — what is returned, in what order, and what
is raised — and `TodoRepository` is `@runtime_checkable` so the contract suite can also
assert that an adapter has every method.

## Ports any store can implement

A repository port must suit a SQL database and a key-value store such as DynamoDB
alike, so every one follows six rules:

1. **The application generates ids.** `Todo.id` is a `UUID` from the injected
   `IdFactory`; no store assigns one. `add` of an id already stored raises `ValueError`
   (a factory bug) and overwrites nothing, as a primary key or a conditional put does.
2. **A method is one access pattern** — `get(todo_id)`, `list_page(cursor, limit)` —
   never an arbitrary query, join, or filter builder.
3. **A list pages by an opaque cursor, never by offset.** `list_page` returns a
   `Page[Todo]` ascending by id, reading `limit + 1` items so `next_cursor` is `None`
   exactly on the last page. `adapters/cursor.py` (`encode_after`, `decode_after`, which
   raises `InvalidCursorError`) is the shared cursor; a store with its own token keeps it
   in its adapter. The service owns the limit (`MAX_PAGE_LIMIT`, `InvalidPageLimitError`).
4. **No store type crosses the adapter boundary** — no row, session, ORM object, or
   query; the core sees only its own values.
5. **A write that must be atomic across items is one port method,** implementable as a
   SQL transaction or a DynamoDB `TransactWriteItems`.
6. **Timestamps are timezone-aware UTC**; `Todo` rejects a naive `created_at`.

## Time and other outside inputs are injected

The core takes time, randomness, environment values, and I/O through injected ports.
The import allowlist and structural call check above enforce the stated boundaries;
review covers indirect calls and aliases the AST check cannot resolve. Current time
arrives through `Clock`, which any zero-argument callable returning a
timezone-aware `datetime` satisfies; a naive one is rejected by the model's invariant
check as a bug. Production passes `composition.utc_now`; tests pass the `fixed_clock`
fixture from `backend/tests/conftest.py`, so a timestamp in an assertion is exact. Ids
arrive the same way through `IdFactory`: production passes `uuid.uuid7`, ascending in
creation order; tests pass the `new_id` fixture, whose ids are v7-shaped and ascend
(`nth_id(n)` is the n-th). Any other outside input — randomness, a remote call — gets a
port of the same kind rather than a direct call.

## Adapters implement a port

- An adapter in `adapters/` wraps one storage or I/O technology, holds no domain rule,
  and translates its driver's failures into the domain errors the port promises
  (`designing-errors`).
- It never blocks the event loop. `InMemoryTodoRepository` never awaits inside a
  read-modify-write, so it needs no lock; `SqlTodoRepository` awaits an async driver
  through SQLAlchemy's asyncio API, one pooled connection per call.
- Its queries are module constants, never assembled at run time. The SQL side —
  tables, statements, the engine, migrations — is **REQUIRED:** `persisting-data`.
- Every implementation of a port runs the one shared contract suite. A new repository
  joins `backend/tests/adapters/test_repository_contract.py` by adding a `pytest.param`
  to `REPOSITORY_FACTORIES`, an async context manager yielding it on a fresh store;
  behavior only it has goes in `backend/tests/adapters/test_<adapter>.py`. Concurrent
  adds must all be stored in every repository (200 `add` calls in one task group).
- The in-memory adapter doubles as the core's fake: `backend/tests/core/test_services.py`
  builds a service over `InMemoryTodoRepository()`, `fixed_clock`, and `new_id` instead
  of mocking the port.

## Settings are read once, at the boundary

`settings.py`'s `Settings` is the only place configuration enters, from
`MY_APP_`-prefixed environment variables (`ENV_PREFIX`). A new setting is a field on
`Settings`:

- validated in a `field_validator`, so a bad value fails at startup with a message that
  says what to set, rather than on the first request;
- checked with string rules only, so `settings.py` imports no adapter's library, and
  handed to the composition root in the form an adapter takes (a URL);
- deleted from the environment by `backend/tests/conftest.py`'s autouse
  `_isolate_settings_env` fixture, which derives the prefix and aliases from `Settings`,
  so a developer's shell cannot leak into a test without a hand-kept variable list;
- listed in the README's Configuration table. `database_url` selects storage;
  `cors_origins` is a comma-separated list of exact HTTP(S) origins, normalized and
  validated here but consumed by the API factory rather than the composition root.
  Blank values mean unset; a bad value names the rejected item at startup.

## The composition root wires everything once

`composition.py` is the only module that constructs adapters and services.
`build_container(settings, clock=utc_now, new_id=uuid.uuid7)` picks adapters from the
settings (`_build_repository`) and returns a frozen `Container` with one field per
service; the API stores it on `app.state`. A new service is a new `Container` field
built in `build_container`; a new adapter choice is a branch in the function that picks
it, driven by a setting.

```python
def build_container(
    settings: Settings, clock: Clock = utc_now, new_id: IdFactory = uuid.uuid7
) -> Container:
    # ... docstring elided
    resources = AsyncExitStack()
    repository = _build_repository(settings, resources)
    todos = TodoService(repository, clock, new_id)
    return Container(todos=todos, _resources=resources)
```

Tests build containers through the same function: `backend/tests/conftest.py`'s
`make_container` passes the fixed clock, `new_id`, and in-memory storage by default, and
`backend/tests/test_composition.py` covers the wiring itself.

## Adding a use case

1. A rule the operation needs goes in the model or a core function, with its
   `InvalidTodoError`-style domain error. **REQUIRED:** `designing-errors`.
2. An `async def` method on the service, awaiting ports only, with `Args:`,
   `Returns:`, and `Raises:`.
3. A port method if storage must do something new, implemented in every adapter, and a
   contract-suite test that every adapter must pass.
4. Tests in `backend/tests/core/` through the service's public methods, happy and error paths.
5. Expose it in each entry point the project keeps. **REQUIRED:** `building-api-routes`
   for a route, if the API exists.

## Adding a port and its adapters

For a new outside dependency — another store, a remote service, a source of randomness —
work through [references/adding-a-port.md](references/adding-a-port.md): the `Protocol`
under "Ports any store can implement", one adapter per technology, its contract suite
and in-memory fake, the wiring in `build_container`, and the cleanup of an adapter that
holds a resource (`AsyncExitStack`, `Container.aclose()`).

Run the narrowest checks while iterating, from the repository root:
`uv run --locked --directory backend pytest tests/core/ tests/adapters/ tests/test_composition.py tests/test_settings.py`.
