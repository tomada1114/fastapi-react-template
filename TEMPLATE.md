# About This Template

This is a FastAPI + React full-stack template: a to-do screen, an async HTTP API,
and SQLite persistence, with the checks needed to extend a fresh copy. This file
says how to use the template; `scripts/bootstrap.py` deletes it from an app. Why each
part is built the way it is lives in the skill that owns the subject
(`.agents/skills/`, indexed by AGENTS.md's Skills table), so it survives into every
app. The Python-only sibling,
[`tomada1114/uv-template`](https://github.com/tomada1114/uv-template), remains the
starting point for command-line tools and API-only services.

## Using This Template

Follow the `starting-an-app` skill (`.agents/skills/starting-an-app/SKILL.md`,
mirrored to `.claude/skills/`): "Use this template", bootstrap the copy, fill its
Product section, then `just install` and `just dev` for the screen and API.
Its `references/bootstrap.md` owns the rename procedure; its GitHub settings
reference marks the owner-only steps. A fresh-copy CI smoke test runs the
bootstrap, verification and browser test.

### Working in the new repository

- Work on a feature branch and publish a PR. The normal commit hooks include the
  secret gate; the `smart-commit` and `create-pr` skills own those procedures.
- Python dependencies use uv and `uv.lock`; JavaScript dependencies use pnpm and
  the root `pnpm-lock.yaml`. Both share one 7-day window: `[tool.uv] exclude-newer`
  and `minimumReleaseAge: 10080`. Monthly Dependabot updates share that cooldown.
  `managing-dependencies` owns review and owner-approved exceptions;
  `merging-dependency-prs` owns landing updates.
- `just verify` is the non-mutating gate before publication or a completion claim.
  `just check` formats first and is for local iteration. `changing-gates` owns
  the toolchain baseline and the enforcement layers.
