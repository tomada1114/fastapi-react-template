# The bootstrap

The detail behind `starting-an-app`'s rename step: what `scripts/bootstrap.py` takes,
what it refuses, what it changes and removes, and how it is proven. This page exists
only in the template: the bootstrap deletes it from both skill trees unless
`--keep-bootstrap` is passed.

## Why a script, and why it runs once

Renaming an app by hand misses a site, and a careless global replace hits text that
merely explains the template. So the script replaces a fixed set of placeholders across
the tracked files, edits a short list of known sites (the contact slots, the copyright
line, the package metadata) that must each still be found exactly once, removes
everything marked as the template's own, and then deletes itself. A second run is
refused: `.template-origin` exists from the first one.

## Running it

From the root of a fresh clone, after `just install` and `git switch -c chore/bootstrap`:

```bash
uv run --locked python scripts/bootstrap.py todo-api \
  --author "Jane Doe" --github-user jdoe --github-repository jdoe/todo-api \
  --description "Todo API" --contact-url https://github.com/jdoe
```

| Flag | Required | Replaces | Rules |
|---|---|---|---|
| `name` (positional) | yes | `my-app` (distribution, README text), `my_app` (the package, renamed `src/my_app` → `src/todo_api`), `MY_APP_` (the settings' environment prefix, `TODO_API_`) | lower-case letters and digits in words joined by single hyphens, starting with a letter, at most 40 characters |
| `--author` | yes | `Your Name` in `pyproject.toml` (TOML-quoted) and `LICENSE` | one line, at most 100 characters |
| `--description` | yes | the two "A short description …" sentences (`pyproject.toml`, README) | one line, at most 200 characters |
| `--github-user` | yes | the owner in `your-username/fastapi-react-template` | a GitHub user or organization name |
| `--github-repository` | no | the repository in `your-username/fastapi-react-template` | `NAME` or `OWNER/NAME`; the owner must equal `--github-user`; defaults to the slug |
| `--display-name` | no | `My App` (README's title, the API's OpenAPI title, the devcontainer) | one line, at most 60 characters; defaults to the slug |
| `--contact-url` | no | the contact sentences in `SECURITY.md` and `CODE_OF_CONDUCT.md` | a public `https://` URL without credentials, such as a profile page |
| `--keep-bootstrap` | no | — | keeps `TEMPLATE.md`, the script, its test, and this page, untouched, for debugging; the kept test exercises the template, so `just verify` fails until they are deleted |

Without `--contact-url`, the contact sentences keep pointing at the repository itself:
`SECURITY.md`'s fallback route at the issue tracker (ask for a private contact, give no
detail), and `CODE_OF_CONDUCT.md`'s reports at the private vulnerability reporting form.
Private vulnerability reporting works only on a public repository
([github-settings.md](github-settings.md)), so on a private one pass
`--contact-url` or follow [private-repository.md](private-repository.md).

There is no `--email`, and argparse rejects one (exit 2, see below): an app cut from the template is
usually public, and its files are where people look for a contact, so no email address
is ever written. A value that looks like one is refused.

## What it refuses

An argument argparse cannot parse — a missing required flag, an unknown one such as
`--email` — exits 2 with the usage line and argparse's own message. Every refusal of
the script's own exits 1 with one `error:` line. Neither writes anything:

- a current directory outside the checkout the script lives in (run from another
  repository, the rename would land somewhere else);
- not the root of a git work tree, or a work tree with any uncommitted or untracked
  change (`git status --porcelain --untracked-files=all` must be empty);
- `.template-origin` already present: the repository was bootstrapped;
- a reserved name, checked in both the hyphenated and the underscored form: `app`,
  `src`, `test`, `tests`, `core`, `api`, `cli`, `adapters`, `settings`, `my-app`,
  `my_app`; a package the app or its tooling imports (`fastapi`, `typer`, `pydantic`,
  `pydantic_settings`, `uvicorn`, `httpx`, `httpx2`, `starlette`, `pytest`, `ruff`, `mypy`),
  which the app's own module would shadow; every `scripts/*.py` stem; any Python
  keyword; and any standard-library module (`sys.stdlib_module_names`);
