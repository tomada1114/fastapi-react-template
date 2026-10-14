---
name: tdd
description: >
  Settles the order of work for a behavior change under backend/src/, scripts/, or
  frontend/src/: where the code goes, the failing test before the implementation,
  proving with uv run --locked pytest or pnpm --dir frontend exec vitest run that it
  fails for the right reason (not an import error), the smallest change that turns it
  green, refactoring with the tests on, the regression test a bug fix starts from, and
  landing test and code in one commit. Use when adding a function, a route, a domain
  rule, or a component, fixing a bug, or when a test written after the code only
  restates it.
---

# Test-Driven Development

**Owns:** the order of work on a behavior change — where the code goes, the failing test
before it, the proof that the test fails, the smallest change that passes, the refactor,
and the commit. **Does not own:** how a test case is written (`writing-tests`); which
file it goes in and the coverage floor (`placing-tests`); the layers themselves and the
direction imports run (`backend/AGENTS.md`'s "Architecture", `designing-core-logic`);
the map from a changed path to its narrowest check (the "Validating a change" tables of
`backend/AGENTS.md`, `frontend/AGENTS.md`, and AGENTS.md).

A test written after the code asserts whatever the code happens to do. It passes on its
first run, so nothing ever showed it can fail, and every gate is green over a test that
cannot tell right from wrong. Writing it first and watching it fail is the cheap way to
know it can.

A change with no behavior — a rename, a comment, a reformat — needs no new test; the
tests that already cover the code are its check.

## Where the code lives

Decide this before the test, because the layer decides which surface the test drives.

- **A decision** — a rule, a calculation, a state transition — goes in `core/`, tested
  by calling the service or model directly with the in-memory fake, `fixed_clock`, and
  `new_id`. **REQUIRED:** `designing-core-logic`.
- **A route** only translates between HTTP and a service; what belongs in one, and
  what moves down into the core, is **REQUIRED:** `building-api-routes`.
- **A storage detail** is an adapter. **REQUIRED:** `designing-core-logic`.
- **A repository script** under `scripts/` is tested through its `main()` and its public
  functions. **REQUIRED:** `writing-repo-scripts`.
- **A screen, a component, or a frontend helper** under `frontend/src/` is tested by a
  Vitest component test that renders the feature component, with MSW answering the
  API. **REQUIRED:** `building-screens`.

## Red: the test first

- Write the test for the behavior a caller observes, through the layer's surface, before
  touching the code. **REQUIRED:** `writing-tests` for the body, `placing-tests` for the
  file.
- Write the edge cases now, as parametrized cases. A case added after green is written
  against what the code returns, which is the failure this order exists to prevent.
- One behavior per cycle. A batch of tests followed by a batch of code leaves no single
  red to attribute to a single change.
- A test of the async path is itself `async def`, in a module marked
  `pytestmark = pytest.mark.anyio` (`writing-tests`' "Async tests"):

  ```python
  async def test_complete_open_todo_marks_it_completed(service):
      todo = await service.create("buy milk")

      completed = await service.complete(todo.id)

      assert completed.is_completed is True
  ```

## Prove it fails, for the right reason

Run the one test from the repository root — for the app,
`uv run --locked --directory backend pytest tests/<layer>/test_<module>.py::test_<name>`;
for a script, `uv run --locked pytest tests/test_<script>.py::test_<name>` — and read the
failure. Red alone is not the proof; the reason is.

| The run reports | Counts as red |
|---|---|
| The new assertion itself, with pytest's expected-versus-actual diff | yes — the only red that counts for a behavior change |
| `NotImplementedError` from a stub, or an `AttributeError`/`TypeError` naming the function or argument not yet written | yes, for code that does not exist yet |
| `ImportError` and `Interrupted: 1 error during collection` | no — the run never reached the test |
| A syntax error, a typo in the test, `fixture '<name>' not found` | no — fix the test and run again |
| `async def functions are not natively supported` | no — the module lacks the `anyio` marker, so the test never ran |
| `TypeError: '<type>' object can't be awaited` | yes, while the code under test is still a plain `def` the test now awaits |
| Green | no — the test does not cover the change; rewrite it |

A name the test imports but the module does not define yet fails collection before any
test runs (observed with pytest 9.1.1, 2026-10-06), so that run proves only the import
path. Add a stub that raises `NotImplementedError` and run again: now the failure comes
from inside the test.

### The frontend

Run the one file from the repository root,
`pnpm --dir frontend exec vitest run tests/<path>.test.tsx` (`-t "<describe> > <it>"`
for one test), and read the failure the same way (observed with Vitest 5.0.3,
2026-10-14):

| The run reports | Counts as red |
|---|---|
| `AssertionError` with its `Expected` / `Received` diff, or `TestingLibraryElementError: Unable to find role=...` from a `findBy...` waiting for what the change should render | yes |
| An error a stub throws from inside the test (`Error: not implemented`) | yes, for code that does not exist yet |
| `Failed to resolve import "../src/..."` under `Failed Suites`, with `Tests  no tests` | no — the file never ran; add the module with a stub export |
| `No test files found, exiting with code 1` | no — the path filter matched no file |
| Green, or every test `skipped` (a `-t` pattern that matched nothing) | no |

Vitest does not type-check: a test assigning a string to a `number` still ran and
passed (observed with Vitest 5.0.3, 2026-10-14). A type error is `tsc`'s, through
`just frontend lint`, never the red this run proves. Widen to `just frontend test` for
the coverage gate once green.

Never skip this run, even when the failure looks certain. A test that has never failed
has proven nothing.

## Green: the smallest change that passes

- Write only what the failing test demands. A branch no test asks for waits for the test
  that does.
- Re-run the one test until it passes, then the layer's directory
  (`uv run --locked --directory backend pytest tests/<layer>/`) for whatever else the
  change reached.
- Green reached by editing the test is not green. An assertion changes only when the
  expectation itself was wrong, and the pull request says so.

## Refactor with the tests on

With the tests green, restructure — rename, extract into the core, remove duplication —
without changing behavior, re-running the tests after each step. A refactor that needs
an assertion changed has changed behavior; that is a new red, not a refactor.

Then widen to the narrowest check for what changed (the "Validating a change" table of
`backend/AGENTS.md`, `frontend/AGENTS.md`, or AGENTS.md), and to `just verify` before
calling the work done.

## Fixing a bug

The regression test comes before the fix, and it reproduces the bug through the
interface the caller hit — not through a helper the bug happened to pass through.

1. Write the test the way the caller met the bug: a `TestClient` request for a wrong
   response, the service called directly for a wrong value, the component rendered
   against MSW for a wrong screen. Name it after the
   behavior, not the report.
2. Prove it fails with the bug's own symptom — the wrong status, the wrong text, the
   wrong value — not with any error at all.
3. Then green and refactor as above. The regression test stays.

## Commit

The test and the implementation land in one commit, with any document the change owes.
A code-only commit puts untested behavior on the branch, and a test added in a later
commit can no longer be shown to have failed against it. **BACKGROUND:** `smart-commit`'s
"Group".

## Anti-patterns

- Implementation first, then a test that asserts what the code returned.
- Weakening or deleting an assertion to reach green, or pasting in whatever value the
  code produced as the expected one.
- `@pytest.mark.skip`, `xfail`, `it.skip`, or `it.todo` for a case that does not pass
  yet.
- Asserting a private helper's call count instead of the behavior it serves.
- A real `time.sleep()` to wait something out instead of an injected clock.
- Skipping the failing run because the failure was obvious.
