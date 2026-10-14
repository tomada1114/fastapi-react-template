---
name: starting-an-app
description: >
  Covers setting up an app cut from this full-stack template, up to its first feature:
  the prerequisites (uv, Just, Node.js 24, pnpm), AGENTS.md's Product section, the
  bootstrap pull request, the roadmap, just labels, GitHub security settings, just
  ruleset and a private repository, the app's shape (full-stack, or API-only without
  frontend/ and e2e/), removing the sample to-do domain and screen, and the first design
  changes. In the template it also covers the rename step, .template-origin, and the
  smoke check. Use when starting an app, dropping the frontend, or a placeholder
  survived the rename.
---

# Starting an App

**Owns:** the order of work from "Use this template" to an app's first feature: the
rename, the Product section and roadmap as steps, the app's shape, removing the sample,
the first design changes, and the new repository's GitHub setup. **Does not own:** what
the roadmap says (`steering-the-roadmap`); how a design change is described
(`AGENTS.md`'s "Before changing the architecture"); labels and issue bodies (`triaging-issues`);
what makes a CI job a required check (`changing-gates`); which files go with the API
(`building-api-routes`).

Steps marked **human** are a person's: an agent never runs them, and only drafts or
lists them for the owner. Steps that write to GitHub run only with the owner's sign-off
(`AGENTS.md`'s "Security and human approval"). A caller that drives these steps (for
example an agent skill that cuts repositories from templates) follows the same order.

## The order

1. **Create and clone.** "Use this template" on GitHub and clone the new repository.
   It needs uv, Just 1.42.3 or later, Node.js 24 (`.node-version`), and pnpm 11
   (`corepack enable`, or any pnpm 11: it fetches the `pnpm@11.18.0` that
   `package.json` pins), but no Docker; CONTRIBUTING.md's "Prerequisites" has the links. Run
   `just install`, which installs both workspaces (uv's, then pnpm's) and the git
   hooks, then `git switch -c chore/bootstrap`. The `no-commit-to-branch` hook that
   `just install` installs refuses a commit on `main`, and bypassing a hook is
   forbidden (`AGENTS.md`'s "Security and human approval"), so the first commit is made
   on a branch like every later one.
2. **Rename.** `scripts/bootstrap.py` renames the template into the app, writes
   `.template-origin`, and deletes itself, so in an app this step is already done.
   `.template-origin` names the template repository and, when the clone's history
   starts at the template's first commit, the template commit. GitHub's "Use this
   template" starts the new repository with a single commit
   (https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template,
   checked 2026-10-06), so there it records `commit: unknown` and the tree, and its
   header gives the `git log … | grep <tree>` search that finds the template commit
   with the same files.
   <!-- template-only -->
   It rewrites the whole repository, so run it only on the owner's request, on a fresh
   clone with a clean work tree. **REQUIRED:**
   [references/bootstrap.md](references/bootstrap.md), for its flags, what it refuses,
   what it removes, and how to recover from a failed write, before running it, changing
   it, or chasing a leftover placeholder.
   <!-- /template-only -->
3. **Write `AGENTS.md`'s Product section**: what the app is and for whom, the core
   interaction, the non-goals, and why it is shaped this way, in the present tense. It is the one home of the app's non-goals. The
   owner decides every entry; an agent drafts one only from what the owner has said.
   `tests/test_product_section.py`, and so `just verify`, fails while an entry is still
   a placeholder. Write it before any feature: a non-goal nobody wrote down is one an
   eager implementer reads as a feature.
4. **Commit and open the bootstrap pull request.** Review `git status` and `git diff`,
   run `just verify`, and commit the rewrite and the Product section as one
   `chore: bootstrap <app> from the template` commit, so the rename stays one reviewable
   diff. Push the branch and open a pull request; merge it once CI is green. A pull
   request rather than a push to `main`, because it is how every change lands here
   (`AGENTS.md`'s "Enforcement layers"), CI checks the bootstrap before `main` holds it, and
   it works the same before and after step 9's ruleset. Pushing, opening, and merging
   are remote writes.
5. **Fill `docs/architecture/roadmap.md`** in its own pull request, with the Now, Next,
   and Later outcomes that follow from the Product section. **REQUIRED:**
   `steering-the-roadmap`.
6. **Labels.** `just labels` creates `.github/labels.yml`'s labels on the new
   repository. Run it before the first issue is filed: an issue form or a planning tool
   applying a missing label loses it silently. It writes to GitHub. **BACKGROUND:**
   `triaging-issues`, for what each label means.
7. **Security settings and secrets** (**human**, the repository's admin): turn on what
   [references/github-settings.md](references/github-settings.md) › "Security settings"
   lists. The template's workflows need no secret beyond the `GITHUB_TOKEN` GitHub
   provides; a secret the app adds later (a deploy key, an API key) is set by a person
   in the repository's settings and never committed — `check-staged` refuses one.
8. **Replace the sample**, in the order of the sections below: the app's shape, the
   first design changes, then the to-do domain.
9. **Ruleset, last** (**human**, an admin): `just ruleset` applies
   `.github/rulesets/main.json` ([references/github-settings.md](references/github-settings.md)
   › "Main branch ruleset"). From then on every change needs a pull request with
   the required checks green, so the ruleset must name only jobs the app still runs.
   On a **private repository**, first **REQUIRED:**
   [references/private-repository.md](references/private-repository.md).

## Choose the app's shape

The template ships a full-stack app: the FastAPI HTTP API over a framework-free core,
and a React screen in `frontend/` that calls it through a generated client, proven end
to end by the browser test in `e2e/`. Decide what the app needs before its first
feature, and write the answer into the Product section's core interaction:

- **Full-stack**, the default, for an app people use through its screen — the shape the
  template ships.
- **API-only**, for a service other programs call over HTTP: drop the screen, the
  browser test, and the Node.js toolchain. **REQUIRED:**
  [references/without-frontend.md](references/without-frontend.md), which lists every
  path each frontend change added and how it goes. An API-only service may instead
  start from `tomada1114/uv-template`, the Python-only template, which has no frontend
  to remove.
- **Core only**, for a library with no entry point of its own: go API-only first, then
  follow the "A project without the API" section of `building-api-routes`, which names
  every file, dependency, recipe, ruff entry, and skill that goes with the API.

Each is a list of deletions, never a core change. Run `uv lock` after removing a
dependency, then `just verify`. An app that needs admin commands adds a command-line
entry point beside the API, over the same core.

## Describe the first design changes

Write each as present state — what the app does and why — in `AGENTS.md` and
`backend/AGENTS.md`'s "Architecture" section, per `AGENTS.md`'s "Before changing the
architecture"; the owner reviews it with the pull request:

- **App shape**: full-stack, API-only, or core only, and why.
- **Persistence**: where and in what format the app keeps state, with how a schema
  change reaches existing data. The template's default is SQLAlchemy Core with Alembic
  migrations on a SQLite file, and the same contract suite runs against PostgreSQL in
  CI; the in-memory repository serves when no database URL is set. Write it as soon as
  the app keeps state of its own, whether it keeps that default, moves to PostgreSQL,
  or adopts another store.

Each new runtime dependency or external service the first features need is a design
change too, described the same way, and a new dependency waits for the owner's sign-off.

## Remove the sample to-do domain

The to-do list is a deletable illustration, not the app. Replace it in the same pull
request that removes it, so the tests and the 80% coverage floor still measure real
code:

- the domain in `backend/src/my_app/core/` (`models.py`, `ports.py`, `services.py`, and
  the `TodoNotFoundError`, `InvalidTodoError`, `InvalidCursorError`, and
  `InvalidPageLimitError` in `errors.py`), and the adapters in
  `backend/src/my_app/adapters/` that implement its repository port, with the cursor
  helper they share (`cursor.py`, which the app's own paged port can adapt);
- the API's wrappers: `backend/src/my_app/api/routers/todos.py` and the to-do models
  in `api/schemas.py`;
- their tests under `backend/tests/core/`, `backend/tests/adapters/`, and
  `backend/tests/api/`, and the contract suite's parameters in
  `backend/tests/adapters/test_repository_contract.py`;
- the `todos` table in `backend/src/my_app/adapters/sql/tables.py` and its migration,
  `backend/migrations/versions/f58f944d0d8e_create_todos.py`: with no deployed
  database yet, replace that first revision with the app's own; once one is deployed,
  add a revision that drops the table instead (**REQUIRED:** `persisting-data`);
- the screen: `frontend/src/features/todos/`, and the to-do screen in the index route
  that renders it, `frontend/src/routes/index.tsx`, replaced by the app's own; their
  tests under `frontend/tests/features/todos/` and `frontend/tests/routes/`; and the
  to-do handler and `todo(...)` builder in `frontend/tests/msw/` (**REQUIRED:**
  `building-screens`);
- the browser test's flow: `e2e/tests/todos.spec.ts`, and `e2e/verify_persistence.py`
  with `backend/tests/test_e2e_persistence.py`, which read a stored to-do;
- then rerun the `contract` recipe, so `frontend/openapi.json` and the generated
  client in `frontend/src/api/generated/` lose the to-do operations;
- README's Quickstart, the HTTP table, and the Configuration section;
- the examples the skills quote from the sample: `writing-python`, `designing-errors`,
  `designing-core-logic`, `building-api-routes`, `persisting-data`, `running-the-app`
  (and its `references/e2e.md` and `references/own-dev-pair.md`), `building-screens`
  (and its `references/accessibility.md` and `references/testing-screens.md`),
  `writing-tests` (and its `references/frontend-tests.md`), `placing-tests`, and `tdd`.
  Rewrite each with the app's own code, keeping the rule around it, then
  `just agents-sync`.

Keep what is general: `core.errors.AppError` and the one place the API maps it (its
handler in `api/app.py`), the composition root, `settings.py` and its environment
prefix, the health route, the banned-api lint rule that keeps the core framework-free,
`backend/tests/conftest.py`'s fixed clock, and on the screen the root route,
`frontend/src/lib/` (the query client and the Problem Details error display), and the
MSW server in `frontend/tests/msw/`. Then search the tree for `Todo`, `todo`, and
`to-do`, and judge each hit: an app whose own name holds one of them keeps those.

## What the new app keeps

Everything about the repository rather than the application survives unchanged: the
`justfile`, every workflow except the template's own bootstrap job, the pre-commit layer
and its secret gate, the skills and sub-agent tiers (drop a skill only when its subject
leaves the repository, with its row in `AGENTS.md`'s Skills table), the label set, and
the ruleset. A red check early in a new app is an argument for fixing the code, never
for deleting or weakening the check.
