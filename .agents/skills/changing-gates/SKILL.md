---
name: changing-gates
description: >
  Covers changing a file that enforces rather than implements: .pre-commit-config.yaml,
  check_staged.py, a .github/workflows job, the ruleset, the justfiles' verify, lint,
  and test recipes, typos.toml, pyproject.toml's ruff, mypy, pytest, and coverage
  tables, vitest.config.ts coverage.thresholds, biome.json, tsconfig.json,
  pnpm-workspace.yaml - and what weakening a gate means (a removed rule, a noqa or
  @ts-ignore, a lower floor, a skipped test, a looser pnpm key, a dropped CI step). Use
  when changing a hook, a lint, type, or coverage setting, or CI. A hook refusing a
  commit is smart-commit's.
---

# Changing Gates

**Owns:** a change to a file that enforces rather than implements, keeping the gate
layers in step, and the list of what counts as weakening one. **Does not own:** whether
a gate may be weakened at all — never, without a human (AGENTS.md's "Security and human
approval"); a coverage floor's meaning and where a test goes (`placing-tests`); a new
tool the config would configure (`managing-dependencies`); the ruff relaxations for
scripts bundled in a skill (`authoring-skills`); writing a script a gate runs
(`writing-repo-scripts`); `.github/labels.yml` (`triaging-issues`).

A gate defines what "done" means for every later change, so a loosened rule silently
lowers the bar for every pull request after it, not only the one that touched it.

## What weakening a gate means here

Each of these is a weakening. An agent never makes one to get a run green; it stops,
says which gate looks wrong and why, and a human decides.

- **Coverage:** lowering `--cov-fail-under=80` (`backend/justfile`'s `test`, or CI's
  `Coverage` job); adding a pattern to `backend/pyproject.toml`'s
  `[tool.coverage.report] exclude_lines`, an `omit`, or a `# pragma: no cover`.
- **Ruff:** removing a prefix from `select`; adding a code to `ignore`; adding or
  widening a `per-file-ignores` entry without a reason comment; a `# noqa` without a
  written reason after it.
- **mypy:** turning off `strict` or any `warn_*` or `enable_error_code` entry; a new
  `[[tool.mypy.overrides]]` block; a `# type: ignore` without an error code and a
  reason; a cast that only silences an error.
- **pytest:** removing `--strict-markers` or `--strict-config`; removing
  `filterwarnings = ["error"]`, or adding an `ignore` entry to it (or a
  `@pytest.mark.filterwarnings` ignore) without a reason comment and a follow-up issue,
  or one broader than the single warning it names; `@pytest.mark.skip`,
  `xfail`, a deleted test, or a weakened assertion.
- **The lock:** removing `--locked` from a recipe or a CI step, or `lock-check` from
  `just verify`.
- **The supply-chain window:** shortening `[tool.uv] exclude-newer` in the root
  `pyproject.toml`, `minimumReleaseAge` in `pnpm-workspace.yaml`, or a Dependabot
  `cooldown` in `.github/dependabot.yml` (the `uv` and `npm` entries' must equal the
  window), or a blanket or stale `exclude-newer-package` entry
  (`managing-dependencies`).
- **The frontend and pnpm** ([references/frontend-gates.md](references/frontend-gates.md)
  has the full list): a lower `coverage.thresholds` value, a Biome rule off in
  `biome.json`, a strict `tsconfig.json` flag removed, `@ts-nocheck` outside
  `frontend/src/api/generated/{client,core}/**`, a looser `pnpm-workspace.yaml` key, an
  `allowBuilds` entry without the owner, `pnpm install` without `--frozen-lockfile`.
- **The pre-commit layer:** removing a hook, narrowing its `files`, `types`, or
  `stages`, loosening `scripts/check_staged.py`'s rules, adding an entry to
  `.check-staged-allow`, `--no-verify`, `SKIP=<id>`, or an edit to `.git/hooks/`.
- **CI and the ruleset:** removing a job or a step; gating a required job with `if:`,
  `paths`, or `paths-ignore`; dropping a context from `.github/rulesets/main.json`;
  adding a bypass actor; widening a workflow's `permissions`; unpinning an action from
  its commit SHA; `persist-credentials: true`.
- **Spelling:** adding a real misspelling to `typos.toml`'s `extend-words`, or a path to
  its `extend-exclude` to hide one.

A change that tightens a gate is welcome, but still owes the pull request body three
things: which rule or option moved, why, and what now fails that did not before.

## Python baseline

Changing the supported Python moves several settings together, held by
`tests/harness/test_python_baseline.py`:
[references/python-baseline.md](references/python-baseline.md).

## The layers and what each sees

AGENTS.md's "Enforcement layers" names the layers. Keeping them in step is this skill's:

| Check | pre-commit | `just verify` | CI |
|---|---|---|---|
| ruff check, ruff format | `ruff`, `ruff-format` | `lint` | `Lint & Type Check` |
| mypy, root (`scripts`, `tests`, skill scripts) | `mypy` | `lint` | `Lint & Type Check` |
| mypy, `backend/` (`src`, `tests`, `migrations`) and `e2e/verify_persistence.py` | `mypy-backend` | `lint` (`backend::lint`) | `Lint & Type Check` (in `backend/`) |
| Skills mirror | `agents-check` (working tree) | `agents-check` (working tree) | `Lint & Type Check` (the commit) |
| Skill script tests | — | `test-skills` | `Lint & Type Check` |
| `uv lock --check` | — | `lock-check` | `--locked` on every `uv sync` |
| Tests, and the 80% floor over `backend/src` | — | `test` (`backend::test` for the floor) | `Coverage` |
| Harness drift (`tests/harness`) and the Product section | — | `check-harness` | `Coverage` |
| Biome, `tsc`, and the `@ts-*` scope over `frontend/` | `biome`, `tsc` | `lint` (`frontend::lint`) | `Frontend` |
| Vitest and the 80 `coverage.thresholds` over `frontend/src` | — | `test` (`frontend::test`) | `Frontend` |
| The frontend build and its staged route tree | — | `frontend::build` | `Frontend` |
| The API contract and generated client | — | `contract-check` | `Contract Drift` |
| Biome and `tsc` over `e2e/` | `biome-e2e`, `tsc-e2e` | `lint` (`e2e-lint`) | `E2E` |
| The browser test, screen to database (`just e2e`) | — | — (run it on its own) | `E2E` |
| typos | `typos` | — | `Spell Check` |
| zizmor | `zizmor` | — | `Workflow Security Lint` |
| shellcheck (skill `.sh` scripts) | `shellcheck` | — | `Lint & Type Check` |
| Skill scripts under Python 3.9 | — | — | `Skill Scripts (Python 3.9)` (not required) |
| Staged secrets | `check-staged` | — | the weekly gitleaks history scan |
| `uv.lock` and `pnpm-lock.yaml`: licenses, advisories | — | — | `Dependency Review` (PRs), `Scan lockfiles` (OSV-Scanner) |
| CodeQL: `python`, `actions`, `javascript-typescript` | — | — | `Analyze (<language>)` |

- A check added to `just verify` gets the matching CI step, and the reverse.
  `tests/harness/test_just_recipes.py` enforces parity for `agents-check`, `lint`,
  `test-skills`, and `test`, `backend/justfile`'s lines included (CI runs those in a
  `working-directory: backend` step); the reviewer checks any additional gate.
