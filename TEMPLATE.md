# About This Template

This file documents the template itself: why it is built the way it is, and
how to turn a copy of it into a real application. `scripts/bootstrap.py` deletes
it from the spawned repo, so nothing here ships with your application.

The template is being reshaped into a FastAPI + React full-stack template; the
[tracking issue](https://github.com/tomada1114/fastapi-react-template/issues/3)
holds the plan and its progress. Until it closes, parts of this file still
describe the Python-only layout it was generated from. That layout stays
available as the Python-only sibling,
[`tomada1114/uv-template`](https://github.com/tomada1114/uv-template), for CLI
tools and API-only services.

## Using This Template

The steps live in one place: the `starting-an-app` skill
(`.agents/skills/starting-an-app/SKILL.md`, mirrored to `.claude/skills/`). It gives
the order of work from "Use this template" to the first feature — the bootstrap, the
Product section, labels, the GitHub settings, the ruleset, removing the sample — and
marks which steps are a human's. Its `references/bootstrap.md` documents
`scripts/bootstrap.py`: the flags, what it refuses, and what it rewrites and removes.

### Working in the new repository

- **Never commit directly on `main`.** The pre-commit `no-commit-to-branch`
  hook blocks it, and `--no-verify` would also switch off the secret gate
  (`scripts/check_staged.py`), so the way through is a feature branch and a
  PR — not a bypass flag.
- The toolchain baseline checklist lives in `changing-gates` so every app keeps it.
- Python dependencies arrive as monthly Dependabot `uv` PRs under a 14-day
  cooldown equal to `[tool.uv] exclude-newer = "14 days"`; a human merges
  them with the `merging-dependency-prs` skill, and `managing-dependencies`
  holds the window and its one-package exception.
- `just verify` (its steps are listed in AGENTS.md's Quick Reference) is the
  non-mutating gate for a PR or a completion claim; `just check` mutates the
  tree first (`fmt`) and is for local iteration only.

## Design Philosophy

Every choice in this template has a reason. If you disagree with a decision,
you know exactly what to change and why it was there in the first place.

### Why `src/` layout?

Keeping the app's package under `backend/src/my_app/` prevents accidental
imports of the local package during development and testing. It ensures that tests always run against the
*installed* package rather than the working tree, so a missing module or a
broken package configuration fails the test run instead of the deployed app.

### Why strict mypy + comprehensive Ruff rules?

Type errors and lint issues are cheapest to fix at write time. Strict settings
from day one mean every line of code is held to the same standard — there is
never a "legacy" codebase to clean up. LLMs generating code also benefit from
strict rules: they produce higher-quality output when constraints are clear.

### Why a framework-free core with FastAPI and Typer over it?

Most Python applications end up with an HTTP API, a command line, or both, and
the expensive mistake is letting either framework leak into the business
rules. The template therefore ships the shape rather than an empty package: a
`core` that imports only the stdlib (ports are `typing.Protocol`s, values are
frozen dataclasses), adapters that implement its ports, and two thin entry
points that get their services from one composition root. Ruff's banned-api
rule and a test keep the core clean, and the CLI reaches the API only through
`cli/serve.py`, so dropping the entry point you do not need is a list of
deletions (README's Architecture section), not a refactor.

The runtime dependencies are what the API and its storage need — FastAPI,
uvicorn, and pydantic-settings for the API; SQLAlchemy, Alembic, and aiosqlite
for the SQL store (below). Anything else is yours to add deliberately.

### Why SQLAlchemy Core and Alembic, and never migrating at start-up?

An app cut from the template keeps state from its first feature, and the first
schema change it makes needs a path for the data already stored. So the SQL
adapter is SQLAlchemy's asyncio API in Core style — explicit `Table` metadata
and statements inside `adapters/`, no ORM classes, no SQLModel — with Alembic
revisions as the schema's only author (tomada1114/fastapi-react-template#3,
D4). Core keeps rows inside the adapter, so the core's ports stay ones a
key-value store could implement too; SQLModel would make one class both the API
schema and the table, coupling the layers the core/adapter split separates.
SQLite through `aiosqlite` is the local default, so a first run needs no
Docker; PostgreSQL takes the same statements, with asyncpg in an optional
`postgres` extra. The same repository contract and migration round trip run
against PostgreSQL in CI so dialect differences surface before deployment.
asyncpg supplies an async driver under Apache-2.0 without extra runtime packages;
the standard library has no PostgreSQL driver, and psycopg's LGPL license does
not fit the dependency gate (https://pypi.org/project/asyncpg/0.31.0/ and
https://pypi.org/project/psycopg/, checked 2026-10-09). Migrations run only when asked
(`just backend db-upgrade`, which `just dev` runs first): an app that migrates
or calls `create_all` at start-up hides a missing revision and races when two
processes start at once. The `persisting-data` skill holds the workflow.

### Why no LLM layer?

The template carries no LLM layer since 2026-10-09, an owner decision
(tomada1114/fastapi-react-template#3, D6): the apps planned from it call models
through a provider this template leaves out, so a provider-specific adapter would
be code every app deletes. An app that calls a model adds its own port and
adapter under `designing-core-logic`'s port rules and records the choice in an
ADR.

### Why Just over Make?

Just has cleaner syntax (no mandatory tabs), better cross-platform support, and
more readable recipe definitions. It is a task runner, not a build system —
which is exactly what a Python project needs.

### Why AGENTS.md and the agent configuration?

AI-assisted development is the norm, not the exception. `AGENTS.md` gives any
coding agent (Claude Code, Codex, Cursor, Gemini CLI, ...) the context it
needs to match your project's standards; `CLAUDE.md` imports it and adds
Claude Code specifics. Skills are authored once in `.agents/skills/` and
mirrored into `.claude/skills/` (`just agents-sync`); `.claude/agents/` and
`.codex/agents/` define the same three sub-agent tiers for each host.
Permission allowlists, model choices, plugin marketplaces, and editor hooks
are personal and are never committed.

### Why a pre-commit layer instead of agent hooks?

A guard rail wired into one agent's hook configuration protects nothing when
a human, or a different tool, makes the commit. So the template commits no
agent hooks: its guard rails are git hooks run by pre-commit, which fire on
`git commit` for every author. `scripts/check_staged.py` refuses secret-shaped
paths and credential-shaped content straight from the index, on every
`git commit` and every merge commit, and `just install` fails when the git
hooks are missing. A file the gate refuses but that holds no secret gets
through by a reviewed entry in `.check-staged-allow`, never by a bypass flag.
Commits git makes without running hooks — `git rebase` replays,
`git cherry-pick`, `git revert` — are left to the weekly full-history scan of
the Security Audit workflow (gitleaks). What the old agent hooks did and where
each behavior went is the replacement table in the `changing-gates` skill's
`references/pre-commit-layer.md`.

### Why 80% coverage minimum?

80% is high enough to catch most regressions but low enough to avoid
test-for-the-sake-of-testing. Branch coverage is enabled, so conditional logic
is meaningfully tested.
