# About This Template

This file documents the template itself: why it is built the way it is, and
how to turn a copy of it into a real application. `scripts/bootstrap.py` deletes
it from the spawned repo, so nothing here ships with your application.

## Using This Template

The steps live in one place: the `starting-an-app` skill
(`.agents/skills/starting-an-app/SKILL.md`, mirrored to `.claude/skills/`). It gives
the order of work from "Use this template" to the first feature — the bootstrap, the
Product section, labels, the GitHub settings, the ruleset, removing the sample — and
marks which steps are a human's. Its `references/bootstrap.md` documents
`scripts/bootstrap.py`: the flags, what it refuses, and what it rewrites and removes.

### Working in the new repository

- **Never commit directly on `main`.** The pre-commit `no-commit-to-branch`
  hook blocks it, and `--no-verify` would also switch off the secret gate
  (`scripts/check_staged.py`), so the way through is a feature branch and a
  PR — not a bypass flag.
- The toolchain baseline checklist lives in `changing-gates` so every app keeps it.
- Python dependencies arrive as monthly Dependabot `uv` PRs under a 14-day
  cooldown equal to `[tool.uv] exclude-newer = "14 days"`; a human merges
  them with the `merging-dependency-prs` skill, and `managing-dependencies`
  holds the window and its one-package exception.
- `just verify` (its steps are listed in AGENTS.md's Quick Reference) is the
  non-mutating gate for a PR or a completion claim; `just check` mutates the
  tree first (`fmt`) and is for local iteration only.

## Design Philosophy

Every choice in this template has a reason. If you disagree with a decision,
you know exactly what to change and why it was there in the first place.

### Why `src/` layout?

The `src/` layout prevents accidental imports of the local package during
development and testing. It ensures that tests always run against the
*installed* package rather than the working tree, so a missing module or a
broken package configuration fails the test run instead of the deployed app.

### Why strict mypy + comprehensive Ruff rules?

Type errors and lint issues are cheapest to fix at write time. Strict settings
from day one mean every line of code is held to the same standard — there is
never a "legacy" codebase to clean up. LLMs generating code also benefit from
strict rules: they produce higher-quality output when constraints are clear.

### Why a framework-free core with FastAPI and Typer over it?

Most Python applications end up with an HTTP API, a command line, or both, and
the expensive mistake is letting either framework leak into the business
rules. The template therefore ships the shape rather than an empty package: a
`core` that imports only the stdlib (ports are `typing.Protocol`s, values are
frozen dataclasses), adapters that implement its ports, and two thin entry
points that get their services from one composition root. Ruff's banned-api
rule and a test keep the core clean, and the CLI reaches the API only through
`cli/serve.py`, so dropping the entry point you do not need is a list of
deletions (README's Architecture section), not a refactor.

The runtime dependencies are exactly what those entry points need — FastAPI,
uvicorn, Typer, and pydantic-settings — and the SQLite adapter uses the
stdlib `sqlite3` driver rather than an ORM. The one other package, `httpx`,
sits in the optional `ai` extra for the LLM adapter below, so an app that
never installs it carries nothing extra. Anything else is yours to add
deliberately.

### Why an optional LLM layer behind a port?

Many apps cut from this template will call a language model, and the same
mistake the core avoids for HTTP frameworks applies here: a provider's SDK
leaking into the business rules. So the LLM is one more port. `LlmPort` and
its values (`core/llm.py`) are plain Python, and adapters implement it: a
`FakeLlm` for tests, a `ClosedLlm` for an app with no key, and
`OpenRouterLlm`. The fake and OpenRouter adapters pass one contract suite.

- **OpenRouter as the one provider.** One key reaches many vendors' models,
  and the model is a setting (`MY_APP_LLM_MODEL`), so trying another model is
  not a code change. A second provider is a second adapter.
- **Raw `httpx` over the `openai` SDK.** `httpx` and everything it needs were
  already locked for `TestClient`, so the layer adds no locked package. The
  SDK would add several, for one POST, and bring its own retry and timeout
  layer that would double the adapter's (the sibling nextjs-app-template's
  issue #73 had to fight exactly that).
- **An extra, not a group or a hard dependency.** An extra is package
  metadata a wheel carries (`pip install 'my-app[ai]'`); a dependency group
  never reaches a built package; a hard dependency would make every app carry
  it.
- **Closed by default.** Without `OPENROUTER_API_KEY`, `build_llm` returns
  `ClosedLlm`, a route built on it answers 503, and neither `httpx` nor the
  adapter is imported. The key alone opens it: a billed endpoint is never
  open by accident. No sample route ships, so there is no billed endpoint to
  protect until an app writes one. 503 rather than 500, because here a 500
  means a bug and an unconfigured feature is not one.
- **Bounded retries inside one deadline.** Two retries on 429, 502, 503, or
  a connect error (never on a timeout, a connect timeout included), waiting
  0.5 s then 1.0 s or the provider's `Retry-After` up to 8 s; a longer
  `Retry-After` ends the call. `timeout` is one budget
  for the call, retries included, so retries never multiply it; callers default
  to 60 s. Each network phase is bounded by the budget left and the deadline is
  checked between phases, body chunks, and attempts, so a pathologically slow
  server can still exceed it; a hard cutoff is the caller's own cancellation.
  The 60 s and the 8 s cap follow the sibling nextjs-app-template's
  OpenRouter adapter (its issues #63, #71, and #73).
- **No live call in the suite.** It would bill, flake, and need a key in CI,
  and a skipped test is a weakened gate. The OpenRouter adapter runs the
  contract suite over `httpx.MockTransport`; the `integrating-llm` skill
  documents the owner's manual live check.

The decision is the template's issue #97. A project that keeps the layer
records its own ADR; one that does not follows the skill's removal list.

### Why Just over Make?

Just has cleaner syntax (no mandatory tabs), better cross-platform support, and
more readable recipe definitions. It is a task runner, not a build system —
which is exactly what a Python project needs.

### Why AGENTS.md and the agent configuration?

AI-assisted development is the norm, not the exception. `AGENTS.md` gives any
coding agent (Claude Code, Codex, Cursor, Gemini CLI, ...) the context it
needs to match your project's standards; `CLAUDE.md` imports it and adds
Claude Code specifics. Skills are authored once in `.agents/skills/` and
mirrored into `.claude/skills/` (`just agents-sync`); `.claude/agents/` and
`.codex/agents/` define the same three sub-agent tiers for each host.
Permission allowlists, model choices, plugin marketplaces, and editor hooks
are personal and are never committed.

### Why a pre-commit layer instead of agent hooks?

A guard rail wired into one agent's hook configuration protects nothing when
a human, or a different tool, makes the commit. So the template commits no
agent hooks: its guard rails are git hooks run by pre-commit, which fire on
`git commit` for every author. `scripts/check_staged.py` refuses secret-shaped
paths and credential-shaped content straight from the index, on every
`git commit` and every merge commit, and `just install` fails when the git
hooks are missing. A file the gate refuses but that holds no secret gets
through by a reviewed entry in `.check-staged-allow`, never by a bypass flag.
Commits git makes without running hooks — `git rebase` replays,
`git cherry-pick`, `git revert` — are left to the weekly full-history scan of
the Security Audit workflow (gitleaks). What the old agent hooks did and where
each behavior went is the replacement table in the `changing-gates` skill's
`references/pre-commit-layer.md`.

### Why 80% coverage minimum?

80% is high enough to catch most regressions but low enough to avoid
test-for-the-sake-of-testing. Branch coverage is enabled, so conditional logic
is meaningfully tested.