- Ruff's local system hooks run `uv run --locked ruff`, sharing `uv.lock` with
  `lint` and CI. A Ruff update moves the existing dependency range and lock; there
  is no separate hook revision to align. **BACKGROUND:** `merging-dependency-prs`.
- CI's `Spell Check` runs the pinned typos pre-commit hook with `--all-files`,
  sharing its revision, config, and file selection with local checks. Dependabot's
  `pre-commit` entry updates remote hook revisions; local hooks use the project lock.
  Dependabot supports remote pre-commit hooks
  (https://github.blog/changelog/2026-03-10-dependabot-now-supports-pre-commit-hooks/,
  checked 2026-10-07).
- CI runs zizmor through the pinned pre-commit hook with `--all-files`, sharing
  its version and file selection with local checks, including Dependabot and composite
  action definitions. Update the hook revision rather than introducing a separate CI pin.
- CI's `Lint & Type Check` runs shellcheck through the pinned `shellcheck-py`
  pre-commit hook with `--all-files`; the hook excludes the `.claude/skills/` mirror.
- `just verify` runs neither typos nor zizmor; the pre-commit hook does, so prose and
  workflow changes are checked at commit time and in CI. AGENTS.md's "Validating a
  change" gives the command for each.

## CI workflows and required checks

- Every job — and every step of a composite action under `.github/actions/` — pins
  each action to a 40-character commit SHA with a `# vX.Y.Z` comment and checks out
  with `persist-credentials: false`; every job sets `timeout-minutes`. The
  top-level `permissions` is `{}` or exactly `contents: read`; a scope beyond that,
  a write above all, is granted on the job that needs it. On a workflow that also runs
  on push, concurrency never cancels a push run on `main`, pending ones included.
  Enforced by: `tests/harness/test_workflow_hygiene.py` (`just check-harness`); zizmor
  (pre-commit and CI) reports most other departures — verify with
  `uv run --locked pre-commit run zizmor --all-files`.
