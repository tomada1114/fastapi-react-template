---
name: writing-repo-scripts
description: >
  Covers the contract for a repository script under scripts/*.py (sync_agents,
  sync_labels, apply_ruleset, check_staged, bootstrap): stdlib-only imports, the module
  docstring with Usage, main(argv) returning an exit code, failures reported on stderr
  as ERR_<STAGE>_<KIND> with Expected and Next lines, a gh or git subprocess with a
  fixed argv, scripts that write to GitHub, and tests in tests/test_<script>.py that
  load the script through importlib. Use when adding or editing a script, a just recipe
  that runs one, or its tests.
---

# Writing Repository Scripts

**Owns:** the contract every file under `scripts/` keeps — imports, entry point, error
reporting, subprocess use, GitHub writes, how it is tested — and every place a new
script must reach. **Does not own:** Python style inside the script (`writing-python`);
a script bundled inside a skill's `scripts/` (`authoring-skills`); wiring a script into
a gate (`changing-gates`); the `AppError` hierarchy of the application, which scripts do
not use (`designing-errors`).

## Standard library only

Every script imports only the standard library. A repository script must work in a
fresh checkout, in CI's `Lint & Type Check` job, and — for `check_staged.py` — under
pre-commit's own interpreter with no project environment at all. `sync_labels.py` reads
`.github/labels.yml` with a small scanner rather than a YAML dependency, and the GitHub
scripts call `gh` rather than an HTTP client. A script that seems to need a package is
a new dependency proposal first. **REQUIRED:** `managing-dependencies`.

- Run a script with `uv run --locked python scripts/<script>.py`, and give it a `just`
  recipe when a person or an agent runs it by hand.
- `scripts/check_staged.py` is the exception to that: pre-commit runs it with
  `language: python`, so ruff's `per-file-target-version` holds it to Python 3.10
  syntax. It inherits `GIT_*` from the hook on purpose, because `git commit -a` hands
  the hook a temporary index through `GIT_INDEX_FILE`.
- Enforced by: `tests/test_script_imports.py`, which checks repository and skill
  scripts against the stdlib shared by their floors (skills: 3.9; `check_staged.py`:
  3.10) and the project interpreter; other repository scripts use the project stdlib.
  All categories reject Windows-only modules and macOS-only `_scproxy` so the same
  script runs on macOS and Linux (CPython's platform module definitions,
  https://github.com/python/cpython/blob/3.14/PC/config.c and
  https://github.com/python/cpython/blob/3.14/Modules/Setup.stdlib.in,
  checked 2026-10-09). Supported interpreter builds are ordinary POSIX CPython
  with core and bundled extensions intact; external-library extensions may be
  absent, as on system Python. The static gate rejects those extensions and their
  dependent import paths (including `_gdbm`, `dbm.gnu`, `ssl`, `sqlite3`, `ctypes`,
  Tk and compression bindings). It permits bundled/pure-Python fallbacks such as
  `hashlib`, `decimal`, `uuid` and `dbm.dumb`; arbitrary stripped/custom builds are
  outside this contract. See Python's optional-build requirements and CPython's
  module definitions above, checked 2026-10-10:
  https://docs.python.org/3.14/using/configure.html#requirements-for-optional-modules.
  Known stdlib submodule gaps are checked against frozen CPython source trees
  for every supported minor (3.9 through 3.14 for skills; 3.10 through 3.14 for
  `check_staged.py`). Both dotted imports and `from package import submodule`
  are checked, including imports inside functions. Ordinary member imports
  (`from datetime import datetime`) stay allowed; general member/API compatibility
  and dynamic imports still need review. Source revisions and aliases are recorded
  in `tests/test_script_imports.py`, checked 2026-10-10.
  Absolute sibling imports are allowed. The backend's
  `banned-api` table does not reach `scripts/`.
- `scripts/**` is excused from ruff's `D1` and `T20`: a script is not a public API, and
  `print` is its output channel.

## Shape

What the scripts share, read from `scripts/*.py`:

- A module docstring that says what the script does and why, with the exact command
  that runs it — a `Usage:` block in `sync_agents.py`, `sync_labels.py`,
  `apply_ruleset.py`, and `check_staged.py`, which also lists its `Exit codes:`.
- A script that reads repository files defines
  `REPO_ROOT = Path(__file__).resolve().parents[1]` and builds its default paths from
  it, so it works from any working directory. `check_staged.py` has none: it reads the
  index through `git`.
- `main(argv: ... | None = None) -> int`, parsing with `argparse` and returning the exit
  code; `argv` is `list[str]`, or `Sequence[str]` in `check_staged.py`.
- A file a test must swap is a keyword parameter of `main` with the real path as its
  default — `apply_ruleset.main`'s `ruleset_file`, `sync_labels.main`'s `labels_file`,
  `sync_agents.main`'s `root` — so the test passes a `tmp_path` copy. Where a script has
  no such parameter, its test drives a real `git` repository under `tmp_path` instead.
- The file ends with an `if __name__ == "__main__":` guard that exits with `main()`'s
  return code, so importing it for a test runs nothing.
- Errors the script raises itself are its own exception classes
  (`RulesetFileError`, `SyncAgentsError`), caught in `main` and turned into a report.

## The stderr contract

`sync_agents.py`, `sync_labels.py`, and `apply_ruleset.py` follow this reporting
contract. `check_staged.py` uses a hook message read at commit time instead.
<!-- template-only -->
`bootstrap.py` uses one-shot error messages because it deletes itself after setup.
<!-- /template-only -->
The remaining shape and subprocess rules still apply to those exceptions.

A failure is read by an agent at least as often as by a person, so a report says what
failed, the path or value involved, what was expected, and the next safe command — and
never a secret or a matched credential. The shape, from `apply_ruleset.py`'s `_fail`
when `main.json` lacks its `rules` key (observed with `main([], ruleset_file=...)`,
2026-10-06; `<repo>` stands for the checkout's absolute path):

```
ERR_RULESET_FILE: <repo>/.github/rulesets/main.json: missing required keys: ['rules']
Expected: a JSON object with keys ['name', 'target', 'enforcement', 'conditions', 'rules']
Next: fix <repo>/.github/rulesets/main.json and rerun `just ruleset`
```

- The code is `ERR_<STAGE>_<KIND>`: the script's area, then the failure —
  `ERR_AGENTS_DRIFT`, `ERR_AGENTS_UNSUPPORTED_ENTRY`, `ERR_LABELS_FILE`,
  `ERR_LABELS_SYNC`, `ERR_LABELS_GH`, `ERR_RULESET_GH`. A refusal with its own remedy
  gets its own code rather than a shared one: `ERR_RULESET_PLAN_UNSUPPORTED` apart
  from `ERR_RULESET_GH`.
- Reports go to stderr; stdout is for the result a caller may parse.
- A code is a contract: a test asserts it on `capsys.readouterr().err`
  (`tests/test_sync_agents.py`), so renaming one is a change a caller notices.

## Subprocesses

`gh` and `git` run through `subprocess.run` with the fixed argv and justified `noqa`
`writing-python`'s "Security" asks for. A script checks the return code itself and
reports a failure through the contract above rather than letting `CalledProcessError`
print a traceback.

## A script that writes to GitHub

- Create or update only what its file declares; never delete what the file does not
  name. `sync_labels.py` leaves a label `.github/labels.yml` does not mention, and
  `apply_ruleset.py` never deletes a ruleset, so a repository-local addition survives.
- Running it against the live repository is a remote write, so it needs the sign-off
  AGENTS.md's "Security and human approval" describes; its recipe goes in the
  "Writes to GitHub" block of AGENTS.md's "Quick Reference", saying who may run it
  (`just ruleset` is an admin step no agent runs).
- Its tests never reach GitHub: they replace `subprocess.run` on the loaded module with
  a fake through `monkeypatch`, as `tests/test_apply_ruleset.py`'s `FakeGh` does, and
  assert the argv it was handed — including that no `DELETE` was ever issued.

## Tests

`scripts/` is not a package, so its test loads the file by path. Every
`tests/test_<script>.py` uses the same loader:

```python
def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sync_agents", REPO_ROOT / "scripts" / "sync_agents.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules while the class body runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
```

- Without the `sys.modules` line, a script that defines a dataclass fails to load.
- Drive `main([...])` with an argv list and a `tmp_path` file, and assert the exit code
  and the stderr report.
- A script that runs `git` is tested against a real repository under `tmp_path` with
  the user's and the system's git configuration switched off, as
  `tests/test_check_staged.py` does.
- Coverage measures `backend/src` only, so nothing forces these tests; write them anyway.
  **BACKGROUND:** `placing-tests`.

## Adding a script

A new file under `scripts/` is finished when every place that names it is, in the same
pull request:

1. Its test, `tests/test_<script>.py`, using the loader above.
2. A `just` recipe, when a person or an agent runs it by hand.
3. That recipe's line in AGENTS.md's "Quick Reference", in the block that says who may
   run it.
4. A row in AGENTS.md's "Validating a change" only when no row covers it; "A script
   under `scripts/`" already does.
5. When a gate runs it — `just verify`, a CI step, or a pre-commit hook —
   **REQUIRED:** `changing-gates`.
6. The module docstring above.
