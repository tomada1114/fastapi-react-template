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
just dev   # HTTP API on http://127.0.0.1:8000, reloading on source changes (Ctrl-C to stop)
# without Just: uv run --locked uvicorn my_app.api.app:create_app --factory --reload
```

With the server running, from another terminal:

```bash
curl http://127.0.0.1:8000/healthz   # {"status":"ok"}
curl -X POST http://127.0.0.1:8000/todos \
  -H 'Content-Type: application/json' -d '{"title": "buy milk"}'
curl http://127.0.0.1:8000/todos
```

The interactive API docs are at <http://127.0.0.1:8000/docs>.

| HTTP | Result |
|---|---|
| `POST /todos` `{"title": "..."}` | 201 with the new to-do, `{"id": "<uuid>", "title": "...", "completed": false, "created_at": "..."}` |
| `GET /todos?cursor=<cursor>&limit=<n>` | one page, oldest first: `{"items": [<to-do>, ...], "next_cursor": "<cursor>" \| null}` |
| `POST /todos/{id}/complete` | the completed to-do |
| `DELETE /todos/{id}` | 204 |

A to-do's `id` is a UUID (version 7) the application generates, so ids sort in
creation order. `GET /todos` returns at most `limit` to-dos (default 50, at most
100) and pages by cursor: pass a page's `next_cursor` back as `cursor` to fetch
the next page; `next_cursor` is `null` on the last one. `GET /todos` with no
parameters is the first page, `{"items": [], "next_cursor": null}` when empty.

An unknown id is a 404 from the API; a title that is empty or longer than 200
characters after trimming, a `cursor` that is not a `next_cursor` the API
returned, or a `limit` outside 1-100 is a 422. Either way the body is
`{"detail": "<reason>"}` — only a request that does not parse at all (an `{id}`
that is not a UUID, a `limit` that is not an integer) gets FastAPI's
list-shaped `detail`.

## Configuration

Settings are read from environment variables prefixed with `MY_APP_`.

| Variable | Default | Effect |
|---|---|---|
| `MY_APP_DATABASE_URL` | unset | Unset (or empty) keeps to-dos in memory, so they vanish when the process exits. `sqlite:///<path>` stores them in a SQLite file at `<path>`, created on first use; `sqlite:///:memory:` and a path ending in `/` are rejected at startup. |

> [!NOTE]
> Without `MY_APP_DATABASE_URL` the server forgets every to-do when it stops,
> and `just dev` restarts it on every source change. The in-memory default
> suits tests and a quick look; point the variable at a SQLite file for
> anything you want to keep.

> [!WARNING]
> A SQLite file written before to-do ids became UUIDs (its table has integer
> ids) is not migrated: the server refuses to start on it, naming the file.
> Delete the file, or point `MY_APP_DATABASE_URL` at a new one.

## Architecture

```
backend/src/my_app/
├── core/            # Domain model, ports (typing.Protocol), services, errors — no frameworks
├── adapters/        # In-memory and SQLite repositories
├── api/             # FastAPI app factory, routers, request/response models
├── settings.py      # MY_APP_* environment variables
└── composition.py   # The one place adapters are wired into services
```

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
just dev       # API with auto-reload on http://127.0.0.1:8000
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
