# Backend Guide

The FastAPI app: a uv workspace member built with
[hatchling](https://hatch.pypa.io/), in a strict `src/` layout with strict type
checking and linting. A framework-free core carries one entry point, the HTTP
API. This file adds the backend's own rules to the root `AGENTS.md`, which
still applies in full — its approval rules and gates above all.

## Validating a change

Every command here runs from the repository root. Run the narrowest check that
can fail while iterating, then `just verify` before a completion claim.

| What you changed | The narrowest check that can fail |
|---|---|
| A module under `backend/src/my_app/<layer>/` | `uv run --locked --directory backend pytest tests/<layer>/` |
| `settings.py` or `composition.py` | `uv run --locked --directory backend pytest tests/test_settings.py tests/test_composition.py` |
| A repository adapter | `uv run --locked --directory backend pytest tests/adapters/test_repository_contract.py` |
| A table in `adapters/sql/tables.py`, or a revision under `migrations/` | `uv run --locked --directory backend pytest tests/adapters/`, then `just backend lint` (`persisting-data`) |
| One backend test | `uv run --locked --directory backend pytest tests/<path>.py::test_<name>` |
| A backend Python file's types | `uv run --locked --directory backend mypy` |
| A backend Python file's lint, or `backend/pyproject.toml`'s ruff, mypy, pytest, or coverage settings | `just backend lint`, then `just backend test` (`changing-gates`) |
| The whole backend, with its 80% branch-coverage floor | `just backend test` |

`just backend dev` is the developer's server, human-run, and migrates the
developer's database (`backend/var/dev.db` by default) before it starts: the root
`AGENTS.md`'s Quick Reference says what to run instead (`running-the-app`).

## Architecture

```
backend/
├── pyproject.toml   # The app's dependencies; its ruff (extending the root's), banned-api, mypy, pytest, and coverage settings
├── justfile         # A just module of the root justfile: `just backend <recipe>`
├── alembic.ini      # Alembic's settings; no database URL (MY_APP_DATABASE_URL supplies it)
├── migrations/      # Alembic: env.py, the revision template, and versions/ (the schema's history)
├── var/             # Gitignored: the development database, dev.db
├── src/my_app/
│   ├── core/            # Framework-free: domain model, ports (Protocols), services, errors
│   ├── adapters/        # Port implementations: in-memory, and SQL (adapters/sql/: tables, engine, repository)
│   ├── api/             # FastAPI: create_app(settings) factory, routers (api/routers/), Pydantic schemas
│   ├── settings.py      # pydantic-settings `Settings`, read from MY_APP_* environment variables
│   └── composition.py   # Composition root: wires adapters into services for the API
└── tests/           # The app's suite, mirroring src/my_app/ (`placing-tests`)
```

- Dependencies point inward: `api/` calls `core/` services and gets
  them only from `composition.build_container`; `adapters/` implement
  `core/ports.py`; `core/` imports nothing outside the stdlib and itself.
  Ruff's `TID251` banned-api rule and `tests/core/test_imports.py` fail the
  build otherwise (`designing-core-logic`).
- Domain errors derive from `core.errors.AppError`; the API maps them in one
  place (`api/app.py`), per `designing-errors`.
- The schema belongs to the migrations: the app never creates or alters a table,
  and `just backend db-upgrade` (which `just backend dev` runs first) applies them
  (`persisting-data`).

## Skills for the backend

The root `AGENTS.md`'s Skills table lists every skill; these are the backend's:

- `designing-core-logic` — a use case, domain rule, port, adapter, or
  `MY_APP_*` setting, or wiring the composition root.
- `building-api-routes` — an HTTP route, request or response model, or API
  dependency, and its TestClient tests.
- `designing-errors` — a failure mode, or the HTTP status a domain error becomes.
- `persisting-data` — a table, a SQL statement, the engine, or an Alembic
  revision.
- `placing-tests` — where a backend test or fixture goes, running one test, or
  a coverage run below the floor.
