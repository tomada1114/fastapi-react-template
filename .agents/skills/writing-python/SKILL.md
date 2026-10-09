---
name: writing-python
description: >
  Covers how one module, class, or function is written in any layer of
  backend/src/my_app/ or in scripts/: a commented Any, TYPE_CHECKING imports and the
  annotations Pydantic and FastAPI read at run time, frozen dataclass versus Pydantic
  versus TypedDict versus Protocol, enums and named constants, docstrings, EAFP, context
  managers, match, logger calls, and a justified noqa. Use when writing or reviewing
  Python code, or fixing a ruff or mypy finding. Whether to log an error at all is
  designing-errors'.
---

# Writing Python

**Owns:** how one module, class, or function is written, in any layer of
`backend/src/my_app/` and in `scripts/`, including two rules other skills point here
for: one-line route docstrings, and never shadowing a builtin. **Does not own:** which
layer code belongs in, and the shape of models, ports, services, and adapters
(`designing-core-logic`); the `AppError` hierarchy, how an entry point reports it, and
whether an error is logged (`designing-errors`); a route (`building-api-routes`); how
a test is written (`writing-tests`); the contract a
repository script keeps — imports, `main()`, `ERR_*` reports (`writing-repo-scripts`).

## Gates first

Enforced by: the root `pyproject.toml`'s `[tool.ruff.lint] select` list (which
`backend/pyproject.toml` extends) and each file's `[tool.mypy]` `strict = true` — read
the finding they report rather than a copy of their rules here.
Two of them carry a policy on top:

- mypy's `ignore-without-code` error code makes a `# type: ignore` name its error code.
  The reason written beside it, like the reason on a `noqa` or a per-file ignore, is
  AGENTS.md's policy ("Security and human approval"); no tool checks it.

- Ruff's bandit rules (`S`) stay on; a `noqa` for one argues that specific check.

## Imports a framework reads at run time stay real

With postponed annotations, a name used only in an annotation belongs under
`if TYPE_CHECKING:`, and ruff's `TC` rules move it there. Pydantic models and FastAPI
routes read their annotations at run time, so the types they name must stay real
imports. The root `pyproject.toml`'s `[tool.ruff.lint.flake8-type-checking]`
lists those base classes and decorators so ruff leaves them alone; a new framework hook
that reads annotations is added to that list, never silenced with a `noqa`. A FastAPI
dependency function has no decorator for that list to name — `building-api-routes`
covers that case.

`api/schemas.py` has both kinds in one file: `datetime` is a real import because a
`BaseModel` field names it, while `Todo` appears only in a method signature.

```python
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from my_app.core.models import Todo
```

## Choosing a type for a value

- **An internal value:** `@dataclass(frozen=True, slots=True)`. A change is a new value
  built with `dataclasses.replace`, never an in-place edit (`Todo`, `Page`,
  `composition.Container`).
- **Pydantic `BaseModel`:** only at a serialization boundary — the wire format in
  `api/schemas.py` and the environment in `settings.py`. Never in `core/`.
- **`Protocol`, not an ABC,** for an interface (`core/ports.py`); `@runtime_checkable`
  only when a test must `isinstance` against it.
- **`TypedDict`** for a dict whose keys are fixed, such as a JSON shape you do not own.
  No module needs one yet.
- **`enum.Enum`** for a closed set instead of loose string constants; `IntEnum` when the
  members are also numbers, as the standard library's `HTTPStatus` is. Inside a
  Pydantic model a `Literal` field does that job on the wire (`HealthResponse.status`).
- **`Any`** only with a comment saying why nothing narrower fits, as in
  `api/routers/todos.py`:
  ``# Any: FastAPI's own type for `responses=` values is dict[str, Any].``

## Names and constants

- A literal that carries meaning is an `UPPER_SNAKE_CASE` module constant in the module
  that owns the meaning (`MAX_TITLE_LENGTH`, `SQLITE_URL_PREFIX`, `ENV_PREFIX`);
  another module imports it rather than repeating the value.
- A boolean is named `is_`, `has_`, `can_`, or `should_` (`Todo.is_completed`). A wire
  format may spell it differently; the schema owns that mapping.
- A private helper is `_name`, an internal module `_name.py`; `__name` only to avoid a
  clash in a subclass hierarchy.
- **Never shadow a builtin.** A function whose natural name is a builtin gets a
  descriptive name instead: the route that lists to-dos is `async def list_todos(...)`
  under `@router.get("")`, never `async def list(...)`.

## Functions, modules, and docstrings

- A 300-line module or a 40-line function is a review trigger, not a rule: split only
  along a real responsibility boundary. One logical concern per module.
- Prefer three or fewer parameters; group related ones in a frozen dataclass. An
  optional collaborator goes keyword-only after `*`:
  `create_app(settings=None, *, container=None)`.
- A Google-style docstring says why, not what the signature says. "A factory rather
  than a module-level `app` so each test gets a fresh store" belongs there.
- **A FastAPI route's docstring is one plain-text line,** because it is published as
  OpenAPI text. Its reasoning goes in a comment or the
  module docstring.

## Idioms

- **EAFP** for lookups and I/O: try the operation and translate the specific exception,
  rather than checking first. `adapters/memory.py` does it for a missing key:

  ```python
  try:
      return self._todos[todo_id]
  except KeyError:
      raise TodoNotFoundError(todo_id) from None
  ```

  `from None` drops a cause that adds nothing; `from error` keeps one that does.
- **A context manager for every resource.** Acquire it with `with` or `async with`
  so it is released on every path: `SqlTodoRepository` takes each connection with
  `async with self._engine.begin() as connection:`, which commits, or rolls back on an
  error, and returns the connection to the pool. When an object's own `with` does not
  release it, compose `contextlib.closing`; a reusable boundary is a
  `@contextmanager` or `@asynccontextmanager` function.
- **`match`/`case`** for dispatch on type or shape (`_status_for` in `api/app.py`).
- **The walrus operator** where it removes a repeated expression, as in
  `if (found := pattern.search(text)) is not None:`.
- **Comprehensions** over `map()` and `filter()`; `*args`/`**kwargs` only when a call
  genuinely forwards them.
- **Time is never read directly** in the core; it arrives through the injected `Clock`
  (`designing-core-logic`).

## Exceptions and logger calls

- Catch the most specific exception that can happen, and handle it meaningfully or
  re-raise it; never swallow one, and never use one for ordinary control flow. Return
  `None` only when the caller expects absence.
- No module under `backend/src/my_app/` logs yet; uvicorn's own log is the only one.
  When one does, it uses a module-level `logging.getLogger(__name__)` and calls
  `logger.exception(...)` inside the `except` block, which keeps the traceback — never
  `logger.error(str(error))`. **BACKGROUND:** `designing-errors` decides which errors
  are logged at all.

## Security

- A path built from outside input is resolved with `Path.resolve()` and checked to stay
  under its allowed root before it is opened.
- SQL takes values only through bound parameters, with the statement a module
  constant built once (`adapters/sql/repository.py`'s `_SELECT_ONE` and siblings,
  `persisting-data`); never a string assembled from input.
- A subprocess takes a fixed argv list, never `shell=True`; its `# noqa: S603` names why
  the argv is safe (`backend/tests/test_composition.py`).

## Performance

Do not optimize preemptively. Profile a measured hotspot first, and put the measurement
in the pull request description.
