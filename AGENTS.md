# Project Guide

## Overview

A FastAPI application in a [uv](https://docs.astral.sh/uv/) workspace, laid out
by area. The sample domain is a to-do list — replace it with your own.

| Area | Holds |
|---|---|
| `backend/` | The FastAPI app, a uv workspace member: its `pyproject.toml`, `src/my_app/`, `tests/`, a `justfile` module (`just backend <recipe>`), and its own `AGENTS.md` |
| `frontend/` | The React app (Vite, TypeScript), a pnpm workspace member: its `package.json`, `src/`, `tests/`, Biome, `tsc`, and Vitest config, a `justfile` module (`just frontend <recipe>`), and its own `AGENTS.md` |
| `e2e/` | The browser test (Playwright, Chromium only), a pnpm workspace member: its `package.json`, `playwright.config.ts`, `tests/`, Biome and `tsc` config, and `verify_persistence.py`, the backend process that checks the database; run by the root `just e2e` and `just e2e-lint` |
| The root | The workspaces (`pyproject.toml`, `uv.lock`; `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `.node-version`) and the repository's tooling: the `justfile` with the aggregate gates, `scripts/`, the harness and script tests under `tests/`, `.agents/skills/`, `.github/` |

Where to work:

- Working under `backend/`: read `backend/AGENTS.md` first. It holds the
  backend's architecture and its narrowest checks; this file still applies.
- Working under `frontend/`: read `frontend/AGENTS.md` first. It holds the
  frontend's toolchain, its coverage floor, and its narrowest checks; this file
  still applies.
- Anywhere else: this file is the whole guide.

Every task here:

- Write everything — code, docs, commits, pull requests — in English.
- Do what has been asked; nothing more, nothing less. Note an improvement
  outside the current scope instead of making it (`triaging-issues`).
- Create no file unless it is absolutely necessary, and no documentation file
  unless asked; prefer editing an existing one.

## Product

<!-- template-only -->
In the template every entry below stays a `TODO:` on purpose: each repository cut
from it writes its own, and `tests/test_product_section.py` fails here if one is
filled in.
<!-- /template-only -->

This section is about the application rather than the harness: without it, an
agent implementing an issue has no in-repo answer to "is this in scope?". The owner
decides every entry; an agent drafts one only from what the owner has said. Once the
bootstrap has run (`.template-origin` exists), `tests/test_product_section.py` — and
so `just verify` — fails while any entry below is still a placeholder.

- **What it is, and who it is for** — TODO: one paragraph: the problem it solves,
  and whose problem that is.
- **The core interaction** — TODO: the one thing a user does most. If the app does
  not do this well, nothing else about it matters.
- **Non-goals** — TODO: what this app deliberately does not do, even where it would
  be easy. Moving anything from here to a goal is a human's decision, not an
  implementer's.
- **Why it is shaped this way** — TODO: the reasoning behind the three entries above,
  in the present tense — why this audience, why this interaction comes first, and why
  each non-goal stays out — so a reader finds why and not only what. It is rewritten
  when the reasoning changes, not appended to ("Before changing the architecture").

## Quick Reference

Grouped by who runs them; the `justfile` is the source of truth, this its index.

### Checks and tasks an agent runs

```bash
just install         # Install dependencies (uv, then pnpm) and git hooks when .git/ is present
just setup           # Alias for just install (first-time setup)
just fmt             # Format code: just frontend fmt, e2e/ (biome check --write), then the Python tree (ruff check --fix + ruff format)
just lint            # Lint + type check: just backend lint, just frontend lint, just e2e-lint, then the root (ruff, mypy)
just test            # Run tests: just backend test, just frontend test, then the root suite
just backend lint    # Lint and type-check the backend (ruff, ruff format --check, mypy strict)
just backend fmt     # Format the backend
just backend test    # Run the backend tests in parallel with branch coverage (80% floor)
just backend test-postgres # Run the shared contract and migrations on a disposable PostgreSQL database
just backend db-upgrade # Migrate MY_APP_DATABASE_URL's database (default: backend/var/dev.db) to the newest revision
just backend db-revision MESSAGE # db-upgrade, then autogenerate a revision from a change to adapters/sql/tables.py
just frontend install # Install the locked JavaScript dependencies (pnpm install --frozen-lockfile)
just frontend lint   # Lint the frontend (biome ci) and type-check it (tsc --noEmit, strict flags)
just frontend fmt    # Format the frontend (biome check --write)
just frontend test   # Run the frontend tests (Vitest) with an 80% floor on lines, functions, statements, branches
just frontend build  # Build the frontend for production into frontend/dist (vite build)
just e2e-lint        # Lint and type-check e2e/ (biome ci, tsc --noEmit) without starting a browser
just e2e             # Browser test (Chromium): the built screen and the API on own free ports and a throwaway SQLite file
just check           # Mutating dev check: fmt → lint → test
just lock            # Update uv.lock after dependency changes
just lock-check      # Fail when uv.lock is out of date, without changing it
just verify          # Non-mutating gate: lock-check → agents-check → check-harness → contract-check → lint → test-skills → test → frontend::build
just contract        # Export frontend/openapi.json and regenerate the typed API client
just contract-check  # Check JSON and client drift and the scope of TypeScript exceptions
just check-harness   # Harness drift (skills, Skills table, recipes, this index, ruleset, labels, workflows) + the Product section check
just test-skills     # Run the unittest suites bundled under .agents/skills/*/scripts/tests
just worktree-prepare # Recreate the locked environments (uv, then pnpm once pnpm-lock.yaml exists) in an existing linked worktree
just worktree-setup ISSUE BRANCH BASE ROOT VERIFY # Provision one issue worktree with its baseline
just worktree-clean ROOT BRANCH # Preview cleanup of one named worktree whose local tip is a merged PR's head; a failed gh fails the run
just worktree-clean-apply ROOT BRANCH # Apply the preview; keeps dirty or unmerged worktrees
just agents-sync     # Regenerate the .claude/skills mirror from .agents/skills
just agents-check    # Fail when the skills mirror has drifted
just clean           # Remove build artifacts and caches
```

### Long-running — human-run

```bash
just dev             # Run just backend dev and just frontend dev together: the screen on http://localhost:5173, the API behind its /api on http://127.0.0.1:8000; runs until stopped
just backend dev     # Run db-upgrade, then serve the API on http://127.0.0.1:8000 with auto-reload; runs until stopped
just frontend dev    # Serve the frontend with Vite's dev server on http://localhost:5173, proxying /api and /healthz to the API; runs until stopped
```

`MY_APP_API_PORT` (default 8000) moves the API and the port Vite proxies to;
`VITE_PORT` (default 5173) moves the screen. Both are process variables, never
`Settings` fields or `backend/.env` keys.

The developer's `just dev`, `just backend dev`, and `just frontend dev` are
theirs: never start, stop, or restart one, and never bind 8000 or 5173. To see
what only a running server shows, prefer a `TestClient` test, else your own
`uv run --locked uvicorn my_app.api.app:create_app --factory --port <free port>`,
or, for the screen, your own pair on two free ports with a scratch database,
`MY_APP_API_PORT=<port> VITE_PORT=<port> just dev`; stop either before your
turn ends (`running-the-app`).

### Writes to GitHub

```bash
just labels          # Create/update GitHub labels from .github/labels.yml (ask first)
just ruleset         # Apply .github/rulesets/main.json to GitHub (admin-only human step; never an agent)
```

Without Just, run the `uv run` and `pnpm` commands the `justfile` gives each
recipe, and a `backend::` or `frontend::` dependency's lines from that area's
`justfile` in its directory.
`just check` runs `fmt` first, so it never proves the *committed* tree green;
`just verify` mutates nothing and is the gate for a PR or a completion claim.

## Validating a change

Run the narrowest check that can fail while iterating, then `just verify` before
a completion claim on any code change — on every edit it is slow enough to stop
being run at all.

| What you changed | The narrowest check that can fail |
|---|---|
| Anything under `backend/` | `backend/AGENTS.md`'s "Validating a change" table |
| Anything under `frontend/` | `just frontend lint && just frontend test` (`frontend/AGENTS.md`'s table has narrower ones) |
| Anything under `e2e/`, or the screen's flow end to end | `just e2e-lint`, then `just e2e` (Chromium once: `pnpm --dir e2e exec playwright install chromium`) |
| One root test (`tests/`) | `uv run --locked pytest tests/test_<module>.py::test_<name>` |
| A root Python file's lint or types (`scripts/`, `tests/`, skill scripts) | `uv run --locked ruff check <file>`, then `uv run --locked mypy` |
| A script under `scripts/` | `uv run --locked pytest tests/test_<script>.py` |
| A skill under `.agents/skills/` | `just agents-sync && just agents-check && just check-harness && just test-skills` |
| Dependencies in `pyproject.toml` or `backend/pyproject.toml` | `uv lock`, `uv sync --all-groups --locked`, then `just verify` |
| A workflow under `.github/workflows/`, or an action under `.github/actions/` | `uv run --locked pre-commit run zizmor --all-files`, then `just check-harness` |
| Markdown or other prose | `uv run --locked pre-commit run typos --files <file>`, then `just check-harness` (it checks each `just <recipe>` named) |

The state of the work comes from Git, fresh test output, and CI — never from
prose or a test count in a prompt.

## Before changing the architecture

The design is recorded as it stands now, never as a log of decisions: this file's
Product section, `backend/AGENTS.md`'s "Architecture" section, and the skill that owns
the subject say together how the app is built and why, and git history holds what it
used to be. The changes below, which the skills call design changes, are hard to
reverse, so the pull request that makes one also rewrites that description: the current
design and the reasoning behind it (what it protects and, where it matters, the
alternative it rules out and why), in the present tense, in place of the sentences it
replaces, never as a dated entry beside them:

- a runtime dependency — a package under `[project] dependencies` (a dev-only tool in
  `[dependency-groups]` is not one unless it changes a gate);
- a package boundary — a new top-level package or layer under `backend/src/`, or a
  change to what may import what;
- the public contract — what `__init__.py`'s `__all__` promises, or the shape of a CLI
  command, an HTTP route, or a file format other programs read;
- persistence — where and in what format state lives (files, SQLite, a database
  server, a cache), and how a schema change reaches existing data;
- an external service — a network API, a cloud provider, a message queue — and how its
  credentials reach the process;
- `requires-python` in `backend/pyproject.toml`;
- distribution — a wheel on a package index, a container image, a tool installed with
  `uv tool`, a hosted service.

Writing the reasoning down grants nothing: a new dependency or a remote write still
needs the sign-off "Security and human approval" asks for, and the owner reviews the
rewritten description with the change.
<!-- template-only -->
In the template itself, the reasoning behind the layers every app starts with lives in
`TEMPLATE.md`'s "Design Philosophy"; a design change to the template rewrites that
entry, rather than leaving the old reason beside the new one.
<!-- /template-only -->

## Skills

Skills are authored under `.agents/skills/` (Codex CLI) and mirrored into
`.claude/skills/` (Claude Code): edit only `.agents/skills/`, run
`just agents-sync`, and commit both trees (`authoring-skills`).

| Skill | Load it when |
|---|---|
| `authoring-skills` | adding, editing, or reviewing a skill under `.agents/skills/`, or a skill never fires |
| `building-api-routes` | adding or changing an HTTP route, request or response model, or API dependency, and the TestClient tests for it |
| `building-screens` | adding or changing a screen, route, or feature under `frontend/src/`: server data through the generated client, API errors, styling, accessibility, and its component tests |
| `changing-gates` | editing a hook, a CI workflow, the ruleset, or a ruff, mypy, pytest, coverage, Vitest, Biome, `tsconfig.json`, or `pnpm-workspace.yaml` setting, or asking whether a change weakens a gate |
| `cloud-claude-shipping-issues` | Claude Code cloud sessions only (`CLAUDE_CODE_REMOTE=true`): shipping the next issue or the backlog over REST `gh api` calls, serially — rank, implement, PR, the PR's review, CI, merge, follow-ups |
| `codex-shipping-issues` | shipping one GitHub issue from a Codex-managed checkout through a regular PR, up to three Codex review rounds with their findings addressed, current-head CI, and an explicitly authorized merge |
| `create-pr` | opening or updating a pull request by hand |
| `designing-core-logic` | adding a use case, domain rule, port, adapter, or `MY_APP_*` setting, or wiring the composition root |
| `designing-errors` | adding a failure mode, or choosing the HTTP status a domain error becomes |
| `managing-dependencies` | adding, bumping, or removing a Python or JavaScript package, or changing the `exclude-newer` or `minimumReleaseAge` window, a Dependabot cooldown, a one-package exception, or another `pnpm-workspace.yaml` exception |
| `merging-dependency-prs` | landing open Dependabot pull requests (GitHub Actions, pre-commit, `uv`, and `npm_and_yarn` bumps) |
| `persisting-data` | changing a table in `backend/src/my_app/adapters/sql/`, writing or reviewing an Alembic revision under `backend/migrations/`, running `just backend db-upgrade` or `db-revision`, a SQL repository's statements, or the `AsyncEngine`'s lifecycle |
| `placing-tests` | adding a test file or a fixture (pytest, Vitest, or the browser test), running one test, or a coverage run below a floor |
| `running-the-app` | running a server of your own to observe a change, and stopping that server afterwards |
| `shipping-issues` | Claude Code only: shipping the next issue or the whole backlog: rank, implement, PR, the PR's own review and its findings, CI, merge |
| `smart-commit` | grouping working-tree changes into commits, or a pre-commit hook refuses a commit |
| `starting-an-app` | setting up an app cut from this template: the Product section, the bootstrap pull request, labels, ruleset, security settings, dropping the frontend, the API, or the sample domain, the first design changes; the template rename step |
| `steering-the-roadmap` | asked what to work on next, or the Now / Next / Later roadmap moves |
| `tdd` | changing behavior under `backend/src/`, `scripts/`, or `frontend/src/`, or fixing a bug: the failing test comes first |
| `triaging-issues` | filing, labelling, or prioritizing an issue, or recording a problem found outside the task |
| `updating-docs` | deciding whether a change owes a README, AGENTS.md (the root's or an area's), regenerated contract, or other document update |
| `writing-python` | writing or reviewing any Python module, class, or function: typing, imports, docstrings, idioms |
| `writing-repo-scripts` | adding or editing a script under `scripts/`, its `just` recipe, or its tests |
| `writing-tests` | writing or reviewing a pytest or Vitest test: its name, assertions, fixtures, fakes or MSW handlers, and edge cases |

## Sub-agents

A skill runs every step inline by default. On a host that can hand a step to a
named sub-agent, a step marked for a tier may go to one of four:

| Tier | Takes |
|---|---|
| `executor` | a settled spec with a clear pass/fail: implementing it, adding tests, getting a check green, bulk edits |
| `architect` | design judgment, review and bug finding, multi-file work, synthesis, a spec that still has holes |
| `scout` | read-only, judgment-free research: collecting, enumerating, or answering a fixed question while changing no files |
| `worker` | single-shot, tool-free writing or checking from a complete brief, such as drafting issue or PR text from findings already verified; never a code change |

Both hosts define the same four: `.claude/agents/<tier>.md` and
`.codex/agents/<tier>.toml`. They are generated by the `syncing-agent-tiers` skill
from one canonical source, which sets each tier's model and effort; never edit them by
hand. `tests/test_agent_tiers.py` holds their structure and instructions equal.

- Neither file declares a permission — no `sandbox_mode`, no tool list.
- Codex CLI loads `.codex/` only for a trusted project (in an untrusted
  checkout a step marked for a tier runs inline), and `.codex/agents/worker.toml`
  replaces Codex's built-in `worker` inside this repository on purpose.

## Security and human approval

- **Commit, push, and pull request need a human's sign-off** — given per
  request, or by one of the [standing exceptions](#standing-exceptions) below.
  The ruleset blocks a force-push to or deletion of `main` only once a human has
  applied it with `just ruleset`; nothing else blocks a force-push or
  `gh pr merge --admin`, so this instruction is the rule itself.
- In Codex, always load the repository-local `codex-shipping-issues` for issue
  shipping; it takes precedence over a global skill of the same name. The existing
  `shipping-issues` workflow is Claude Code only and is never executed by Codex.
- In a Claude Code cloud session (`CLAUDE_CODE_REMOTE=true`), ship issues with
  `cloud-claude-shipping-issues`, never `shipping-issues`, whose scripts' GraphQL
  calls the session's GitHub proxy refuses.
- In Codex, use GitHub MCP for all remote GitHub operations; never invoke `gh`
  directly or through live-GitHub helpers, and never use a direct HTTP fallback.
  Report missing MCP capabilities. Local checkout, commit and push use Git;
  repository checks using mocked CLI fixtures remain permitted.
- Never bypass a git hook — no `--no-verify`, no `SKIP=<hook id>`, no edit to
  `.git/hooks/`. `--no-verify` switches off the secret gate of the
  [enforcement layers](#enforcement-layers) along with everything else.
- Never weaken a gate to make a run pass: no lowered coverage threshold, no
  removed ruff rule, no `noqa`, `type: ignore`, or per-file ignore without a
  written reason, no skipped or deleted test, no removed `--locked`, no
  `.check-staged-allow` entry added, widened, re-pointed, or re-pinned without
  a human's decision (removing one whose file the same change deleted or
  renamed narrows the gate and is allowed). If a gate is wrong, say so and let
  a human decide. `changing-gates` lists every form
  this takes.
- When a command is denied — by a permission setting, a hook, or a human —
  re-spelling it (`bash -c '…'`, an alias, a wrapper script) is forbidden. Stop
  and ask.

### Standing exceptions

Invoking a skill that lists the commits or remote writes it makes is the
sign-off for exactly those, for that invocation only:

- `shipping-issues`: the writes its `SKILL.md` lists — priority and status
  labels, syncing label definitions from `.github/labels.yml` with
  `just labels`, pushing its own branches, creating the pull request, merging
  it once CI passes, filing and labelling follow-up issues and the comments it
  posts, and deleting the branches it created.
- `cloud-claude-shipping-issues`: the writes its `SKILL.md` lists — pushing its own
  branch; creating the pull request; on that open PR alone, appending `Closes #<n>` to
  its body when missing or retargeting its base to the default branch; merging it once
  CI passes; closing by hand, with a back-reference comment naming the PR, the issue
  that merged PR was meant to close when GitHub left it open; for the design-held issue
  the run takes on, its design-decision comment and then clearing its design block
  (the design-block label and the ship contract's `design=open`); filing and labelling
  follow-up issues; and removing `blocked: dependency` from the issues its merge
  unblocked — never a force-push, a branch deletion, a reply to or resolution of a
  review thread, `@codex review`, `just labels`, or Auto-fix.
- `create-pr`: pushing the current branch, `gh pr create` for it, and
  `gh pr edit` on its own open pull request — never a force-push or a merge.
- `smart-commit`: the commits it makes on the current branch, and pushing that
  branch only when asked — never a force-push and never `main`.

One request is a standing exception too: the owner explicitly asking for an
issue ("file an issue for this") signs off the `gh issue create` of each issue it
asks for, with the labels `triaging-issues` gives it. An issue the agent would
file on its own initiative is drafted in the reply and waits for a yes.

None of them covers a force-push or other history rewrite, `--no-verify` or
any other hook bypass, weakening a gate, or adding a dependency — a new
dependency is proposed and the agent stops for sign-off.

## Enforcement layers

Each layer catches what the one before it cannot; `changing-gates` owns them.

| Layer | Runs | Holds |
|---|---|---|
| Git hooks (pre-commit, `.pre-commit-config.yaml`) | Every `git commit` by any author — a human, Claude Code, Codex CLI, any tool; `check-staged` also on merge commits | No staged secret (`check-staged`), no commit on `main` (`no-commit-to-branch`), ruff, ruff-format, mypy, typos, zizmor, the skills mirror |
| `just verify` | Before a pull request or a completion claim | A current `uv.lock`, the skills mirror, the harness self-checks (`check-harness`), ruff, mypy, the skill script tests, the test suite and its 80% branch-coverage floor |
| CI (`.github/workflows/`) | Every pull request and push to `main`, unless noted | The `just verify` checks, the browser test (`just e2e`), typos, zizmor, and CodeQL; the PR title and Dependency Review (pull requests only); OSV-Scanner (when `uv.lock` or `pnpm-lock.yaml` changes, and weekly); gitleaks over the whole history (weekly) |
| GitHub ruleset (`.github/rulesets/main.json`) | Every change to `main` | Every change arrives by a branch and a pull request, with the required checks green; no force-push, no deletion |

- How `just install` installs the hooks, and which commits run none:
  `changing-gates`' `references/pre-commit-layer.md`.
- No agent-specific hook, permission rule, model choice, or plugin marketplace
  is committed: one person's trust would bind every repository made from this
  template. Keep them in `~/.claude/settings.json`, `~/.codex/config.toml`, or
  the gitignored `.claude/settings.local.json` and `.codex/rules/local.rules`.
  The one committed hook, `.claude/settings.json`'s cloud-only SessionStart
  hook, grants no trust: it runs `just install`, nothing else.
- Only a human changes the live ruleset (`just ruleset`, an admin step) or the
  repository's security settings; `starting-an-app` lists what a new one enables.