- a value containing a placeholder token (`my-app`, `my_app`, `fastapi-react-template`,
  `your-username`, `you@example.com`, any case), or equal to a placeholder phrase
  (`My App`, `Your Name`, any case), which the leftover scan would report. A value that
  only contains such a phrase inside other words ("Sync my apps") is fine;
- `src/my_app` missing or the destination package already present;
- a site that no longer has the shape the script expects: a contact sentence, the
  copyright line, the metadata lines, or a template-only block left open or closed
  twice. The template changed; fix the script's site list, not the file.

## What it does

1. Validates every value, then the repository's state.
2. Computes every file's new content in memory: removes each template-only block (a
   line holding only `<!-- template-only -->`, through the line holding only
   `<!-- /template-only -->`; in YAML, TOML, or a shell file the marker sits behind
   `#`), edits the known sites, and replaces the placeholders in one pass, so a new
   value is never rewritten again. `uv.lock`, the files it is about to delete, and
   secret-shaped paths are left alone.
3. Writes, the step most likely to fail first and itself last: renames `src/my_app`,
   writes the edited files, writes `.template-origin`, then deletes `TEMPLATE.md`,
   `tests/test_bootstrap.py`, this page in both skill trees, and `scripts/bootstrap.py`
   (none of them with `--keep-bootstrap`). On top of the placeholders,
   `LICENSE` gets the run's year and the author. `pyproject.toml`'s `exclude-newer`
   is a relative `"14 days"` and is left as it is.
   CI's `Template Bootstrap Smoke` job sits in a template-only block, so it goes too.
   If a write fails part-way, it exits 1 with an `error:` line naming the steps already
   done; see "A failed write" below.
4. Runs `uv lock` (the lock still names the template's package), then
   `ruff check --fix` and `ruff format` (a longer module name can push imports past the
   line length). A failure here exits 1 after the write: run the failed command and
   the ones after it by hand.

`.template-origin` records the template's repository, the template commit, and the
tree. Keep it committed: the bootstrap's second-run refusal and
`tests/test_product_section.py` both read it. The commit is known only when the
clone's history starts at the template's first commit. GitHub's "Use this template"
starts the new repository with a single commit
(https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template,
checked 2026-10-06), so there it reads `unknown`, and the file says how to find the
commit by its tree.

## A failed write

The work tree was required clean before the run, so git holds the whole template.
From the repository root:

```bash
git restore --staged --worktree :/ && git clean -fd
```

This discards the partial rewrite — every edited, renamed, and new file — and restores
the template, ready for a second run once the cause is fixed. `git clean -fd` leaves
ignored files alone, so if `src/<module>/` survives holding only caches such as
`__pycache__/`, delete that directory too before running again.

## How it is proven

- `tests/test_bootstrap.py` runs the script on a git clone of the working tree in a
  temporary directory, so an edit is tested before it is committed: every requirement
  above has a test, including that each refusal leaves the tree byte-identical.
- CI's `Template Bootstrap Smoke` job clones the commit under test, bootstraps it with
  the sample values above, fails on any placeholder left in the tracked or new files
  (`git grep` over everything but `.template-origin`, which names the template on
  purpose: the tokens in any case, and `My App` and `Your Name` as whole words), checks
  that `tests/test_product_section.py` fails on the unfilled Product section for that
  reason, fills that section, and runs `just verify` there. It is not a required
  check, because an app no longer has it.

A change to the script, to a placeholder, or to a file it edits is proven by
`uv run --locked pytest tests/test_bootstrap.py` locally and that job on the pull
request.

## A placeholder survived

The placeholder vocabulary lives in `scripts/bootstrap.py`'s `FORBIDDEN_TOKENS`,
`FORBIDDEN_PHRASES`, and `PLACEHOLDER_DESCRIPTIONS`. Search for those spellings with
case-insensitive matching, excluding `.template-origin`. The bootstrap tests derive
their scans from those constants and check CI's smoke patterns and deletion list
against them, so a vocabulary change cannot silently leave CI behind.

A hit is a spelling the placeholder list does not cover (a different case, a joined
form) or text that should have been template-only. Fix it by hand in the app, and fix
the template — the placeholder list or a template-only block — so the next app does
not inherit it.
