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
export MY_APP_DATABASE_URL=sqlite:///todos.db  # keep to-dos between commands
uv run --locked my-app todo add "buy milk"     # Added 1 [ ] buy milk
uv run --locked my-app todo list               # 1 [ ] buy milk
uv run --locked my-app serve                   # HTTP API on http://127.0.0.1:8000 (Ctrl-C to stop)
```

With the server running, `curl http://127.0.0.1:8000/healthz` returns
`{"status":"ok"}`, and the interactive API docs are at
<http://127.0.0.1:8000/docs>.

| CLI | HTTP | Result |
|---|---|---|
| `my-app todo add TITLE` | `POST /todos` `{"title": "..."}` | 201 with the new to-do |
| `my-app todo list` | `GET /todos` | every to-do, oldest first (`[]` when empty) |
| `my-app todo complete ID` | `POST /todos/{id}/complete` | the completed to-do |
| `my-app todo delete ID` | `DELETE /todos/{id}` | 204 |

An unknown id is a 404 from the API; a title that is empty or longer than 200
characters after trimming is a 422. A route you build on the optional LLM
layer answers 503 while no key is set, 429 when the provider keeps
rate-limiting, 504 when the call times out, and 502 for any other provider
failure. Either way the body is `{"detail": "<reason>"}` — only a request that
does not parse at all gets FastAPI's list-shaped `detail`.

The CLI exits with one of these codes. A domain or configuration error prints
one line on stderr; a usage error prints Typer's own usage message.

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Domain error: an unknown id, an invalid title |
| 2 | Usage error: a missing or malformed argument (Typer's own) |
| 3 | Invalid configuration: a `MY_APP_*` variable that does not validate |

## Configuration

Settings are read from environment variables prefixed with `MY_APP_`; the
one exception is `OPENROUTER_API_KEY`, which keeps the name OpenRouter uses.

| Variable | Default | Effect |
|---|---|---|
| `MY_APP_DATABASE_URL` | unset | Unset (or empty) keeps to-dos in memory, so they vanish when the process exits. `sqlite:///<path>` stores them in a SQLite file at `<path>`, created on first use; `sqlite:///:memory:` and a path ending in `/` are rejected at startup. |
| `OPENROUTER_API_KEY` | unset | Unset (or blank) keeps the optional LLM layer closed: an LLM-backed route answers 503, and neither `httpx` nor the OpenRouter adapter is imported. Set, it opens the OpenRouter adapter, which needs the `ai` extra. |
| `MY_APP_LLM_MODEL` | `deepseek/deepseek-v4.1-flash` | The OpenRouter model a call that names none is sent to; blank means the default. |

> [!NOTE]
> Each `my-app todo` invocation is its own process, so without
> `MY_APP_DATABASE_URL` the CLI forgets every to-do as soon as the command
> exits. The in-memory default suits the API server and tests; point the
> variable at a SQLite file for anything you want to keep.

The LLM layer is optional: `uv sync --extra ai` (or `pip install 'my-app[ai]'`)
installs `httpx` for the OpenRouter adapter. The `integrating-llm` skill
(`.agents/skills/integrating-llm/SKILL.md`) covers calling it, testing with
the fake, and removing it.

## Architecture

```
src/my_app/
├── core/            # Domain model, ports (typing.Protocol), services, errors — no frameworks
├── adapters/        # In-memory and SQLite repositories; fake, closed, and OpenRouter LLM adapters
├── api/             # FastAPI app factory, routers, request/response models
├── cli/             # Typer commands; serve.py is the only one that touches the API
├── settings.py      # MY_APP_* environment variables, plus OPENROUTER_API_KEY
└── composition.py   # The one place adapters are wired into services
```

The API and the CLI are thin: both get their services from
`composition.build_container` and only translate between their own protocol
and the core. The core imports neither of them, nor any framework or driver;
lint (`ruff` `TID251`) and a test enforce that. Either entry point can
therefore be removed by deleting files, without touching the core. The
`building-api-routes` and `designing-clis` skills hold the removal checklists.

## Development

See [CONTRIBUTING.md](https://github.com/your-username/fastapi-react-template/blob/main/CONTRIBUTING.md)
for full setup instructions.

```bash
just install   # dependencies + git hooks, then checks the hooks are in place
just check
just dev        # API with auto-reload on http://127.0.0.1:8000
just run --help # the CLI, through uv
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
