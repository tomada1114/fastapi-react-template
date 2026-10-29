# Why the gates are shaped this way

Read before changing how strict a checker is, how CI reports to the ruleset, which task
runner holds the recipes, or which layer runs a check. `SKILL.md` holds the rules; this
page holds what each choice protects and the alternative it rules out. Rewrite the
reason here in the same pull request that changes the choice.

## Strict types and lint from the first commit

Strict mypy and a wide Ruff rule set cover Python, and strict `tsc` and Biome cover the
frontend and `e2e/`, from the template's first commit rather than once the code
settles. Relaxed checks on early code leave a cleanup backlog that only grows, and the
same bar applies whether a human or an agent writes the change. Generated code carries
the one narrow exception `frontend/AGENTS.md` describes.

## One aggregate CI context

The ruleset requires `CI result` (`ci.yml`'s `ci-result` job), which fails unless every
gating job succeeded, instead of naming each job. Adding, renaming, or splitting a job
then never needs the live ruleset edited, which only an admin can do. The PR title,
Dependency Review, and CodeQL are separate required contexts because they come from
other workflows. In the template, the fresh-copy `Template Bootstrap Smoke` job runs
beside them and is never required, and the bootstrap removes it, so the template's own
check never changes an app's gates.

## Just rather than Make

Just expresses development tasks and per-area modules (`just backend <recipe>`,
`just frontend <recipe>`) directly, rather than through Make's build-target model. The
root combines the areas' recipes into one install and
one verification entry point, and each check stays runnable on its own, so no document
has to copy a command list.

## Git hooks rather than agent hooks

A check in one agent's hook misses every other author. The pre-commit layer runs the
same staged-secret, lint, type, spelling, and mirror checks on every commit by anyone —
a human, Claude Code, Codex CLI, another tool — and linked worktrees share the primary
checkout's hooks. What it cannot see is in
[pre-commit-layer.md](pre-commit-layer.md) › "When the hooks run, and when they do not";
the weekly gitleaks scan covers committed history.
