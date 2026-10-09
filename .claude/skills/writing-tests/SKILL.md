---
name: writing-tests
description: >
  Covers how one pytest test is written under backend/tests/ or the root tests/: its
  test_<what>_<scenario>_<expected> name, Arrange-Act-Assert, testing behavior through
  a layer's public module, edge cases to sweep, pytest.raises with match=, parametrize
  with pytest.param ids, factory fixtures, tmp_path and monkeypatch, fakes over mocks,
  no sleep, skip, or order dependency, and the anti-patterns to reject in review. Use
  when writing or reviewing a test, choosing what to assert or what to fake, or fixing
  a flaky or skipped test.
---

# Writing Tests

**Owns:** how one test case is written — its name, the interface it goes through, what
it asserts, how it fakes the world, and what to reject in review. **Does not own:** which
file and directory a test lives in, the fixtures' homes, and the coverage floor
(`placing-tests`); the order of work that puts the test first (`tdd`); the mechanics of
each seam (`building-api-routes`, `designing-core-logic`); the error classes a test
asserts against (`designing-errors`); a script's tests (`writing-repo-scripts`).

## Naming and shape

- Name a test `test_<what>_<scenario>_<expected_result>`:
  `test_parse_config_empty_string_raises_value_error`. The suite's own
  `test_unmapped_app_error_returns_400_not_500` reads the same way.
- Arrange, Act, Assert, in that order. One logical behavior per test; several `assert`
  statements are fine when they all check that one behavior.
- Branching inside a test body belongs in a separate test or a parametrized case, never
  an `if` in the test.

## Test behavior through a public surface

- Test *behavior and contracts*, not implementation details. A test that breaks on a
  refactor while behavior is unchanged was testing the implementation.
- Go through each layer's public modules —
  `from my_app.core.services import TodoService` — never a private helper directly.
  Wanting to reach a private helper means the module is the wrong shape, not that the
  test needs an exception.
- Cover the happy path **and** the error path of every public function.
- Each layer has one seam, and its skill owns the mechanics:
  - a route — **REQUIRED:** `building-api-routes` ("Testing a route": the `client`
    fixture);
  - a service, a port, or an adapter — **REQUIRED:** `designing-core-logic` (the one
    repository contract suite, the in-memory fake, and containers built through the
    composition root rather than wired by hand).

## Expected values come from outside the code

An expected value is a literal, a worked example, or the spec — never recomputed the way
the implementation computes it. `assert add(a, b) == a + b` passes by construction and
cannot disagree with a wrong implementation. Write the value you expect by hand. The
`fixed_now` fixture exists so a timestamp in an assertion is exact rather than
"whatever the clock said".

Do not write `assert True` or `assert result is not None` when a specific value can be
checked.

## Edge cases — consider these every time

- **Empty inputs:** empty string, empty list, empty dict, `None` where optional.
- **Boundary values:** 0, 1, -1, the largest and smallest values the code accepts,
  `float("inf")`, `float("nan")`; one past every documented limit
  (`MAX_TITLE_LENGTH` + 1).
- **Type boundaries:** very long strings, unicode and emoji, mixed encodings,
  surrounding whitespace.
- **Collection boundaries:** a single element, duplicate elements, the largest expected
  size.
- **Concurrency:** for async code, cancellation and timeouts.
- **State transitions:** the initial state, after one operation, after repeated
  operations, and after recovery from an error.

## Errors and exceptions

- `pytest.raises(XError, match=r"expected message")` — always with `match=`. The pattern
  proves the error was raised for the reason the test claims, not merely that some error
  of that class surfaced.
- Test that cleanup runs when an exception occurs: a context manager's exit, a `finally`,
  a transaction rolled back.
- Test recovery: after an error, is the object still consistent and usable? Repeat a
  successful operation after the failed one.
- An `AppError` crossing the API is asserted as the API reports it — the status and
  exact body. **BACKGROUND:** `designing-errors`.

## Parametrize instead of copying

- `@pytest.mark.parametrize` for input/output variations; never copy-paste a test body
  to change one value.
- Give each case a readable id, `pytest.param(..., id="descriptive-name")`, whenever the
  raw values would not read as a test name in a failure report.
- `hypothesis` fits a function with a well-defined invariant over a large input space —
  a round trip, an idempotent normalization. It is not a dependency here; adding it to
  the `dev` group is a new dependency. **REQUIRED:** `managing-dependencies`.

## Fixtures

- Prefer a factory fixture to a static one: it returns a callable that builds a
  customizable object (`def make_user(**overrides)`). `make_container` and
  `backend/tests/api/test_todos.py`'s `make_todo` are the shape.
- `tmp_path` for every file the test writes; never write into the repository tree.
- `monkeypatch` for environment variables and attributes — `monkeypatch.setenv`,
  never `os.environ[...] =` — so the change is undone after the test.
- A fixture that opens a resource `yield`s it and cleans up after the `yield`, so the
  teardown runs even when the test fails.
- Scope a fixture `function` (the default) for isolation; `session` only for setup that
  is truly expensive and never mutated.

## Fakes over mocks

- Mock only at a boundary: I/O, network, clock, a subprocess, an external service —
  never the unit under test and never an internal collaborator.
- Prefer a fake (a real in-memory implementation) to a mock for a repository or a store.
  `InMemoryTodoRepository` is the core's fake and `fixed_clock` fixes time; both are
  real code paths, so the code under test runs as it does in production.
- Assert on outcomes and captured arguments, not on how many times something was called
  — except when the call itself is the contract: retry or rate-limit behavior, a step
  that must be skipped, proving that no network call happened.
- A test needing more than two mocks usually means the code under test has too many
  dependencies; reshape the code rather than the test.

## Independence and reliability

- No shared mutable state and no ordering dependency. Each test passes alone
  (`uv run --locked --directory backend pytest tests/<layer>/test_<module>.py::test_<name>`),
  in any order, in any process: `just test` runs the suite with `pytest-xdist`
  (`-n auto`) and CI also runs it across processes, so a hidden dependency surfaces as
  an intermittent failure.
- No `time.sleep()`: inject the clock (`fixed_clock`) or patch it with `monkeypatch`.
- No `@pytest.mark.skip`, `xfail`, or TODO test on `main` — fix the test or delete it.
  Skipping a test is weakening a gate (AGENTS.md's "Security and human approval").
- A flaky test is fixed immediately, never retried or ignored.

## Anti-patterns to reject in review

- Testing getters and setters while a business rule's edge cases go untested.
- A vague assertion where a specific value is checkable.
- Testing that a dependency works (that `json.loads` parses JSON) rather than how this
  code uses it.
- Mocking so much that the real code under test never runs — tests against real
  collaborators catch real bugs.
- A trivial test written only to move the coverage number. **BACKGROUND:**
  `placing-tests` on what the floor measures.
