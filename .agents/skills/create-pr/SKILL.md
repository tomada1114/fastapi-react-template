---
name: create-pr
description: >
  Use when opening or updating a pull request by hand, outside shipping-issues: asked to
  "open a PR", "create a pull request", "push this and make a PR", or to refresh the
  title or body of the PR already open for the current branch. Covers the preconditions
  (not on main, a clean tree, one PR per branch), running just verify first, a
  Conventional Commits title check-pr-title.yml accepts, filling
  .github/PULL_REQUEST_TEMPLATE.md's Summary, Test Plan, and Checklist honestly, and
  git push, gh pr create, and gh pr edit.
---

# Create PR

**Owns:** opening a pull request for the current branch, or updating the one already
open for it — the preconditions, the gate run before it, the title, the body, and the
push. **Does not own:** shipping an issue end to end through CI and merge
(`shipping-issues`); landing a Dependabot PR (`merging-dependency-prs`); making the
commits the PR carries (`smart-commit`).

**Invoking this skill is the sign-off for exactly the remote writes AGENTS.md's
"Standing exceptions" lists for it, for this invocation only:** pushing the current
branch to `origin`, `gh pr create` for it, and `gh pr edit` on its own open pull
request. Nothing else — no force-push, no merge, no label, no comment, no other branch.
A step that would need one of those stops and asks.

Every step below ends in either the next step or a stop. A stop is reported with what
was found and what would clear it; it never becomes a PR with the problem left in it.

## Codex execution surface

In Codex, use GitHub MCP exclusively for remote PR reads and writes. The `gh`
examples below apply to Claude Code only; do not run them or live-GitHub helper
scripts in Codex. Local Git still owns fetch, status, commit and push. Discover MCP
schemas to list this branch's PR, read its existing body, and create/update it with
structured title/body text. Preserve human edits and verify returned head/base and
PR state. If MCP lacks a required capability, report it without a CLI or direct
HTTP fallback. The same checks and write authorization apply on both hosts.

## 1. Preconditions

Gather the state before running anything:

```bash
git branch --show-current
git status --short
git fetch origin main
git log --oneline origin/main..HEAD
gh pr list --head <branch> --state open --json number,url,title
```

- **On `main`, or detached:** stop. A PR needs a branch of its own, and creating one is
  the requester's call.
- **Uncommitted or untracked changes:** stop. The PR would carry only what is committed,
  so the gate would judge a tree the reviewer never sees. Commit first with
  `smart-commit` — a commit needs its own sign-off, the request that invokes that skill,
  which this skill does not grant — then start again.
- **No commits ahead of `main`:** stop; there is nothing to propose.
- **A PR already open for the branch:** update it in step 6 with `gh pr edit`. Never
  open a second PR for the same branch — the first one's review and CI history would be
  stranded on a duplicate.

## 2. The gate

Run `just verify`, the non-mutating gate whose steps AGENTS.md's Quick Reference lists
(`just --show verify` prints the recipe). It never rewrites a file, so a pass proves the
*committed* tree is green — `just check` runs `fmt` first and proves nothing about what
was committed.

