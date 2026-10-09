---
name: designing-core-logic
description: >
  Covers what goes where beneath the entry points: models, rules, and services in
  src/my_app/core/, ports as typing.Protocol, the injected Clock, adapters in
  src/my_app/adapters/ and the shared repository contract suite, Settings in
  settings.py, and the composition root's build_container and Container. Use when
  adding a use case, a domain rule or model, a port, a repository or other adapter, or
  a MY_APP_ setting, or when ruff TID251 or tests/core/test_imports.py rejects an
  import in the core.
---

# Designing Core Logic

**Owns:** the layers beneath the entry points — what belongs in `core/`, how a port and
its adapters are shaped and tested, how configuration is read, and how
`composition.py` wires adapters into services. **Does not own:** the layer map
(AGENTS.md's "Architecture"); removing the API (`building-api-routes`); the
`AppError` hierarchy and its mapping (`designing-errors`); exposing a service over
HTTP (`building-api-routes`); module-level Python style (`writing-python`).

## The direction dependencies point

`api/` calls services from `core/`, which it receives only from
`composition.build_container`; `adapters/` implement the ports `core/` declares; `core/`
imports only itself and the deterministic standard-library modules allowed by
`ALLOWED_STDLIB` in `tests/core/test_imports.py`.

- Enforced by: `tests/core/test_imports.py`, the authoritative allowlist. It rejects
  every import outside the core and the allowlist, including third-party modules,
  other application layers, relative escapes, and imports inside `TYPE_CHECKING`.
  The check walks subpackages too. Adding an allowed module is a reviewed decision:
  it must do no I/O and read no clock, randomness, or environment; otherwise use a port.
- Enforced by: `pyproject.toml` `[tool.ruff.lint.flake8-tidy-imports.banned-api]`
  (`TID251`), a fast subset for common framework and driver mistakes. Its
  per-file-ignores let the outer layers use those dependencies.
- Enforced by: the AST call check in `tests/core/test_imports.py`, which rejects bare
  calls to `open`, `input`, `print`, `breakpoint`, `exec`, `eval`, `compile`, and
  `__import__`, plus `now`, `utcnow`, or `today` on a receiver name or attribute ending
  in `datetime` or `date`. It also rejects `date.fromtimestamp` on recognizable
  `date` receivers, `datetime.fromtimestamp` on recognizable `datetime` receivers
  without an explicit timezone, and any attribute call to `astimezone` without an
  explicit timezone. Positional or keyword `tz` arguments count as explicit unless
  they are literal `None`. This is a structural check, not alias or data-flow/type
  analysis: review must ensure supplied timezones are non-None and `astimezone`
  receivers are timezone-aware.

A new framework or driver the core must not touch gets a `banned-api` entry in the same
change that adds it; the per-file-ignores already let the outer layers use it.

## Models hold the invariants

A domain value is a frozen dataclass whose `__post_init__` refuses any state no rule
allows. The check runs on every construction — an adapter rebuilding a row,
`dataclasses.replace` producing a changed copy — so no code path can hold an invalid
value. A value that does not have its identity yet is its own type: `TodoDraft` has no
`id`, `Todo` has one, and both run `_check_invariants`.

A rule lives once, in the core, as a function every entry point reaches through a
service. `normalize_title` strips and length-checks a title; the API's request model
leaves the title as a plain `str`, so every entry point rejects the same input with
the same message.

## Services are the use cases

A service class groups the operations an entry point offers on one part of the domain.
Its constructor takes the ports and the clock it needs; its methods take what a user
supplies (`raw_title: str`, `todo_id: int`) and return domain models. Entry points call
a service and nothing below it, so a rule added to a service holds for every entry
point. A method's docstring records the behavior a caller may rely on — `complete`
returns an already-completed to-do unchanged, so a retried request is safe.

Excerpts in this skill drop docstrings where marked; the real code keeps them, because
ruff's `D` rules require them.

```python
def create(self, raw_title: str) -> Todo:
    # ... docstring elided
    draft = TodoDraft(title=normalize_title(raw_title), created_at=self._clock())
    return self._repository.add(draft)
```

Services are synchronous. FastAPI runs a synchronous route in its thread pool, so a
service and its adapters may be called from several threads at once; that is why
`InMemoryTodoRepository` takes a lock and `SqliteTodoRepository` opens a connection per
call.

## Ports describe what the core needs from outside

A port is a `typing.Protocol` in `core/ports.py`, typed with core models only. An
adapter satisfies it by shape and never imports or subclasses it. The port's docstrings
are the contract — what is returned, in what order, and what is raised — and
`TodoRepository` is `@runtime_checkable` so the contract suite can also assert that an
adapter has every method.

## Time and other outside inputs are injected

The core takes time, randomness, environment values, and I/O through injected ports.
The import allowlist and structural call check above enforce the stated boundaries;
review covers indirect calls and aliases the AST check cannot resolve. Current time
arrives through `Clock`, which any zero-argument callable returning a
timezone-aware `datetime` satisfies; a naive one is rejected by the model's invariant
check as a bug. Production passes `composition.utc_now`; tests pass the `fixed_clock`
fixture from `tests/conftest.py`, so a timestamp in an assertion is exact. Any other
outside input — randomness, an identifier generator, a remote call — gets a port of
the same kind rather than a direct call.

## Adapters implement a port

- An adapter in `adapters/` wraps one storage or I/O technology, holds no domain rule,
  and translates its driver's failures into the domain errors the port promises
  (`designing-errors`).
- It is safe to call from several threads; see "Services are the use cases".
- Its queries are module constants spelled out in full, never assembled at run time
  (`adapters/sqlite.py`).
- Every implementation of a port runs the one shared contract suite. A new repository
  joins `tests/adapters/test_repository_contract.py` by adding a `pytest.param` to
  `REPOSITORY_FACTORIES`; behavior only it has (the SQLite file outliving the object,
  persistence details) goes in `tests/adapters/test_<adapter>.py`. Concurrent adds
  must assign unique ids in every repository.
- The in-memory adapter doubles as the core's fake: `tests/core/test_services.py`
  builds a service over `InMemoryTodoRepository()` and `fixed_clock` instead of mocking
  the port.

## Settings are read once, at the boundary

`settings.py`'s `Settings` is the only place configuration enters, from
`MY_APP_`-prefixed environment variables (`ENV_PREFIX`). The one unprefixed variable is
the vendor's own `OPENROUTER_API_KEY`, read through a `validation_alias`
(`integrating-llm`). A new setting is a field on `Settings`:

- validated in a `field_validator`, so a bad value fails at startup with a message that
  says what to set, rather than on the first request;
- turned into the form the composition root needs by a property (`sqlite_path` turns
  `database_url` into a `Path`), so adapters never parse configuration strings;
- deleted from the environment by `tests/conftest.py`'s autouse `_isolate_settings_env`
  fixture, which derives the prefix and aliases from `Settings`, so a developer's
  shell cannot leak into a test without a hand-kept variable list;
- listed in the README's Configuration table.

## The composition root wires everything once

`composition.py` is the only module that constructs adapters and services.
`build_container(settings, clock=utc_now)` picks adapters from the settings
(`_build_repository`) and returns a frozen `Container` with one field per service; the
API stores it on `app.state`. A new service is a new
`Container` field built in `build_container`; a new adapter choice is a branch in the
function that picks it, driven by a setting.

```python
def build_container(settings: Settings, clock: Clock = utc_now) -> Container:
    # ... docstring elided
    with ExitStack() as resources:
        todos = TodoService(_build_repository(settings, resources), clock)
        return Container(todos=todos, _resources=resources.pop_all())
```

Tests build containers through the same function: the `make_container` fixture in
`tests/conftest.py` calls `build_container` with the fixed clock and in-memory storage
by default, and `tests/test_composition.py` covers the wiring itself.

## An adapter that holds a resource

`build_container` owns an `ExitStack` and passes it to adapter builders. Register a
resource immediately with `resources.enter_context(adapter)` or
`resources.callback(adapter.close)`; never close an adapter in a service. A failed
build closes the stack before propagating the error. A successful build transfers it
to the frozen `Container`, whose `close()` is idempotent and whose context manager
forwards exception details to registered context managers on exit and preserves their
suppression decision. Direct `close()` exits without an active exception. Cleanup
failures propagate while remaining callbacks still run.

The API builds services in its factory and closes that container in its lifespan. A
supplied container (`container=`) stays caller-owned: close it explicitly or use it as
a context manager. Current adapters acquire resources per call and register nothing here.

## Adding a use case

1. A rule the operation needs goes in the model or a core function, with its
   `InvalidTodoError`-style domain error. **REQUIRED:** `designing-errors`.
2. A method on the service, calling ports only, with `Args:`, `Returns:`, and `Raises:`.
3. A port method if storage must do something new, implemented in every adapter, and a
   contract-suite test that every adapter must pass.
4. Tests in `tests/core/` through the service's public methods, happy and error paths.
5. Expose it in each entry point the project keeps. **REQUIRED:** `building-api-routes`
   for a route, if the API exists.

## Adding a port and its adapters

For a new outside dependency — another store, a remote service, a source of randomness:

1. A `Protocol` in `core/ports.py`, typed with core models only, whose docstrings state
   what each method returns and raises.
2. One adapter per technology in `adapters/`, satisfying the port by shape, translating
   its driver's failures into the domain errors the port names, and safe across threads.
3. A contract suite for the port in `tests/adapters/test_<port>_contract.py`, written
   once and parametrized over every implementation the way `REPOSITORY_FACTORIES` is,
   plus `tests/adapters/test_<adapter>.py` for what only one adapter does.
4. An in-memory adapter that passes the same suite and serves as the core tests' fake.
5. The service that needs it takes it as a constructor parameter; `build_container`
   builds the adapter (choosing between implementations by a `Settings` field when
   there is more than one) and passes it in, and a new service gets its `Container`
   field.
6. An adapter retaining a resource follows "An adapter that holds a resource".
7. A new setting follows "Settings are read once, at the boundary"; a new driver
   follows "The direction dependencies point".

Run the narrowest checks while iterating: `uv run --locked pytest tests/core/
tests/adapters/ tests/test_composition.py tests/test_settings.py`.
