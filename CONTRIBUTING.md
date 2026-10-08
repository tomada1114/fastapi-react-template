# Contributing

Thank you for considering a contribution! This document explains how to set up
your development environment and submit changes.

## Prerequisites

Install these tools:

- [Python 3.14+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.11.8 or later
  (`pyproject.toml`'s `required-version`; the relative `exclude-newer` and its lockfile form need it)
- [Just](https://just.systems/man/en/installation.html) (optional — you can run
  `uv run` commands directly)

Then install the dependencies and the git hooks (without Just, run the
`install` recipe's commands from the `justfile`):

```bash
just install
```

The hooks are required: they carry the secret gate that refuses a commit
staging a secret, and `just install` fails if one is missing (README's
"Development" section has the details).

## Development Workflow

```bash
# Format and auto-fix
just fmt

# Lint + type check
just lint

# Run tests
just test

# Mutating development check (format → lint → test)
just check

# Non-mutating PR/completion gate (its steps: AGENTS.md's Quick Reference)
just verify
```

**Without Just**, run the `uv run` commands the `justfile` gives each recipe
(`just verify` runs the recipes its own line in the `justfile` names).

## Worktrees

Install the Git hooks once in the primary checkout with `just install`. For a
manually managed issue worktree, provision it from the primary checkout under a
directory outside that checkout:

```bash
just worktree-setup 123 codex/123-short-description origin/main "$HOME/.local/state/linked-worktrees" 'just verify'
```

The existing `shipping-issues` provisioner creates the linked worktree, recreates its
`.venv` from `uv.lock`, checks the shared hook, and runs the requested baseline. It
never copies `.env*`, personal settings, or the primary checkout's `.venv`.

When Codex has already created a linked worktree, run `just worktree-prepare` from
that checkout to recreate its locked environment. This runs `uv sync` only; it does
not reinstall the shared hook. A fresh, independent checkout should use `just install`
instead.

Cleanup requires an explicit worktree root and branch. Preview first:

```bash
just worktree-clean "$HOME/.local/state/linked-worktrees" codex/123-short-description
```

Only after reviewing the paths, apply it with `just worktree-clean-apply` and the same
arguments. The cleaner delegates to the `shipping-issues` helper, which keeps a branch
unless its exact tip is the head of a merged PR, no PR is open for the branch, and the
worktree has no uncommitted changes. It does not delete remote branches or bypass those
checks. Applying cleanup also removes ignored files such as `.venv` and caches; copy
anything worth keeping before applying. For worktrees whose lifecycle is owned by
Codex itself and is not visible to `git worktree list`, use Codex's worktree controls
after checking the work is preserved.

## Pull Request Process

1. Fork the repository and create a branch from `main`
2. Make your changes
3. Apply formatting with `just fmt`, commit the result, then ensure `just verify` passes
4. Write or update tests for your changes
5. Open a pull request using the PR template

### Code Standards

- All public functions and methods must have type annotations
- mypy strict mode must pass
- Ruff must pass with no warnings
- Maintain or improve test coverage (minimum 80%)

### Commit Messages

Use Conventional Commits for both commits and PR titles:

```
<type>(<optional-scope>): <short summary>
```

Examples:

- `feat: add JSON export support`
- `fix(api): handle empty input`
- `docs: update installation guide`

The accepted types are declared in
[the PR title workflow](.github/workflows/check-pr-title.yml) under `types:`.

### Shipped Changes

Merged pull requests and closed issues record what has shipped. Use `git log`
for the local history and the repository's pull request and issue lists for context.

## Getting Help

If something is unclear, open an issue or start a discussion. We're happy to
help you get started.