- **Any failure stops the PR.** Fix it on the branch, or report it. A formatting failure
  is fixed with `just fmt`; committing that fix needs the sign-off step 1 names (this
  skill never commits), then the gate runs again. Never weaken a gate to make the run
  pass (AGENTS.md's "Security and human approval").
- **Then `git status --short` again.** Anything that changed means the branch differs
  from what was just judged: commit it (with the sign-off step 1 names) and run the gate
  again.

`just verify` runs neither typos nor zizmor. Also run the narrowest check for what the
branch touches from AGENTS.md's "Validating a change" when the gate does not already run
it — `uv run --locked pre-commit run typos --files <file>` for prose,
`uv run --locked pre-commit run zizmor --all-files` for a workflow. The Test Plan names
each command.

## 3. Read the diff for what the gates cannot judge

```bash
git diff origin/main...HEAD --stat
git diff origin/main...HEAD
```

Each row feeds a checklist item or the Summary:

| In the diff | Then |
|---|---|
| A new package in `pyproject.toml` | Stop unless the owner already signed off on that package; then put the review record in the body. **BACKGROUND:** `managing-dependencies`. |
| A weakened gate (`changing-gates`' list: a removed ruff rule, a `noqa` without a reason, a skipped test, …) | Stop. The PR waits until a human decides; it is not opened with the problem in it. |
| New behavior without a test that covers it | Stop and add the test. **REQUIRED:** `tdd`. |
| A new public function without type annotations or a docstring that says why | Add them. **BACKGROUND:** `writing-python`. |
| A route, status, or `MY_APP_*` setting a user observes changed | The relevant README text changes on this branch. **REQUIRED:** `updating-docs` decides what is owed. |
| A removed or changed public behavior | A breaking change: call it out in the Summary, in one line a user can act on, and mark the title with `!`. |
| A decision that owes an ADR | The ADR is on this branch. **REQUIRED:** `recording-architecture-decisions` decides whether one is owed. |

A row that does not apply holds trivially; say so in the body rather than leaving the
reader to guess ("No new dependency").

## 4. Title

`<type>(<scope>)<!>: <summary>`, under 72 characters, in English. The title becomes the
squash-merge commit subject, `.github/workflows/check-pr-title.yml` validates it as a
Conventional Commit, and `.github/workflows/pr-label.yml` derives the PR's label from
its type, so the type is not decoration.

- Choose a type from the explicit `types:` input in
  `.github/workflows/check-pr-title.yml`, the canonical accepted-type list, and
  verify that `.github/workflows/pr-label.yml` maps it to a label.
- The scope is the area the change lives in, matching recent history: `skills`,
  `hooks`, `github`, `deps`, `bootstrap`, or a layer (`core`, `api`, `cli`).
- The summary is imperative and lower-case, with no trailing period, and says what the
  change does, not which files it touches.
- For a branch whose commits mix types, take the most significant one: `feat` over `fix`
  over the rest.

## 5. Body

Fill `.github/PULL_REQUEST_TEMPLATE.md` in its own order, keeping its headings, and
write it to a file outside the checkout — the scratch or temp directory your host
provides — so it never shows up as an untracked file in the tree the gate judged.

- **Summary.** One to three lines: what the change does and why, then any breaking
  change, dependency, or ADR line step 3 called for. Then `Closes #N` on its own line
  when the branch resolves an issue; a bare `#N` closes nothing. Ask rather than guess
  when it is unclear which issue the branch closes.
- **Test Plan.** The commands actually run, each with its verdict line —
  `just verify` → passed, `N passed`. Never a command that was not run, and never a raw
  log.
- **Checklist.** Tick an item only when step 2 or step 3 showed it holds. An item that
  cannot be ticked is a stop: report which one and why, and open nothing. A box ticked
  on trust is the one defect in this PR a reviewer cannot see.

## 6. Create or update

```bash
git push -u origin <branch>
gh pr create --base main --head <branch> --title "<title>" --body-file <body-file>
```

For a branch that already has an open PR, push, then update that PR instead:

```bash
gh pr view <number> --json title,body
gh pr edit <number> --title "<title>" --body-file <body-file>
```

Read the current body first and carry over anything a human added to it — `gh pr edit`
replaces the body whole.

- A push rejected as non-fast-forward stops: the remote branch has commits this checkout
  does not. Never force-push to get past it.
- `--body-file`, never an inline `--body` built from a heredoc or command substitution —
  backticks and `$` in a body are expanded by the shell before `gh` sees them.
- Run no `--web` flag or anything else that opens a browser; print the PR's URL instead.

Report the URL, the title, and every checklist item as it was ticked. The PR is then the
requester's: watching CI and merging are not this skill's.
