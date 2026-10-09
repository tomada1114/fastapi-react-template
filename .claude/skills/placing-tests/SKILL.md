---
name: placing-tests
description: >
  Decides where a new test file goes in the two test trees (backend/tests/ for the app:
  backend/tests/<layer>/test_<module>.py for backend/src/my_app/<layer>/; the root
  tests/ for scripts and the harness), where a fixture goes (backend/tests/conftest.py,
  a layer conftest.py, or the test file), which command runs it, how the suite runs in
  parallel in CI, and the 80% branch-coverage floor over backend/src. Use when adding a
  test file or a fixture, running one test, a coverage run drops below the floor, or CI
  test jobs slow down.
---

# Placing Tests

**Owns:** where a test file and a fixture go, which command runs them, how CI runs
them, and which coverage floor governs them. **Does not own:** how a test is written
(`writing-tests`); the tests bundled inside a skill's `scripts/tests/`
(`authoring-skills`); changing the floor, the pytest options, or the coverage config
(`changing-gates`).

## Two trees, each mirroring its source

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

- Used by every layer: `backend/tests/conftest.py`. It holds `make_container`,
  `fixed_clock`, `fixed_now`, `new_id` and `nth_id` (predictable ids), the
  session-scoped `anyio_backend` that runs async tests on asyncio (`writing-tests`'
  "Async tests"), and the autouse fixture that keeps a
  developer's `MY_APP_*` variables out of every test. `backend/tests/settings_env.py` derives the
  cleanup from the settings prefix and model aliases.
- Used by one layer: that layer's `conftest.py` — `backend/tests/api/conftest.py`
  holds `client`.
- Used by one file: that file. A fixture moves up only when a second file needs it.
- The narrowest scope that works (`writing-tests`' "Fixtures").

## Running tests

From the repository root:

```bash
uv run --locked --directory backend pytest tests/<layer>/test_<module>.py::test_<name>  # one app test
uv run --locked --directory backend pytest tests/<layer>/   # one app layer
just backend test                                           # the app's suite, coverage floor
uv run --locked pytest tests/test_<script>.py               # one root test file
just test                                                   # both suites
```

`--directory backend` runs pytest in `backend/`, so the paths after it are relative to
`backend/`. Each tree's `[tool.pytest.ini_options]` runs with
`--import-mode=importlib`, `--strict-markers`, and `--strict-config`: an unregistered
marker or a misspelled option is an error, not a warning. `filterwarnings = ["error"]`
makes any warning, a `DeprecationWarning` above all, fail the test that raised it.
`just test` adds `-n auto`, so both suites run across processes. The map from a changed
path to its narrowest check is `backend/AGENTS.md`'s "Validating a change" for the app,
AGENTS.md's for the rest.

## CI test runner

CI's `Coverage` job runs the same two commands as `just test`: the root suite, then the
app's suite with the coverage floor in `backend/`. The recipe parity check in
`tests/harness/test_just_recipes.py` rejects command drift.

## The coverage floor

- **80%, with branch coverage, over `backend/src` only.** `backend/pyproject.toml`'s
  `[tool.coverage.run]` sets `branch = true` and `source = ["src"]`; `backend/justfile`'s
  `test` (`just backend test`, which `just test` runs) enforces the floor with
  `--cov-fail-under=80`, and CI's `Coverage` job with the same command. Neither
  `scripts/` nor either `tests/` tree is measured, so a script's tests guard behavior
  but move no number.
- **A floor, not a ceiling.** It is never lowered (AGENTS.md's "Security and human
  approval"), and no line leaves the measurement to move the number — a
  `# pragma: no cover`, an `omit`, or an `exclude_lines` entry is a weakened gate, as
  `changing-gates`' "What weakening a gate means here" lists.
- **Branch coverage matters more than line coverage.** Cover both sides of a
  conditional; a test that only adds a line hit is not the fix.
- **Missing coverage asks "is this reachable?"** If no input reaches the branch, delete
  it rather than test around it.
- **Never write a trivial test to hit the number.** Cover an edge case or an error path
  instead.

When `just backend test` fails on the floor, read the `term-missing` report it prints,
add real coverage for the uncovered branch, and run it again.
