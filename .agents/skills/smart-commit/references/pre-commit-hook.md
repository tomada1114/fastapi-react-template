# The pre-commit hooks

Read when `git commit` fails, or before committing a partially staged file. The hooks
and their options are `.pre-commit-config.yaml`'s; read them there. This file holds
only what each refusal means and how to clear it without switching the hook off.
**BACKGROUND:** `changing-gates` for why the layer is shaped this way.

## How the hooks run

- pre-commit sets aside unstaged edits to tracked files while the hooks run, so a hook
  that reads files sees what is staged. An untracked file is not set aside: `mypy` and
  `mypy-backend`, which check whole trees rather than the staged files, can still fail
  on one.
- Some hooks **rewrite** files: `trailing-whitespace`, `end-of-file-fixer`,
  `ruff --fix`, and `ruff-format`. When they change anything the commit fails, and
  their rewrites are left in the working tree, unstaged. Inspect them with `git diff`,
  re-stage the files by name, and commit again.
- One failure aborts the commit, but every hook still runs; read the whole output,
  since more than one can fail at once.
- `agents-check` runs only when a path under `.agents/skills/` or `.claude/skills/` is
  staged; `mypy` only when a Python file is, and `mypy-backend` only when one under
  `backend/` is.

## When the hooks run

- The hooks run on `git commit`, including the commit that concludes a conflicted
  merge — there pre-commit hands the file-based hooks only the merge's conflicted and
  hand-changed files (observed in pre-commit 4.6.0's `git.get_conflicted_files`,
  2026-10-06), while `check-staged` reads the whole index itself. Only `check-staged`
  runs on a clean merge, through git's `pre-merge-commit` hook.
- Some commits git makes itself run no hook at all — `changing-gates`'
  `references/pre-commit-layer.md` lists them. `git rebase --continue` is one, so
  commit a rebase resolution with `git commit` first, so the hooks judge it.

## Recovery, one row per hook

| Hook | What the failure means | Clear it by |
|---|---|---|
| `trailing-whitespace`, `end-of-file-fixer` | It fixed the file. | Re-stage the file and commit again. |
| `ruff` | A lint violation `--fix` could not fix, or one it did fix (the file changed). | Fix the code by hand where it reports; re-stage. Never a bare `noqa` and never a relaxed rule — a `noqa` carries a written reason (`writing-python`). |
| `ruff-format` | It reformatted the file. With a partially staged file whose unstaged hunk overlaps a reformatted line, pre-commit prints "Stashed changes conflicted with hook auto-fixes... Rolling back fixes..." and discards the fixes, keeping your unstaged edits. | Re-stage the file. On an overlap: stage the whole file, or run `uv run --locked ruff format <file>` first and stage the hunks again. |
| `mypy`, `mypy-backend` | A whole tree failed to type-check, not only the staged files: the root's `scripts`, `tests`, and skill scripts (`mypy`), or `backend/src` and `backend/tests` (`mypy-backend`, run from `backend/`); the error can sit in a file this commit does not touch, or in an untracked one. | Fix the type where it is. When the error lives in a change that belongs to a later group, set it aside (`git stash push --keep-index --include-untracked`), commit, and `git stash pop`. Never a `# type: ignore` without its code and a reason. |
| `typos` | A misspelling in a staged file. | Fix the word. Add a genuine technical term to `typos.toml`'s `default.extend-words`, never a real misspelling. |
| `zizmor` | A workflow under `.github/workflows/` breaks a security rule. | Fix the workflow (`changing-gates`' "CI workflows and required checks"). |
| `check-yaml`, `check-toml`, `check-json` | The file does not parse. | Fix the syntax. |
| `check-merge-conflict` | A conflict marker is still in a staged file. | Finish resolving it. |
| `check-added-large-files` | A staged file is over 500 KB. | Leave it out; it is almost always an artifact. |
| `check-case-conflict`, `check-symlinks` | Two paths differ only in case, or a symlink points nowhere. | Rename the path, or fix or drop the link. |
| `no-commit-to-branch` | The current branch is `main`. | Create a branch and commit there; the commit never belongs on `main`. |
| `check-staged` | A staged path or staged content looks like a secret; the output names the path and the kind, never the value. `ERR_STAGED_ALLOWLIST_*`: `.check-staged-allow` is malformed, too broad, or stale. | `git restore --staged <path>`, then tell the requester which path was refused and why — without opening it. A refusal you believe is wrong is a stop for a human to judge. `ERR_STAGED_ALLOWLIST_*`: the one edit you may make is removing the named entry when this same change deleted or renamed its file, which narrows the exemption. Adding an entry, widening one, re-pointing its path, or re-pinning a content blob id is a human's decision: stop and report the `ERR_` line. |
| `agents-check` | `ERR_AGENTS_DRIFT`: `.claude/skills/` is not a byte-for-byte copy of `.agents/skills/`. | Make the edit under `.agents/skills/` (an edit made only under `.claude/skills/` is lost at the next sync, so move it first), run `just agents-sync`, and stage both trees. **BACKGROUND:** `authoring-skills`. |

After the fix, run the same `git commit` again. Every hook runs again, so a fix for one
row can surface another.

## What never clears a refusal

`git commit --no-verify` or `-n`, `SKIP=<hook id>` or any other switch that turns a
hook off, an edit to `.pre-commit-config.yaml` or `.git/hooks/`, and a rebase or
cherry-pick used to commit past the hooks. Each removes the check rather than the
problem, and `--no-verify` takes the secret gate down with everything else. A refusal
that cannot be cleared is reported with the failing hook's output, and the commit waits
for a human.
