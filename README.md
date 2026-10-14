# My App

[![CI](https://github.com/your-username/fastapi-react-template/actions/workflows/ci.yml/badge.svg)](https://github.com/your-username/fastapi-react-template/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/your-username/fastapi-react-template/blob/main/LICENSE)

<!-- template-only -->
> [!NOTE]
> This is the fastapi-react-template repository itself: a FastAPI + React
> full-stack template. To start an application from it, follow the
> `starting-an-app` skill (`.agents/skills/starting-an-app/SKILL.md`);
> `TEMPLATE.md` explains its design. The Python-only sibling,
> [`tomada1114/uv-template`](https://github.com/tomada1114/uv-template), is for
> command-line tools and API-only services.
<!-- /template-only -->

A short description of what this application does.

## Quickstart

Prerequisites (CONTRIBUTING.md's "Prerequisites" has the links and the details):

- [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.11.8 or later; it
  installs Python 3.14 when none is found
- [Just](https://just.systems/man/en/installation.html) 1.42.3 or later
- [Node.js 24](https://nodejs.org/en/download) (`.node-version`)
- [pnpm](https://pnpm.io/installation), through `corepack enable` (Corepack ships
  with Node.js 24); `package.json` pins the version
- no Docker

<!-- template-only -->
In the template repository itself, first copy it ("Use this template" on GitHub)
and bootstrap the copy with the `starting-an-app` skill
(`.agents/skills/starting-an-app/SKILL.md`); the steps below are the copy's.
<!-- /template-only -->

Then:

1. Install the dependencies and the git hooks, then start the app:

   ```bash
   just install   # the Python and JavaScript dependencies, and the git hooks
   just dev       # migrate backend/var/dev.db, then serve the screen and the API, reloading on source changes (Ctrl-C stops both)
   ```

2. Open <http://localhost:5173>: the to-do screen. The API answers on
   <http://127.0.0.1:8000>, with `/healthz` and the interactive docs at `/docs`.

`just dev` is the developer's own server and runs until stopped; an agent runs
its own pair on free ports instead (the `running-the-app` skill). Without Just,
CONTRIBUTING.md's "Without Just" note says where each recipe's commands are.

The request flow under `just dev`:

```text
browser
  -> Vite dev server, http://localhost:5173 (VITE_PORT); proxies /api and /healthz
  -> FastAPI router, http://127.0.0.1:8000 (MY_APP_API_PORT)
  -> service in backend/src/my_app/core/
  -> repository port
  -> SQL adapter (SQLAlchemy asyncio Core)
  -> SQLite file, backend/var/dev.db
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
| `GET /healthz` | 200 `{"status": "ok"}` |
| `POST /api/todos` `{"title": "..."}` | 201 with the new to-do, `{"id": "<uuid>", "title": "...", "completed": false, "created_at": "..."}` |
| `GET /api/todos?cursor=<cursor>&limit=<n>` | 200 with one page, oldest first: `{"items": [<to-do>, ...], "next_cursor": "<cursor>" \| null}` |
| `POST /api/todos/{id}/complete` | 200 with the completed to-do; 404 `todo_not_found` when unknown |
| `DELETE /api/todos/{id}` | 204; 404 `todo_not_found` when unknown |

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
| `MY_APP_DATABASE_URL` | unset (`just dev`: `sqlite+aiosqlite:///./var/dev.db`) | Unset (or empty) keeps to-dos in memory, so they vanish when the process exits. `sqlite+aiosqlite:///<path>` stores them in a SQLite file at `<path>`, relative to the working directory (an absolute path adds a fourth slash: `sqlite+aiosqlite:////var/lib/todos.db`). `postgresql+asyncpg://<user>:<password>@<host>/<database>` names a PostgreSQL database; include the optional `postgres` extra in workspace commands (`uv run --locked --directory backend --extra postgres ...`) or install the built app with that extra. Anything else is rejected at startup, naming the fix: a URL without the async driver (`sqlite:` or `postgresql:` alone), an in-memory SQLite target (including `:memory:` with options and native URI memory mode), an empty target, and a directory target ending in `/`, even when query options follow. File options are preserved; migrations and the app use separate engine/process lifetimes, so in-memory SQL cannot retain the separately migrated schema. |

The development servers read a second set of variables from the process
environment. They are not `Settings` fields, so they never go in `backend/.env`,
which rejects unknown `MY_APP_` keys at startup:

| Variable | Default | Read by | Effect |
|---|---|---|---|
| `MY_APP_API_PORT` | `8000` | `just dev`, `just backend dev`, and the Vite proxy | The API's port, and the port Vite proxies `/api` and `/healthz` to. |
| `VITE_PORT` | `5173` | `just dev`, `just frontend dev` | The screen's port; Vite fails rather than moving to another port when it is taken. |
| `E2E_API_PORT`, `E2E_WEB_PORT` | a free port each | `just e2e` | The browser test's own API and screen ports; never 8000 or 5173. |

The database recipes automatically select the `postgres` extra for PostgreSQL
URLs and keep the default environment for SQLite.

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

```text
backend/    # The FastAPI app (uv workspace member): core, adapters, API, settings, Alembic migrations
frontend/   # The React app (Vite, TypeScript; pnpm workspace member) and its typed API client
e2e/        # The Playwright test from the screen to the database (just e2e)
```

`backend/AGENTS.md` holds the backend's architecture: the core imports neither
the API nor any framework or driver, the API only translates between HTTP and
the core, and `composition.py` is the one place adapters are wired in.
`frontend/AGENTS.md` holds the frontend's toolchain. The schema lives in
`backend/src/my_app/adapters/sql/tables.py` and its history in Alembic revisions
under `backend/migrations/` (the `persisting-data` skill).

## Development

See [CONTRIBUTING.md](https://github.com/your-username/fastapi-react-template/blob/main/CONTRIBUTING.md)
for the prerequisites, the workflow, and the pull request process; AGENTS.md's
Quick Reference indexes every recipe.

```bash
just install   # dependencies + git hooks, then checks the hooks are in place
just dev       # migrate backend/var/dev.db, then the screen on http://localhost:5173 and the API on http://127.0.0.1:8000
just verify    # the non-mutating gate a pull request must pass
```

Each area has its own recipes: `just backend <recipe>` (for example
`just backend test`, `just backend db-upgrade`) and `just frontend <recipe>`
(for example `just frontend test`); `just contract` regenerates the typed API
client from the backend's OpenAPI contract, and `just e2e` runs the browser test.

`just dev` runs `just backend dev` (uvicorn with auto-reload on
http://127.0.0.1:8000) and `just frontend dev` (Vite on http://localhost:5173)
together in one terminal. Open http://localhost:5173: Vite proxies `/api` and
`/healthz` to the API, so the browser sees one origin and needs no CORS.
Ctrl-C stops both; when either one exits, `just dev` stops the other and exits
with that one's status. `MY_APP_API_PORT` and `VITE_PORT` (the development-server
table under "Configuration") move the ports when the defaults are taken:

```bash
MY_APP_API_PORT=8001 VITE_PORT=5174 just dev
```

The git hooks are not optional: they carry the secret gate that refuses a
commit staging a secret, for every author. `just install` installs the
dependencies and the hooks `.pre-commit-config.yaml`'s
`default_install_hook_types` lists (`pre-commit` and `pre-merge-commit`), then
fails if any of them is missing. `ALLOW_MISSING_GIT_HOOKS=1 just install` still tries
to install them but only warns when that fails (`CI=true` does the same).
Outside a Git repository — a "Use this template" copy before `git init` — it
skips the hooks. A failed `pnpm install` still lets the hooks install, then
fails the run. Without Just, run `uv sync --all-groups --locked`,
`pnpm install --frozen-lockfile`, and then
`uv run --locked pre-commit install --install-hooks`.

## License

[MIT](https://github.com/your-username/fastapi-react-template/blob/main/LICENSE)
