# The pre-commit layer

Read before editing `.pre-commit-config.yaml` or `scripts/check_staged.py`, or when a
commit, a merge, or `just install` behaves unexpectedly around the hooks. The hook list
itself is `.pre-commit-config.yaml`'s; read it there.

The guard rails run as git hooks through [pre-commit](https://pre-commit.com/), so they
hold for every author — a human, Claude Code, Codex CLI, or any other tool. No
agent-specific hook is committed.

## `shellcheck`

The `shellcheck` hook (`shellcheck-py`, pinned by `rev:` and kept current by
Dependabot's `pre-commit` entry) lints every shell script at default severity, style
included. It excludes `^\.claude/skills/`, the byte-identical mirror of
`.agents/skills/`. It installs shellcheck in pre-commit's own environment, so it adds
nothing to `pyproject.toml` or `uv.lock`. CI's `Lint & Type Check` runs it with
`uv run --locked pre-commit run shellcheck --all-files`.

## `check-staged`, the secret gate

`check-staged` (`scripts/check_staged.py`) refuses a commit that stages a secret-shaped
path or secret-shaped content. Its module docstring and constants are the list; in
summary:

- **Paths:** `.env` and `.env.*`, `.envrc` and `.envrc.*`, except names ending
  `.example`, `.sample`, or `.template`; anything under `secrets/`; `*.pem`, `*.key`,
  `id_rsa*`; `.claude/settings.local.json` at any depth; `.codex/rules/local.rules`.
- **Content:** an AWS access key; a GitHub, Anthropic, OpenAI project, OpenRouter,
  Slack, or Stripe live token; a PEM private-key header.
- It judges the index, not the working tree, so a partially staged file is judged as it
  will be committed. It names the file and the kind of secret and never prints the
  matched value.
- It is stdlib-only and runs with pre-commit's own interpreter (`language: python`), so
  it needs no uv; ruff holds it to Python 3.10 syntax for that reason.
- A staged deletion is never inspected: removing a file cannot add a secret.

### Exempting a legitimate file

A file the gate refuses that holds no secret — a public CA certificate, a Keynote
`.key`, `docs/id_rsa-rotation.md`, a test fixture with a fake token — gets through by
an entry in `.check-staged-allow` at the repository root, and by nothing else: no hook
`args:`, no environment variable, no inline marker, and `exclude:` cannot narrow a hook
that takes no filenames. The template ships no `.check-staged-allow`; without one,
nothing is exempt.

**An entry is a gate loosening a human decides,** reviewed in the pull request like any
other change to a gate — never something an agent adds or widens to get its own commit
through. The one edit an agent may make on its own is removing an entry whose file
its own change deleted or renamed, which narrows the exemption; adding, widening,
re-pointing, or re-pinning an entry is the human's.

```text
# Public root CA for the staging TLS proxy; holds no private key.
path deploy/certs/staging-ca.pem

# Fake AWS key the parser tests feed in; the file is a fixture, not config.
path tests/fixtures/secrets/aws.txt
content tests/fixtures/secrets/aws.txt 3b18e512dba79e4c8300dd08aeb37f8e728b8dad
```

- **Two kinds of entry, each exact.** `path <file>` lets that one file past the path
  rules; its content is still scanned. `content <file> <blob id>` lets that one staged
  content of the file past the credential patterns. A file both refuse needs one of
  each. `<file>` is the path from the repository root, unquoted, as
  `git -c core.quotePath=false ls-files --full-name` prints it, with `/`; a glob (`*`,
  `?`), a directory, `.`, an absolute path, or a `..` segment is refused.
- **Every entry sits below a `#` reason comment** with text after the `#`, and no blank
  line between them; consecutive entries share the comment above them. CRLF endings and
  a BOM are fine. Lines split on `\n` alone, and a line holding any other control or
  line-separator character (a form feed, U+2028, a lone `\r`; a tab is fine) is refused,
  so the file parses into exactly the lines a reviewer reads in the diff.
- **It is read from the index** the commit is made from, never the working tree: an
  entry counts only once it is staged, and a `git commit -- <path>` that leaves out a
  staged allowlist edit does not get that edit's exemption.
- **The blob id** is `git rev-parse :<file>` after `git add <file>`. Any edit changes
  it, so edited content is judged again.
- **A stale entry fails the commit** until it is removed or corrected in the same commit:
  a file deleted or renamed, a blob id that is not the staged one, a `path` entry no
  rule needs, a `content` entry whose content matches no pattern or names a submodule.
- **The allowlist is judged like any file**, so a token pasted into a reason comment is
  refused.
- **The weekly gitleaks history scan does not read it**: gitleaks has its own
  exemptions (a root `.gitleaksignore`, which the template does not ship).

Every allowlist error exits 3, and its report names the line and the problem without
quoting the line, then an `Expected:` and a `Next:` line:

| Code | Raised when |
|---|---|
| `ERR_STAGED_ALLOWLIST_FILE` | The staged `.check-staged-allow` is a symlink, a submodule, a directory, or not UTF-8. |
| `ERR_STAGED_ALLOWLIST_SYNTAX` | An unknown keyword or an indented entry, a missing path or blob id, a malformed blob id or path, an entry with no reason comment or one with no text, a control or line-separator character, or a duplicate. |
| `ERR_STAGED_ALLOWLIST_TOO_BROAD` | A glob, a trailing `/`, `.`, or a path that names a directory in the index. |
| `ERR_STAGED_ALLOWLIST_STALE` | An entry the index no longer matches, as above. |

FILE, SYNTAX, and TOO_BROAD stop the gate before it judges anything, so `path *` cannot
exempt everything. STALE is printed next to the usual refusals, so both can be fixed in
one pass.

## When the hooks run, and when they do not

- `check-staged` runs on every `git commit`, including the one that concludes a
  conflicted merge, and on clean merges through git's `pre-merge-commit` hook. In a
  merge, content identical to what the merged-in branch already has at the same path is
  not judged again; conflict resolutions and other new content are. It is the only hook
  at `pre-merge-commit`; every other hook runs on `git commit` only.
- Commits that git makes itself run no pre-commit hook at all: the commits `git rebase`
  replays (including after `git rebase --continue`), `git cherry-pick`, and
  `git revert`. The backstop for those is the weekly full-history gitleaks scan in
  `.github/workflows/security-audit.yml`.

## Installing the hooks

- `just install` installs the git hooks and fails when any type listed in
  `default_install_hook_types` (a one-line `[a, b]` list) is missing afterwards;
  `tests/test_just_install.py` runs the recipe body against a fake `uv`.
  With `ALLOW_MISSING_GIT_HOOKS=1` or `CI=true` it still attempts the install, but a
  failed install or a missing hook is only a warning. Outside a Git repository it skips
  the hooks.
- A checkout installed before the `pre-merge-commit` hook existed has only the
  `pre-commit` hook: re-run `just install` to add it.
- Git hooks live in the main checkout's `.git/hooks/` and are shared by every linked
  worktree. Run `just install` from the main checkout: run from a worktree, it points
  the shared hooks at that worktree's `.venv`.

## What replaced the agent hooks

<!-- template-only -->
The repository used to wire agent hook scripts into Claude Code and Codex CLI. Each
behavior they had now lives here:

| Former agent hook behavior | Where it lives now |
|---|---|
| Format-on-edit (`format.py`) | An opt-in personal hook in the gitignored `.claude/settings.local.json` (snippet below) |
| Blocking `git commit --no-verify`, plain force-push, `gh pr merge --admin` (`guard.py`) | The owner's user-level deny rules, plus "never bypass a git hook" in AGENTS.md's "Security and human approval" |
| Blocking writes to `uv.lock` (`guard.py`) | `just verify`'s `lock-check` (`uv lock --check`) |
| Blocking writes to `.env*` and `secrets/**` (`guard.py`) | `check-staged` refuses them at commit time |
| ruff and mypy before an agent ends its turn (`stop_check.py`) | The ruff and mypy pre-commit hooks, and `just verify` |

<!-- /template-only -->

Format-on-edit for Claude Code, in `.claude/settings.local.json` (needs `jq`):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "f=$(jq -r '.tool_input.file_path // empty'); case \"$f\" in *.py) cd \"$CLAUDE_PROJECT_DIR\" && uv run --locked ruff check --fix --quiet \"$f\"; uv run --locked ruff format --quiet \"$f\" ;; esac; exit 0"
          }
        ]
      }
    ]
  }
}
```
