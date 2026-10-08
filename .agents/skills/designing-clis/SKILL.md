---
name: designing-clis
description: >
  Covers the Typer entry point in src/my_app/cli/: the my-app root app in main.py, one
  Typer group per resource, the shared lazy get_container accessor that caches services
  on ctx.obj, commands wrapped in exit_on_domain_error, stdout for results and stderr for
  errors, one-line command docstrings, the deferred FastAPI and uvicorn imports in
  serve.py, and CliRunner tests passing obj=. Use when adding or changing a command, an
  argument or option, or command output, or when removing the CLI. The skill is deleted
  along with src/my_app/cli/.
---

# Designing CLIs

**Owns:** everything under `src/my_app/cli/` and `tests/cli/` — the command tree, how a
command gets its services and settings, what it prints where, and how it is tested.
**Does not own:** the exit-code table and what maps to each code (`designing-errors`);
the service a command calls (`designing-core-logic`); running the installed `my-app`
by hand (`running-the-app`); module-level Python style (`writing-python`).

## A project without the CLI

This skill describes the command-line entry point only. Dropping the CLI is a deletion,
never a core change:

- delete `src/my_app/cli/` and `tests/cli/`, and `[project.scripts]` in
  `pyproject.toml`;
- remove the `typer` runtime dependency, then run `uv lock`. Keep `uvicorn`: `just dev`
  serves the API with it;
