# My App

[![CI](https://github.com/your-username/fastapi-react-template/actions/workflows/ci.yml/badge.svg)](https://github.com/your-username/fastapi-react-template/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/your-username/fastapi-react-template/blob/main/LICENSE)

<!-- template-only -->
> [!NOTE]
> This is the fastapi-react-template repository itself. It is being migrated
> from a Python-only template to a FastAPI + React full-stack one; the
> [tracking issue](https://github.com/tomada1114/fastapi-react-template/issues/3)
> holds the plan and its progress. To start an application from it, follow the
> `starting-an-app` skill (`.agents/skills/starting-an-app/SKILL.md`);
> `TEMPLATE.md` explains why the template is built the way it is.
<!-- /template-only -->

A short description of what this application does.

## Quickstart

```bash
uv sync --locked
just dev   # migrate backend/var/dev.db, then serve the API on http://127.0.0.1:8000, reloading on source changes (Ctrl-C to stop)
# without Just, from backend/:
#   mkdir -p var
#   MY_APP_DATABASE_URL=sqlite+aiosqlite:///./var/dev.db uv run --locked alembic upgrade head
#   MY_APP_DATABASE_URL=sqlite+aiosqlite:///./var/dev.db uv run --locked uvicorn my_app.api.app:create_app --factory --reload --no-access-log
```

With the server running, from another terminal:

```bash
curl http://127.0.0.1:8000/healthz   # {"status":"ok"}
curl -X POST http://127.0.0.1:8000/api/todos \
  -H 'Content-Type: application/json' -d '{"title": "buy milk"}'
curl http://127.0.0.1:8000/api/todos
```

The interactive API docs are at <http://127.0.0.1:8000/docs>.

| HTTP | Result |
|---|---|
| `POST /api/todos` `{"title": "..."}` | 201 with the new to-do, `{"id": "<uuid>", "title": "...", "completed": false, "created_at": "..."}` |
| `GET /api/todos?cursor=<cursor>&limit=<n>` | one page, oldest first: `{"items": [<to-do>, ...], "next_cursor": "<cursor>" \| null}` |
| `POST /api/todos/{id}/complete` | the completed to-do |
| `DELETE /api/todos/{id}` | 204 |

A to-do's `id` is a UUID (version 7) the application generates, so ids sort in
creation order. `GET /api/todos` returns at most `limit` to-dos (default 50, at most
100) and pages by cursor: pass a page's `next_cursor` back as `cursor` to fetch
the next page; `next_cursor` is `null` on the last one. `GET /api/todos` with no
parameters is the first page, `{"items": [], "next_cursor": null}` when empty.

Every error uses RFC 9457 `application/problem+json`: `type: "about:blank"`,
`title` (the status phrase), numeric `status`, client-safe `detail`, and a stable
`code`. Clients branch on `code` and ignore unknown extensions.

An unknown to-do is 404 `todo_not_found`. An invalid title, cursor, or page limit
is 422 `invalid_todo`, `invalid_cursor`, or `invalid_page_limit`. An unmapped
domain error falls back to 400 with its own code (`AppError` uses `app_error`).
A request that does not parse is 422 `request_invalid`, detail `Request validation
failed`, and `errors: [{"loc": [...], "message": "...", "type": "..."}]`;
raw input and server context are omitted. Domain errors have no `errors`.

Unknown routes are 404 `not_found`; unsupported methods are 405
`method_not_allowed` with the `Allow` header. Other HTTP exceptions use
`http_error` and keep protocol headers; body type, length, and encoding describe
the new representation. Unregistered codes use title `Unknown Status`,
and statuses forbidding a body remain empty.
Rejected CORS preflights are 400 `http_error` Problem Details and retain the
CORS policy headers; allowed preflights remain 200 with body `OK`.
Unexpected exceptions return 500 `internal_error` with detail `An unexpected
error occurred`, while the traceback is logged on `my_app.api.errors`.

## Configuration

Settings read environment variables prefixed with `MY_APP_`, then optional UTF-8
`backend/.env`. The file's path is resolved from the module, so changing the
working directory does not change which file is read. A missing file is fine.

To start with a local copy (gitignored):

```bash
cp backend/.env.example backend/.env
```

The sample lists every setting with an empty value and its default. Environment
values take precedence over the file, including an explicit empty value: blanks
mean unset/default. Quoted file values are supported. Unknown `MY_APP_` keys in
the file fail at startup (Pydantic names the normalized field); unrelated,
unprefixed keys are ignored.

| Variable | Default | Effect |
|---|---|---|
| `MY_APP_LOG_LEVEL` | `INFO` | Case-insensitive `DEBUG`, `INFO`, `WARNING`, or `ERROR`; blank keeps the default. |
| `MY_APP_LOG_FORMAT` | `text` | `text` or one JSON object per line with timestamp, level, logger, message, request ID, access fields, and exception type/traceback when present; blank keeps text. |
| `MY_APP_CORS_ORIGINS` | empty (CORS disabled) | Comma-separated HTTP(S) origins, e.g. `http://localhost:5173,https://app.example.com`. Spaces and empty items are removed, hosts use lowercase/punycode, default ports are removed, and duplicates kept once. Paths, queries, fragments, user info, invalid ports, trailing slashes, wildcards, and origins without an HTTP(S) scheme are rejected at startup. JSON requests from listed origins are allowed without credentials. |
| `MY_APP_DATABASE_URL` | unset (`just dev`: `sqlite+aiosqlite:///./var/dev.db`) | Unset (or empty) keeps to-dos in memory, so they vanish when the process exits. `sqlite+aiosqlite:///<path>` stores them in a SQLite file at `<path>`, relative to the working directory (an absolute path adds a fourth slash: `sqlite+aiosqlite:////var/lib/todos.db`). `postgresql+asyncpg://<user>:<password>@<host>/<database>` names a PostgreSQL database; its driver, asyncpg, is not installed yet. Anything else is rejected at startup, naming the fix: a URL without the async driver (`sqlite:` or `postgresql:` alone), an in-memory SQLite database (`:memory:`), and a path ending in `/`. |

Every HTTP response carries `X-Request-ID`. Send 1–128 ASCII letters, digits,
dots, underscores or hyphens to retain your own ID; other values receive a UUIDv7.
Problem Details includes the same `request_id`, including 500 and CORS failures.
Application logs carry that ID; the access record contains method, path, status,
and duration, without query strings or request bodies. Paths escape control
characters and Unicode to preserve one physical access line. `just backend dev` disables
uvicorn's duplicate access log.

The database must be migrated before the API uses it: the app never creates or
alters a table. `just backend db-upgrade` migrates the database
the environment or `backend/.env` selects to the newest revision, and `just dev`
runs it first (see AGENTS.md's Quick Reference for `db-revision`, which writes
a new one).
The database recipes resolve the URL once using `Settings` and give that same
URL to both migration and server. If the result is unset or empty, they use
`sqlite+aiosqlite:///./var/dev.db`, including when `.env` is a copy of the sample.
A direct API factory or uvicorn run with no resolved URL uses the in-memory store.

> [!NOTE]
> `just dev` keeps to-dos in `backend/var/dev.db` (gitignored) unless
> `MY_APP_DATABASE_URL` in the environment or `backend/.env` selects another file,
> so they survive the restart on every source change. A direct server run with
> `MY_APP_DATABASE_URL=` overrides the file and forgets its to-dos when it stops.

> [!WARNING]
> A database file the app's earlier stdlib-`sqlite3` store wrote is not
> migrated: its table predates the migrations, so `just backend db-upgrade`
> fails on it. Delete the file, or point `MY_APP_DATABASE_URL` at a new one.
> A database nobody migrated answers every to-do request with a 500.

## Architecture

```
backend/src/my_app/
├── core/            # Domain model, ports (typing.Protocol), services, errors — no frameworks
├── adapters/        # In-memory and SQL repositories (SQLAlchemy asyncio Core; SQLite or PostgreSQL)
├── api/             # FastAPI app factory, routers, request/response models
├── settings.py      # MY_APP_* environment variables and backend/.env
└── composition.py   # The one place adapters are wired into services
```

The schema lives in `backend/src/my_app/adapters/sql/tables.py` and its history in
Alembic revisions under `backend/migrations/`; the `persisting-data` skill covers
changing it.

The API is thin: it gets its services from `composition.build_container`
and only translates between HTTP and the core. The core imports neither the
API nor any framework or driver; lint (`ruff` `TID251`) and a test enforce
that, so a new entry point is added beside the API without touching the core.
The `building-api-routes` skill covers the API's routes and their tests.

## Development

See [CONTRIBUTING.md](https://github.com/your-username/fastapi-react-template/blob/main/CONTRIBUTING.md)
for full setup instructions.

```bash
just install   # dependencies + git hooks, then checks the hooks are in place
just check
just dev       # migrate backend/var/dev.db, then the API with auto-reload on http://127.0.0.1:8000
```

The git hooks are not optional: they carry the secret gate that refuses a
commit staging a secret, for every author. `just install` installs the
dependencies and the hooks `.pre-commit-config.yaml`'s
`default_install_hook_types` lists (`pre-commit` and `pre-merge-commit`), then
fails if any of them is missing. `ALLOW_MISSING_GIT_HOOKS=1 just install` still tries
to install them but only warns when that fails (`CI=true` does the same).
Outside a Git repository — a "Use this template" copy before `git init` — it
skips the hooks. Without Just, run `uv sync --all-groups --locked` and then
`uv run --locked pre-commit install --install-hooks`.

## License

[MIT](https://github.com/your-username/fastapi-react-template/blob/main/LICENSE)
