---
name: placing-tests
description: >
  Decides where a new test file goes (backend/tests/<layer>/test_<module>.py for
  backend/src/my_app/<layer>/, the root tests/ for scripts and the harness,
  frontend/tests/ mirroring frontend/src/ as *.test.tsx, e2e/tests/ for a Playwright
  spec), where a fixture, helper, or MSW handler goes, which command runs one test, one
  file, or the suite (pytest, vitest run), and the coverage floors: 80% branches over
  backend/src, coverage.thresholds of 80 over frontend/src. Use when adding a test file
  or a fixture, running one test, a coverage run drops below a floor, or CI test jobs
  slow down.
---

# Placing Tests

**Owns:** where a test file and a fixture go, which command runs them, how CI runs
them, and which coverage floor governs them, for Python, the frontend, and the browser
test. **Does not own:** how a test is written (`writing-tests`); the tests bundled
inside a skill's `scripts/tests/` (`authoring-skills`); changing a floor, the pytest
options, or the coverage config (`changing-gates`); running the browser test against
its servers (`running-the-app`).

## The Python trees, each mirroring its source

The app's suite is `backend/tests/`, run from `backend/` with `backend/pyproject.toml`'s
pytest and coverage settings. The root `tests/` holds the repository's own code: the
scripts' tests and the harness, run with the root `pyproject.toml`'s pytest settings.
Both hold a `tests` package, so each tree runs on its own.

