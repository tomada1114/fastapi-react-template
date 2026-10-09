---
name: building-api-routes
description: >
  Covers the FastAPI entry point in backend/src/my_app/api/: the create_app factory and
  app.state.container, service dependencies in dependencies.py, one APIRouter per
  resource under routers/, Pydantic request and response models in schemas.py, success
  status codes and the responses= declaration, and TestClient tests through the client
  fixture. Use when adding or changing an HTTP route, a request or response body, a
  dependency, or a router, or when removing the API. Which status a domain error
  becomes is designing-errors'. The skill is deleted along with backend/src/my_app/api/.
---

# Building API Routes

**Owns:** everything under `backend/src/my_app/api/` and `backend/tests/api/` — the
factory, the dependencies, the routers, the wire-format models, and how a route is
tested.
**Does not own:** which status a domain error becomes (`designing-errors`); the service
a route calls (`designing-core-logic`); trying a route against a live server
(`running-the-app`); module-level Python style (`writing-python`).

## A project without the API

This skill describes the HTTP entry point, the only one the template ships. Dropping it
is a deletion, never a core change, and leaves the core as a library with no entry
point of its own:

- delete `backend/src/my_app/api/` and `backend/tests/api/`;
- remove the `fastapi` and `uvicorn` runtime dependencies from `backend/pyproject.toml`
  and the `httpx2` and `httpx` dev dependencies `TestClient` uses from the root
  `pyproject.toml`, then run `uv lock`;
- remove the `dev` recipes, `backend/justfile`'s and the root's `dev: backend::dev`, and
  the lines that name them (README's Quickstart and Development block, AGENTS.md's
  Quick Reference and the paragraph under it, `backend/AGENTS.md`;
  `just check-harness` fails while one remains), and in `backend/pyproject.toml`'s
  ruff config the `fastapi` and `uvicorn` entries and the API package's per-file-ignore;
- update `backend/AGENTS.md`'s opening paragraph and its Architecture tree and bullets
  to describe the core alone; in the paragraph after AGENTS.md's Quick Reference,
  remove the server instructions that require the deleted API;
- update README: remove Quickstart's `just dev`, curl, API docs and HTTP table, all
  HTTP status/`detail` prose, and the server Configuration
  note; rewrite Architecture for the core alone and remove the pointer to this deleted
  skill;
- replace the HTTP request in `.github/ISSUE_TEMPLATE/bug_report.yml`'s reproduction
  placeholder with a call into the core;
- delete `.agents/skills/building-api-routes/`, remove its row from AGENTS.md's Skills
  table, and run `just agents-sync`.

Then prune what sibling skills say about the API:

- `designing-errors`: "The HTTP mapping", step 4 of "Adding a failure mode", and the
  API's part of "Two kinds of failure", "Configuration errors", and "Logging";
- `designing-core-logic`: the `building-api-routes` pointers, and the routes and
  `create_app` in what "Services are the use cases" and "An adapter that holds a
  resource" say about the async path and the lifespan;
- `running-the-app`: "Running a server of your own" and the server tier of "Evidence,
  cheapest first", which leaves a test as its only tier;
- `writing-python`: the examples that quote `api/` files;
- `writing-tests`, `placing-tests`, `tdd`, and `updating-docs`: their mentions of the
  `client` fixture, `backend/tests/api/`, a route, or an HTTP status.

## How a request flows

A route function receives its typed parameters and a service from a dependency, calls
one service method, and maps the domain result to a response model. A domain error
propagates out of the route untouched; the one `AppError` handler `create_app`
registers answers it. A route holds no rule, no `try`/`except` for an `AppError`, and
no `HTTPException` for a domain failure.

## The factory

`create_app(settings=None, *, container=None)` in `api/app.py` builds a new application
per call; there is no module-level `app`. It builds a container from `settings` (read
from the environment when omitted), or takes one a test built, and stores it on
`app.state.container`. Building remains in the factory, so configuration errors fail
at startup. Its lifespan awaits `aclose()` only on the container it built; a supplied
`container=` stays caller-owned. Use `TestClient` as a context manager to run lifespan
shutdown.
It includes resource routers under `API_PREFIX` (`/api`), leaves probes such as
`/healthz` at the root, and registers the `AppError` handler. It reads HTTP settings
also when a caller supplies a container. A non-empty `cors_origins` wraps the complete
middleware stack with CORS, including server-error responses; the stack is built
lazily so a caller can still register middleware before startup.

- A new router is a module under `api/routers/`, added to the imports and included with `app.include_router(router, prefix=API_PREFIX)`.
- Each route function name is its public generated-client operation id; keep names
  unique across routers. `route_operation_id` and the operation-id tests enforce it.
- The API never constructs an adapter or a service: they come only from
  `composition.build_container` (`designing-core-logic`).
- `just dev` serves it through `uvicorn my_app.api.app:create_app --factory`; an
  agent's own server runs the same command on a free port (`running-the-app`).

## Dependencies hand routes their services

`api/dependencies.py` has one function per service that reads the container from the
request's application, plus an `Annotated` alias a route parameter uses as its type.
Reading from `request.app.state` rather than a module global lets every `create_app`
call — one per test — own an independent store. A new service on `Container` gets its
own function and alias in the same shape:

```python
def get_todo_service(request: Request) -> TodoService:
    # ... docstring elided
    container: Container = request.app.state.container
    return container.todos


TodoServiceDep = Annotated[TodoService, Depends(get_todo_service)]
```

