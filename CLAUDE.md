@AGENTS.md

# Claude Code Specifics

Shared, tool-agnostic project instructions live in `AGENTS.md` (imported
above). This file only records what Claude Code adds on top of them.

- `.claude/settings.json` holds one thing: a SessionStart hook that runs
  `just install` in a Claude Code cloud session (`CLAUDE_CODE_REMOTE=true`)
  and does nothing locally, since a cloud session reads no user-level or
  `.local` settings. The guard rails stay git hooks (`AGENTS.md`'s
  "Enforcement layers"), which run for every author. Permission rules, plugin
  marketplaces, and personal hooks such as format-on-edit (its snippet is in
  the `changing-gates` skill's `references/pre-commit-layer.md`) belong in
  `~/.claude/settings.json` or the gitignored `.claude/settings.local.json`.
- `.claude/skills/` is a generated mirror of `.agents/skills/`. Never hand-edit
  it: edit `.agents/skills/`, run `just agents-sync`, and commit both.
- Hand a step to a sub-agent tier by `subagent_type` — `executor`, `architect`,
  `scout`, or `worker` — never by a bare `model`, which runs at the session's default
  effort rather than the tier's. The definitions in `.claude/agents/` shadow
  same-named ones in `~/.claude/agents/` inside this repository.