- A required check must be a job that runs on every pull request and cannot be skipped:
  never a job in a workflow whose `pull_request` trigger has `paths` or `paths-ignore`,
  and never a job whose `if:` could skip it — a skipped required check counts as
  passing. A job with `needs:` is guarded with `!cancelled()` or `always()` and fails on
  its own when a needed job did not succeed. Only a few step shapes count, read as
  text: an initial `if [ "$R" != "success" ]; then … exit 1; fi` as the step's first
  command,
  `[ "$R" = success ] || exit 1`, or a step `if: needs.X.result != 'success'` whose
  `run:` is `exit 1` (the full list is `tests/harness/_needs.py`'s docstring).
  `skipped` is not `success`, so a required job cannot need a job that is skipped on
  purpose. Enforced by: `tests/harness/test_ruleset_contexts.py`, which also fails on a
  workflow layout its scanner cannot read.
- The ruleset requires one CI context, `CI result` (`ci.yml`'s `ci-result` job), plus
  the contexts other workflows report. A gating CI job joins `ci-result`'s `needs:` and
  its failing step's `if:` (one `needs.<id>.result != 'success'` term each), with no
  ruleset edit; a job that does not gate goes in `tests/harness/test_ci_aggregate.py`'s
  `EXEMPT_JOBS` with its reason. That test fails on a `ci.yml` job in neither. Its
  `needs:` today: `Lint & Type Check`, `Coverage`, `Frontend`, `PostgreSQL`,
  `Spell Check`, `Workflow Security Lint`, `Contract Drift`, and `E2E`.
- Renaming `CI result` is the one CI change that edits `.github/rulesets/main.json`;
  so do adding or renaming a required context from another workflow. Each also edits
  `tests/test_apply_ruleset.py::test_required_contexts_match_settled_defaults` in the
  same pull request. The live ruleset changes only when the owner reruns `just ruleset`
  — an admin step an agent proposes and never runs. **BACKGROUND:** `starting-an-app`
  for the ruleset and security settings a new repository enables.
- A new workflow file is warranted only for a different trigger or permission
  footprint, never as a convenience split from `ci.yml`.

## The pre-commit layer

The hooks run for every author, so a hook that fires on intended work teaches its
author to reach for `--no-verify`, which switches off the secret gate with it. Test a
new or changed hook against an ordinary commit before trusting it to catch a bad one.
Every hook names `stages: [pre-commit]` itself; only `check-staged` also runs at
`pre-merge-commit` (`tests/test_check_staged.py`). The frontend's `biome` and `tsc`
hooks run `pnpm exec` from `frontend/`, and `biome-e2e` and `tsc-e2e` from `e2e/`. Their shape, what `check-staged` refuses, how
merges and rebases interact with it, how `just install` verifies the hooks, and what
replaced the old agent hooks: [references/pre-commit-layer.md](references/pre-commit-layer.md).

## Tool configs in the two `pyproject.toml` files

Read the current values in the files rather than a copy here. The root `pyproject.toml`
configures the repository's own code (`scripts/`, the root `tests/`, skill scripts) and
holds the shared Ruff rule selection; `backend/pyproject.toml` configures the app: its
Ruff config `extend`s the root's and replaces `per-file-ignores`, and it holds the
`banned-api` table and the app's own mypy, pytest, and coverage tables. Traps that have
cost time:

- The root's Ruff `per-file-target-version` pins skill scripts to `py39` and
  `scripts/check_staged.py` to `py310`, because each runs under an interpreter older
  than the project's 3.14. Never let a newer syntax rule reach them.
- `backend/pyproject.toml`'s `[tool.ruff.lint.flake8-tidy-imports.banned-api]` is a
  layer boundary, not a style rule. **BACKGROUND:** `designing-core-logic`.
- The root's `[tool.ruff.lint.flake8-type-checking]` runtime-evaluated lists keep
  framework annotations real imports. **BACKGROUND:** `writing-python`.
- The coverage floor is in neither `pyproject.toml`: it is the `80` in
  `backend/justfile`'s `test` recipe and in CI's `Coverage` job. Change both or neither.

## What no gate sees

- Anything only a running server shows (`running-the-app`).
- Whether a path named in Markdown still exists. A skill's frontmatter, AGENTS.md's
  Skills table, and a `just <recipe>` in command position are `just check-harness`'s,
  but the recipe scan leaves out the roadmap, `docs/product/`
  (intent or history, not instructions), and `.devcontainer/` (JSON with comments).
- A staged deletion: `check-staged` never inspects one, by design.
- Commits that run no hook at all ([references/pre-commit-layer.md](references/pre-commit-layer.md)
  › "When the hooks run, and when they do not").

A gate proposed to close one of these gaps is a real gate, argued for in its own pull
request.
