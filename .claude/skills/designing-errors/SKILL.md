---
name: designing-errors
description: >
  Covers the AppError hierarchy in backend/src/my_app/core/errors.py and how the API reports
  it: when a failure earns a subclass, what its message and attributes carry,
  translating a driver error in an adapter, and the HTTP status _status_for in
  api/app.py gives it with an ErrorResponse body (404, 422, 400 fallback). Use when adding a failure mode, choosing a status,
  seeing an unexpected 500 or traceback, or deciding whether to log an error.
---

# Designing Errors

**Owns:** what counts as a domain error, the `AppError` hierarchy, and the table that
turns one into an HTTP status. **Does not own:** where the rule that raises an error
lives (`designing-core-logic`); the shape of a route and its `responses=` declaration
(`building-api-routes`); `raise ... from`, the `EM` message variable, and logging calls
in general (`writing-python`).

## Two kinds of failure

- **Expected:** the user's input or the state of their data breaks a domain rule — an
  unknown id, an invalid title. It is raised as an `AppError` subclass, and the API
  turns it into an HTTP status in exactly one place. It is reported, not logged, and
  never shows a traceback.
- **A bug:** anything else — a naive `datetime` from a clock, a driver error nobody
  translated. It is a builtin exception or left to propagate, and it keeps its
  traceback: the API answers a plain-text `500 Internal Server Error` while the
  traceback goes to the server's log (observed with starlette 1.3.1 and fastapi
  0.139.2, 2026-10-06). Never catch `Exception` to dress a bug up as a domain error.

`core/models.py` draws the line in one function: `_check_invariants` raises
`InvalidTodoError` for a bad title but a plain `ValueError` for a naive `created_at`,
because "That is a bug in a clock or an adapter, not bad user input".

## The hierarchy

Every domain error derives from `AppError`, the package's one base exception, so an
entry point can catch the whole family with a single `except`. A failure earns its own
subclass when a caller must tell it apart — an entry point maps it differently, or a
caller needs data it carries. Otherwise raise an existing class with a new message.

- Keep the data a caller needs as attributes, so nobody parses the message.
- Pass exactly the constructor's arguments to `super().__init__`, so pickling (process
  pools, task queues) rebuilds an equal error. `backend/tests/core/test_errors.py`
  checks the round trip only for the subclasses listed in its parametrized tests, so
  each new one is added there (step 5 below).
- `str(error)` is the user-facing sentence, and the API shows it verbatim as `detail`.
  It must be safe to hand a client: never a credential, a SQL statement, a server path,
  or a stack detail.

`TodoNotFoundError` has all three properties. Excerpts in this skill drop docstrings
where marked; the real code keeps them, because ruff's `D` rules require them.

```python
class TodoNotFoundError(AppError):
    # ... docstrings elided
    def __init__(self, todo_id: int) -> None:
        super().__init__(todo_id)
        self.todo_id = todo_id

    def __str__(self) -> str:
        return f"To-do {self.todo_id} not found"
```

A message-only error takes the message as its one argument, built in a variable first:
`normalize_title` builds `msg` and raises `InvalidTodoError(msg)`.

## Raise in the core, translate in the adapter

The core raises a domain error where it checks the rule. An adapter translates its
driver's failure into the error the port's `Raises:` section promises, because the
port's docstring is the contract and
`backend/tests/adapters/test_repository_contract.py` holds every adapter to it.
`InMemoryTodoRepository` turns a `KeyError` into
`TodoNotFoundError`; `SqliteTodoRepository` answers an id outside SQLite's 64-bit range
(`SQLITE_MIN_INTEGER`, `SQLITE_MAX_INTEGER`) as not found before binding it, instead of
letting `OverflowError` escape. A driver failure with no domain meaning — a locked
database, a full disk — stays a bug and propagates.

## The HTTP mapping

`create_app` registers one handler for `AppError`, and no route catches one. The status
table is `_status_for` in `api/app.py`, and nowhere else:

| Core error | HTTP status |
|---|---|
| `TodoNotFoundError` | 404 `HTTPStatus.NOT_FOUND` |
| `InvalidTodoError` | 422 `HTTPStatus.UNPROCESSABLE_CONTENT` |
| any other `AppError` | 400 `HTTPStatus.BAD_REQUEST` |

The body is always `ErrorResponse`, `{"detail": str(error)}`. FastAPI's own 422 for a
request that does not parse (a missing field, a non-integer path parameter) keeps its
list-shaped `detail`, so a client tells the two apart by the type of `detail`.

Each status names a cause. 404 means the named thing does not exist. 422 means the
request parsed but its input breaks a domain rule on a field — `InvalidTodoError`'s
kind of failure. A new error class gets its own case when a specific status names its
cause: 404 for something missing, 409 `HTTPStatus.CONFLICT` for a conflict with the
current state such as a duplicate, 422 for invalid input.

400 is only the fallback for an `AppError` that has no case yet: it keeps an unmapped
subclass the client's problem, never an unhandled 500, and
`backend/tests/api/test_app.py::test_unmapped_app_error_returns_400_not_500` pins it. Never
choose 400 on purpose for a new error; give it the status that names its cause.

Adding a status for a new error:

1. Add a `case` to `_status_for`, with a subclass's case above its base class's.
2. List the status, with `ErrorResponse` as its model, in `responses=` on every route
   that can raise the error.
3. Assert the status and the exact `{"detail": ...}` in a `TestClient` test, and add
   the route's status to the parametrized OpenAPI test in
   `backend/tests/api/test_todos.py`.
4. Describe the status in the README beside the existing 404 and 422.

```python
match error:
    case TodoNotFoundError():
        status = HTTPStatus.NOT_FOUND
    case InvalidTodoError():
        status = HTTPStatus.UNPROCESSABLE_CONTENT
    case _:
        status = HTTPStatus.BAD_REQUEST
return status
```

Each case assigns and one `return` follows the `match`, which keeps ruff's `PLR0911`
return-count limit from capping how many errors get a status.

## Configuration errors

An invalid setting is not an `AppError`: Pydantic raises `ValidationError` when
`Settings()` is built. The API does not map it: `create_app()` without settings, as
uvicorn's `--factory` calls it for `just dev`, fails to start with the traceback.
Validate a new setting in a `field_validator`, so it fails at startup rather than on
the first request (`designing-core-logic`).

## Logging

An `AppError` is expected, so it is mapped at the API boundary to an HTTP status, and
not logged with `logging.exception()`. An
unexpected error keeps its traceback; code that catches one to add context logs it with
`logging.exception()` and re-raises.

## Adding a failure mode

1. Can an existing class carry it with the same mapping? Reuse it with a new message.
2. Otherwise subclass `AppError` beside the existing errors, with its data as
   attributes, a pickle-safe `__init__`, and a client-safe `__str__`.
3. Raise it in the core where the rule is checked, or translate to it in an adapter, and
   name it in the `Raises:` section of the port or service method.
4. If the project has the API: give it a status by the steps in "The HTTP mapping",
   with a mapping test. **REQUIRED:** `building-api-routes`.
5. Required, not optional: add a `pytest.param` for it to both parametrized tests in
   `backend/tests/core/test_errors.py` (it is an `AppError`; its pickle round trip keeps
   type, message, and args), plus a test for any attribute it carries.
6. Update the README where it describes the API's error statuses.
