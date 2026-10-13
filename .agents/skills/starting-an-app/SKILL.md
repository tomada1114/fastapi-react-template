---
name: starting-an-app
description: >
  Covers setting up an app cut from this template, from the first commit to its first
  feature: AGENTS.md's Product section and tests/test_product_section.py, the bootstrap
  pull request, the roadmap, just labels, GitHub security settings and secrets, just
  ruleset and a private repository, keeping or dropping the HTTP API, removing the
  sample to-do domain, and the first ADRs (app shape, persistence). In the template it
  also covers the rename step, .template-origin, and the template smoke check. Use when
  starting an app, setting up the new repository, or a placeholder survived the rename.
---

# Starting an App

**Owns:** the order of work from "Use this template" to an app's first feature: the
rename, the Product section and roadmap as steps, the app's shape, removing the sample,
the first ADRs, and the new repository's GitHub setup. **Does not own:** what the
roadmap says (`steering-the-roadmap`); how an ADR is written
(`recording-architecture-decisions`); labels and issue bodies (`triaging-issues`);
what makes a CI job a required check (`changing-gates`); which files go with the API
(`building-api-routes`).

Steps marked **human** are a person's: an agent never runs them, and only drafts or
lists them for the owner. Steps that write to GitHub run only with the owner's sign-off
(`AGENTS.md`'s "Security and human approval"). A caller that drives these steps (for
example an agent skill that cuts repositories from templates) follows the same order.

## The order

1. **Create and clone.** "Use this template" on GitHub, clone the new repository, run
   `just install`, then `git switch -c chore/bootstrap`. The `no-commit-to-branch` hook
   that `just install` installs refuses a commit on `main`, and bypassing a hook is
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
   interaction, the non-goals, and where those decisions are recorded
   (`docs/product/requirements.md`). It is the one home of the app's non-goals. The
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
   first ADRs, then the to-do domain.
9. **Ruleset, last** (**human**, an admin): `just ruleset` applies
   `.github/rulesets/main.json` ([references/github-settings.md](references/github-settings.md)
   › "Main branch ruleset"). From then on every change needs a pull request with
   the required checks green, so the ruleset must name only jobs the app still runs.
   On a **private repository**, first **REQUIRED:**
   [references/private-repository.md](references/private-repository.md).

## Choose the app's shape

The template ships one entry point over a framework-free core: the FastAPI HTTP API.
Decide what the app needs before its first feature, and write the answer into the
Product section's core interaction:

- **API**, for a service other programs call over HTTP — the shape the template ships.
- **Core only**, for a library with no entry point of its own.

Dropping the API is a list of deletions, never a core change: the "A project without
the API" section of `building-api-routes` names every file, dependency, recipe, ruff
entry, and skill that goes with it. Run `uv lock` after removing a dependency, then
`just verify`. An app that needs admin commands adds a command-line entry point beside
the API, over the same core.

## Record the first ADRs

Write each as Proposed (only the owner accepts), in `docs/architecture/adr/` with its
row in `docs/architecture/README.md`, per **REQUIRED:**
`recording-architecture-decisions`:

- **App shape**: whether the app keeps the API, and why.
- **Persistence**: where and in what format the app keeps state — the in-memory
  repository, the SQL adapter (SQLAlchemy with Alembic migrations, on SQLite or
  PostgreSQL), or another store — with how a schema change reaches existing data. Write it as soon as the app keeps state of its own.

Each new runtime dependency or external service the first features need is an ADR too,
and a new dependency waits for the owner's sign-off.

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
- README's Quickstart, the HTTP table, and the Configuration section;
- the examples the code-writing skills quote from the sample (`writing-python`,
  `designing-errors`, `designing-core-logic`, `building-api-routes`,
  `running-the-app`): rewrite each with the app's own code, keeping the rule around it,
  then `just agents-sync`.

Keep what is general: `core.errors.AppError` and the one place the API maps it (its
handler in `api/app.py`), the composition root, `settings.py` and its environment
prefix, the health route, the banned-api lint rule that keeps the core framework-free,
and `backend/tests/conftest.py`'s fixed clock. Then search the tree for `Todo`, `todo`,
and `to-do`, and judge each hit: an app whose own name holds one of them keeps those.

## What the new app keeps

Everything about the repository rather than the application survives unchanged: the
`justfile`, every workflow except the template's own bootstrap job, the pre-commit layer
and its secret gate, the skills and sub-agent tiers (drop a skill only when its subject
leaves the repository, with its row in `AGENTS.md`'s Skills table), the label set, and
the ruleset. A red check early in a new app is an argument for fixing the code, never
for deleting or weakening the check.