- remove the `just run` recipe and the lines that name it (README's Development block,
  AGENTS.md's Quick Reference; `just check-harness` fails while one remains), and in
  `pyproject.toml`'s ruff config the `typer.*` entries and the `src/my_app/cli/**`
  per-file-ignore;
- update AGENTS.md's Overview and Architecture tree and bullets to describe only
  the API; in the paragraph after Quick Reference, replace `my-app serve` with
  a direct `uvicorn ... --factory` invocation on a free port while preserving
  the rule that the developer's server is human-run;
- update README: remove Quickstart's CLI examples and column, the exit-code
  table, and Configuration's `my-app todo` invocation guidance; rewrite
  Architecture for the remaining API and remove the pointer to this deleted
  skill; keep the API examples using `just dev`;
- replace the CLI reproduction command in `.github/ISSUE_TEMPLATE/bug_report.yml`
  with an HTTP request example;
- delete `.agents/skills/designing-clis/`, remove its row from AGENTS.md's Skills
  table, and run `just agents-sync`.

Then prune what sibling skills say about the CLI:

- `designing-errors`: "The CLI mapping", step 5 of "Adding a failure mode", and the
  CLI half of "Two kinds of failure" and "Configuration errors";
- `designing-core-logic`: the `designing-clis` pointer in "Adding a use case";
- `running-the-app`: "Running the CLI" and the CLI tier of "Evidence, cheapest first";
  its server script switches to the `uvicorn ... --factory` command it names;
- `writing-python`: the examples that quote `cli/` files;
- `writing-tests`, `tdd`, and `updating-docs`: their mentions of `CliRunner`, a
  command, or an exit code.

## The command tree

- `cli/main.py` holds the root `app = typer.Typer(help=..., no_args_is_help=True)`, the
  `my-app` console script (`[project.scripts]` in `pyproject.toml`). It registers each
  group with `app.add_typer(<module>.app, name=...)` and `serve` with
  `app.command()(serve)`, and holds nothing else.
- Each group is its own module with its own `typer.Typer(help=..., no_args_is_help=True)`,
  so `my-app <group>` with no subcommand prints help rather than doing something.
- A command never shadows a builtin: it is registered by name over a descriptive
  function (`writing-python` owns the rule).

## Services come from a shared lazy accessor

Commands call `get_container(ctx)` from `cli/context.py` when they need services.
The accessor reuses the nearest supplied `ctx.obj`, including a caller's `obj=` through
`CliRunner.invoke`. With none supplied, it builds through `build_container(load_settings())`
and caches on the invocation's root context, so sibling commands share one container.
It registers the built container's `close()` with the root's `call_on_close`, including
when a command fails. A supplied `obj=` stays caller-owned and is never closed by the
CLI.
Groups do not build services in a callback: subcommand `--help` must work without
reading settings or creating a database, even under invalid configuration.

A command never calls `build_container` or constructs an adapter itself, and never
builds `Settings()` directly: `load_settings()` is what turns an invalid `MY_APP_*`
variable into exit 3 and one line instead of a traceback.

Excerpts in this skill drop comments, docstrings, and enclosing code where marked; the
real code keeps its docstrings, because ruff's `D` rules require them.

## A command's shape

- Parameters are `Annotated[T, typer.Argument(...)]` or `typer.Option(...)` with a
  `help=`, and a `metavar=` where the parameter name reads badly in usage text
  (`metavar="ID"`). A typed parameter (`int`) gives Typer's own usage error, exit 2,
  for a malformed value. Defaults are named module constants.
- The docstring is one plain-text line (`writing-python` owns the rule and its
  reason).
- The service call that can raise an `AppError` sits inside
  `with exit_on_domain_error():`, and the output is printed after the block, so the
  wrapper maps only the domain failure. A command whose service cannot raise one (a
  listing) needs no wrapper.

```python
@app.command("complete")
def complete_todo(
    ctx: typer.Context,
    todo_id: Annotated[int, typer.Argument(metavar="ID", help="The to-do's id.")],
) -> None:
    """Mark a to-do as completed."""
    with exit_on_domain_error():
        todo = get_container(ctx).todos.complete(todo_id)
    typer.echo(f"Completed {_describe(todo)}")
```

## Output, errors, and logging

- **Results go to stdout through `typer.echo`,** one line per item in a stable format a
  script can split, rendered by one helper (`_describe` prints `3 [x] buy milk`) with
  its markers as named constants. An empty result says so in words ("No to-dos yet.")
  rather than printing nothing. `print` fails lint (`T20`).
- **A domain or configuration failure goes to stderr as one line** (exit 1 or 3), and
  only through the two helpers in `cli/errors.py` — `exit_on_domain_error()` and
  `load_settings()` — so the `Error: ` prefix and the exit code stay uniform. A command
  never echoes an error itself and never raises `typer.Exit` with a bare integer: it
  uses an `ExitCode` member. The codes are `designing-errors`'.
- **A usage error (exit 2) is Typer's own output,** several lines on stderr — the usage
  line, a `--help` hint, and a boxed message (observed with typer 0.27.0, 2026-10-06).
  A command does not try to reshape it.
- **No logging and no progress chatter on stdout.** No module under `cli/` logs.

## Each invocation is its own process

A real run builds a fresh container, so with `MY_APP_DATABASE_URL` unset the in-memory
store forgets everything when the command exits; the README's Configuration note says
so to users. Tests reproduce one long-lived process by passing the same container as
`obj=` to every invocation.

## `serve` and imports

`cli/serve.py` is the CLI's only bridge to the API, a module of its own so that dropping
the API means deleting it and its registration line in `cli/main.py`. It imports
uvicorn and `create_app` inside the command, each with a `noqa: PLC0415` that says why,
so `my-app <group> ...` never loads the server stack;
`tests/cli/test_serve.py::test_cli_import_does_not_load_the_server_stack` proves it in
a fresh interpreter. No other CLI module imports `my_app.api`, and a future command
that needs a heavy optional stack defers its import the same way. `serve` binds
`127.0.0.1` unless `--host` says otherwise, and its default port is the developer's
(`running-the-app`).

## Adding a command

1. The service method it calls exists first, with its tests. **REQUIRED:**
   `designing-core-logic`.
2. The command goes in its group's module in the shape above; a new group is a new
   module with its own `app`, registered in `cli/main.py`.
3. Test it (below): the happy path with exact stdout, each domain error with
   `ExitCode.DOMAIN_ERROR`, and a malformed argument with `ExitCode.USAGE_ERROR`.
4. Add it to the README's CLI/HTTP table.

## Testing a command

- Drive the app in-process with `typer.testing.CliRunner` and `obj=` a container from
  the `make_container` fixture, never by spawning `my-app`. `tests/cli/test_todo.py`'s
  `run` fixture wraps that, sharing one container across calls:

  ```python
  # ... fixture header and docstring elided
  runner = CliRunner()
  container = make_container()


  def _run(*args: str) -> Result:
      return runner.invoke(app, list(args), obj=container)
  ```

- Assert `result.exit_code` against an `ExitCode` member, `result.stdout` exactly, and
  `result.stderr` for the error line; a failure also asserts `stdout == ""`.
- A test omits `obj=` when what it checks happens before, or instead of, the lazy
  container: reading settings from the environment
  (`test_todo_without_supplied_container_reads_settings_from_env` in
  `tests/cli/test_todo.py`, the config-error test in `tests/cli/test_errors.py`) and
  every test in `tests/cli/test_serve.py`, because `serve` builds its app from
  `load_settings()`, not from `ctx.obj`. Such a test sets the `MY_APP_*` variables it
  needs with `monkeypatch`, pointing a database at a `tmp_path` file.
- `serve` is tested with `uvicorn.run` replaced by a recording fake (`serve_calls` in
  `tests/cli/test_serve.py`); a test never binds a port.
- Run `uv run --locked pytest tests/cli/`.