| Code under test | Its test file |
|---|---|
| `backend/src/my_app/<layer>/<module>.py` (`core`, `adapters`, `api`) | `backend/tests/<layer>/test_<module>.py` |
| A top-level app module (`settings.py`, `composition.py`) | `backend/tests/test_<module>.py` |
| `scripts/<script>.py` | `tests/test_<script>.py` |
| Agent tier definitions in `.claude/agents/` and `.codex/agents/` | `tests/test_agent_tiers.py` |
| A cross-file rule of the agent harness (skills, AGENTS.md's Skills table, `just` recipes named in docs, ruleset contexts, labels, workflow hygiene) | `tests/harness/test_<family>.py`, run by `just check-harness` |

- A new module gets its test file in the same commit as the module. **BACKGROUND:**
  `tdd`.
- Every directory under either `tests/` tree carries an `__init__.py`; a new layer
  directory does too.

Three files hold a rule for a whole layer rather than one module, and grow by a new case
rather than by a new file:

- `backend/tests/adapters/test_repository_contract.py` — the one contract suite every
  repository adapter runs; how an adapter joins it, and what goes in its own file
  instead. **REQUIRED:** `designing-core-logic`.
- `backend/tests/core/test_imports.py` — the core's import boundary. **BACKGROUND:**
  `designing-core-logic`.
- `backend/tests/core/test_errors.py` — every `AppError` subclass joins its
  parametrized tests. **REQUIRED:** `designing-errors`.

## Where a fixture goes

- Used by every layer: `backend/tests/conftest.py`. It holds `make_container` (which
  closes every container it built), `fixed_clock`, `fixed_now`, `new_id` and `nth_id`
  (predictable ids), `sqlite_url`, `alembic_config`, and `migrated_sqlite_url` (a
  SQLite file migrated to head; `persisting-data`), the session-scoped `anyio_backend`
  that runs async tests on asyncio (`writing-tests`' "Async tests"), and the autouse
  fixture that keeps a developer's `MY_APP_*` variables out of every test. `backend/tests/settings_env.py` derives the
  cleanup from the settings prefix and model aliases.
- Used by one layer: that layer's `conftest.py` — `backend/tests/api/conftest.py`
  holds `client`.
- Used by one file: that file. A fixture moves up only when a second file needs it.
- The narrowest scope that works (`writing-tests`' "Fixtures").

## The frontend and the browser test

The frontend's suite is `frontend/tests/`, run by Vitest with
`frontend/vitest.config.ts`; the browser test is `e2e/tests/`, run by Playwright through
`just e2e`.

| Code under test | Its test file |
|---|---|
| `frontend/src/<dir>/<Name>.tsx` (a feature, a route, `src/lib/`) | `frontend/tests/<dir>/<Name>.test.tsx` |
| `frontend/src/<dir>/<name>.ts` (no JSX) | `frontend/tests/<dir>/<name>.test.ts` |
| A user flow from the screen to the database | `e2e/tests/<flow>.spec.ts` (`running-the-app`) |

- A frontend test never sits beside its source. Vitest runs only
  `tests/**/*.test.{ts,tsx}` (`include` in `vitest.config.ts`), so a file named
  otherwise never runs and moves no number.
- A screen is tested through its feature component, and its route file through the
  router; a component a screen renders may be covered by the screen's test instead of
  a file of its own (`TodoList.tsx` is). **REQUIRED:** `building-screens`.
- Shared test code lives under `frontend/tests/`: `setup.ts` (the jest-dom matchers and
  `cleanup`, run before every file), `msw/server.ts` (the MSW server and its default
  handlers), and `msw/helpers.tsx` (`renderWithQuery`, `deferred`). A handler one test
  needs goes in that test with `server.use(...)`; one every test needs goes in
  `msw/server.ts`; a helper moves to `msw/helpers.tsx` only when a second file needs it.
- The browser test is one flow, not a second component suite: add a spec only for a
  flow that crosses the screen, the API, and the database.

## Running tests

From the repository root:

```bash
uv run --locked --directory backend pytest tests/<layer>/test_<module>.py::test_<name>  # one app test
uv run --locked --directory backend pytest tests/<layer>/   # one app layer
just backend test                                           # the app's suite, coverage floor
uv run --locked pytest tests/test_<script>.py               # one root test file
just test                                                   # both suites and the frontend's
pnpm --dir frontend exec vitest run tests/features/todos/TodoItem.test.tsx  # one frontend file
pnpm --dir frontend exec vitest run TodoItem -t "TodoItem > completes"       # one frontend test
just frontend test                                          # the frontend's suite, coverage gate
just e2e                                                    # the browser test
```

`vitest run <filter>` runs every test file whose path contains the string, and `-t`
takes a regex matched against the full test name, the `describe` names and the `it`
sentence joined with ` > ` (https://vitest.dev/guide/filtering, checked 2026-10-14). A
filter that matches no file exits 1 with `No test files found` (observed with Vitest
5.0.3, 2026-10-14), but a `-t` that matches no test skips every test and exits 0, so
read the `Tests` count before trusting a green run.

`--directory backend` runs pytest in `backend/`, and `--dir frontend` runs Vitest in
`frontend/`, so the paths after each are relative to that directory. Each tree's
`[tool.pytest.ini_options]` runs with `--import-mode=importlib`, `--strict-markers`, and
`--strict-config`: an unregistered marker or a misspelled option is an error, not a
warning. `filterwarnings = ["error"]` makes any warning, a `DeprecationWarning` above
all, fail the test that raised it. `just test` adds `-n auto`, so both suites run across
processes. The map from a changed path to its narrowest check is the "Validating a
change" table of `backend/AGENTS.md` for the app, of `frontend/AGENTS.md` for the
frontend, and of AGENTS.md for the rest.
## CI test runner

CI's `Coverage` job runs the same two Python commands as `just test`: the root suite,
then the app's suite with the coverage floor in `backend/`. The recipe parity check in
`tests/harness/test_just_recipes.py` rejects command drift. CI's `Frontend` job runs
`just frontend test`, and its `E2E` job `just e2e`.

## The coverage floor

- **80%, with branch coverage, over `backend/src` only.** `backend/pyproject.toml`'s
  `[tool.coverage.run]` sets `branch = true` and `source = ["src"]`; `backend/justfile`'s
  `test` (`just backend test`, which `just test` runs) enforces the floor with
  `--cov-fail-under=80`, and CI's `Coverage` job with the same command. Neither
  `scripts/` nor either `tests/` tree is measured, so a script's tests guard behavior
  but move no number.
- **80 on all four metrics over `frontend/src`.** `frontend/vitest.config.ts`'s
  `coverage.thresholds` sets `lines`, `functions`, `statements`, and `branches` to 80
  over `src/**/*.{ts,tsx}`, and its `coverage.exclude` leaves out generated code only
  (`src/api/generated/**`, `src/routeTree.gen.ts`). `just frontend test` (run by
  `just test` and CI's `Frontend` job) is `vitest run --coverage`, which fails below
  any of the four. Neither `frontend/tests/` nor `e2e/` is measured.
- **A floor, not a ceiling.** It is never lowered (AGENTS.md's "Security and human
  approval"), and no line leaves the measurement to move the number — a
  `# pragma: no cover`, an `omit`, an `exclude_lines` entry, a lowered
  `coverage.thresholds` value, or a wider `coverage.exclude` is a weakened gate, as
  `changing-gates`' "What weakening a gate means here" lists.
- **Branch coverage matters more than line coverage.** Cover both sides of a
  conditional; a test that only adds a line hit is not the fix.
- **Missing coverage asks "is this reachable?"** If no input reaches the branch, delete
  it rather than test around it.
- **Never write a trivial test to hit the number.** Cover an edge case or an error path
  instead.

When `just backend test` fails on the floor, read the `term-missing` report it prints,
add real coverage for the uncovered branch, and run it again. When `just frontend test`
does, read its `text` report's uncovered lines the same way.