FastAPI reads a dependency function's annotations at run time too, and no
`runtime-evaluated-decorators` entry can cover it, because nothing decorates it. Every
type in its signature stays a real import, never under `if TYPE_CHECKING:`. Moved
there, `request: Request` silently becomes a required query parameter and every call
answers 422 (observed with fastapi 0.139.2, 2026-10-06). Ruff leaves `Request` alone in
`dependencies.py` only because `Depends` is a run-time import from the same package,
which the `TC` rules' default non-strict mode accepts. A dependency module without such
an import gets a `TC002` finding there, and that finding is the one to argue in a
reasoned `noqa`, not to apply. A type used only inside the body, like `Container`
above, may stay under `if TYPE_CHECKING:`.

## Routers

One module per resource, each with a single module-level `router = APIRouter(...)` with
`tags=`, plus a `prefix=` when every path in it shares one: `routers/todos.py` has
`prefix="/todos"`, while `routers/health.py` serves `/healthz` with no prefix.

- **A route is `async def`** and awaits the one service method it calls, so it runs on
  the event loop rather than in FastAPI's worker threads.
  `test_create_app_every_route_is_a_coroutine_function` in
  `backend/tests/api/test_app.py` fails on a plain `def` route.
- **Parameters are typed.** A path id typed `UUID` gives FastAPI's own 422 for anything
  that is not a UUID; the body is a request model; the service is the `...Dep` alias.
- **The return annotation is the response model.** Return a response model built from
  the domain result, or `None` for a 204.
- **Status codes are `HTTPStatus` members:** `status_code=HTTPStatus.CREATED` on a
  create, `HTTPStatus.NO_CONTENT` on a delete, the default 200 otherwise.
- **`responses=` lists every domain-error status the route can return,** with
  `ErrorResponse` as its model, so the OpenAPI document shows it. The dictionaries are
  module constants shared by the routes that need them (`_NOT_FOUND`,
  `_INVALID_TITLE`), with the `# Any:` comment their type needs.
- **The docstring is one plain-text line** (`writing-python` owns the rule and its
  reason).
- **`/healthz` touches no repository,** so a slow or missing database never gets a live
  process restarted. Keep a new probe the same way.

```python
@router.post("/{todo_id}/complete", responses=_NOT_FOUND)
async def complete_todo(todo_id: UUID, service: TodoServiceDep) -> TodoResponse:
    """Mark a to-do as completed."""
    return TodoResponse.from_domain(await service.complete(todo_id))
```

FastAPI reads route annotations at run time, so their types stay real imports. The root `pyproject.toml`'s `runtime-evaluated-decorators` (which
`backend/pyproject.toml` extends) lists the `APIRouter` and `FastAPI` decorators in
use; a route registered through a decorator not on that list needs it added there
(`writing-python`).

## Schemas are the wire format

`api/schemas.py` holds every request and response body as a Pydantic `BaseModel`,
apart from the domain models, so a domain field can be renamed without breaking a
client.

- A response model maps a domain value in one classmethod, `from_domain`, the only
  place the two shapes meet — `TodoResponse.from_domain` renames `is_completed` to
  `completed`.
- A request model does not repeat a rule the core owns. `TodoCreateRequest.title` is a
  plain `str`, so the core's `InvalidTodoError` produces the one message both entry
  points share; a `Field(max_length=...)` there would answer the same mistake with
  FastAPI's differently shaped 422. Types a parser enforces (`int`, `UUID`, `datetime`)
  stay. A query parameter follows the same rule: `list_todos`' `limit: int` has no
  `Query(ge=, le=)`, because the core's `InvalidPageLimitError` owns the range.
- Every domain error's body is `ErrorResponse`; its status is `designing-errors`'.

## Adding a route

Take reading one item by id, `GET /<resource>/{id}`, as the worked case:

1. The service needs a method for it. `TodoService` has none for a single item yet,
   though the `TodoRepository` port already has `get`; add the method and its tests
   first. **REQUIRED:** `designing-core-logic`.
2. Add the route to the resource's router module: a `UUID` path parameter, the service
   dependency, the response model as the return type, `responses=_NOT_FOUND`, and a
   one-line docstring.
3. The status for a missing item needs nothing new: the not-found error already maps to
   404 in `_status_for`. A new error type needs its mapping first. **REQUIRED:**
   `designing-errors`.
4. Test it (below): 200 with the body a create returned, 404 with the exact `detail`, a
   non-UUID id in the parametrized 422 test, and its 404 in the OpenAPI test.
5. Add the route to the README's HTTP table.

## Testing a route

- Route tests stay plain `def`: `TestClient` is synchronous and runs the app on its own
  event loop. Only a test that awaits something itself, such as a container's
  `aclose()`, is `async def` (`writing-tests`' "Async tests").
- Use the `client` fixture from `backend/tests/api/conftest.py`:
  `TestClient(create_app(container=make_container()))`, an empty in-memory store and
  the fixed clock, so `created_at` is known exactly. Tests go in
  `backend/tests/api/test_<router>.py`.
- Create state through the API — `backend/tests/api/test_todos.py`'s `make_todo`
  factory fixture posts and returns the body — rather than reaching into the container.
- Assert the status against an `HTTPStatus` member and the whole JSON body; an error
  asserts `{"detail": "..."}` exactly.
- `test_openapi_documents_domain_errors_with_error_response` checks that each
  documented error points at `ErrorResponse`; add a `pytest.param` per new route.
- A behavior of the factory itself (the 400 fallback, reading the environment) is
  tested in `backend/tests/api/test_app.py`, on its own `create_app` call.
- Run `uv run --locked --directory backend pytest tests/api/` from the repository root;
  a live server is the last resort, not the test (`running-the-app`).
