---
name: placing-tests
description: >
  Decides where a new test file goes under tests/ (tests/<layer>/test_<module>.py for
  src/my_app/<layer>/, tests/test_<module>.py for settings, composition, and scripts),
  where a fixture goes (tests/conftest.py, a layer conftest.py, or the test file), which
  command runs it, how the suite runs in parallel in CI, and the 80%
  branch-coverage floor over src/. Use when adding a test file or a fixture, running one
  test, a coverage run drops below the floor, or CI test jobs slow down.
---

# Placing Tests

**Owns:** where a test file and a fixture go, which command runs them, how CI runs
them, and which coverage floor governs them. **Does not own:** how a test is written
(`writing-tests`); the tests bundled inside a skill's `scripts/tests/`
(`authoring-skills`); changing the floor, the pytest options, or the coverage config
(`changing-gates`).

## The tree mirrors the source

| Code under test | Its test file |
|---|---|
| `src/my_app/<layer>/<module>.py` (`core`, `adapters`, `api`, `cli`) | `tests/<layer>/test_<module>.py` |
| A top-level module (`settings.py`, `composition.py`) | `tests/test_<module>.py` |
| `scripts/<script>.py` | `tests/test_<script>.py` |
| Agent tier definitions in `.claude/agents/` and `.codex/agents/` | `tests/test_agent_tiers.py` |
| A cross-file rule of the agent harness (skills, AGENTS.md's Skills table, `just` recipes named in docs, ruleset contexts, labels, workflow hygiene) | `tests/harness/test_<family>.py`, run by `just check-harness` |

- A new module gets its test file in the same commit as the module. **BACKGROUND:**
  `tdd`.
- Every directory under `tests/` carries an `__init__.py`; a new layer directory does
  too.
- `tests/core/test_errors.py` and `tests/cli/test_errors.py` share a basename on
  purpose: each mirrors its own `errors.py`.

Three files hold a rule for a whole layer rather than one module, and grow by a new case
rather than by a new file:

- `tests/adapters/test_repository_contract.py` — the one contract suite every
  repository adapter runs; how an adapter joins it, and what goes in its own file
  instead. **REQUIRED:** `designing-core-logic`.
- `tests/core/test_imports.py` — the core's import boundary. **BACKGROUND:**
  `designing-core-logic`.
- `tests/core/test_errors.py` — every `AppError` subclass joins its parametrized tests.
  **REQUIRED:** `designing-errors`.

## Where a fixture goes

- Used by every layer: `tests/conftest.py`. It holds `make_container`, `fixed_clock`,
  `fixed_now`, and the autouse fixture that keeps a developer's `MY_APP_*` variables
  out of every test. `tests/settings_env.py` derives the cleanup from the settings
  prefix and model aliases, shared with subprocess probes.
- Used by one layer: that layer's `conftest.py` — `tests/api/conftest.py` holds
  `client`.
- Used by one file: that file. A fixture moves up only when a second file needs it.
- The narrowest scope that works (`writing-tests`' "Fixtures").

## Running tests

```bash
uv run --locked pytest tests/<layer>/test_<module>.py::test_<name>   # one test
uv run --locked pytest tests/<layer>/                                  # one layer
just test                                                              # whole suite, coverage floor
```

`[tool.pytest.ini_options]` runs with `--import-mode=importlib`, `--strict-markers`,
and `--strict-config`: an unregistered marker or a misspelled option is an error, not a
warning. `filterwarnings = ["error"]` makes any warning, a `DeprecationWarning` above
all, fail the test that raised it. `just test` adds `-n auto`, so the suite runs across processes. The map from a
changed path to its narrowest check is AGENTS.md's "Validating a change".

## CI test runner

CI's `Coverage` job runs the same parallel suite and coverage command as `just test`.
The recipe parity check in `tests/harness/test_just_recipes.py` rejects command drift.

## The coverage floor

- **80%, with branch coverage, over `src/` only.** `[tool.coverage.run]` sets
  `branch = true` and `source = ["src"]`; `just test` enforces the floor with
  `--cov-fail-under=80`, and CI's `Coverage` job with the same command. Neither `scripts/` nor
  `tests/` is measured, so a script's tests guard behavior but move no number.
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

When `just test` fails on the floor, read the `term-missing` report it prints, add real
coverage for the uncovered branch, and run it again.
