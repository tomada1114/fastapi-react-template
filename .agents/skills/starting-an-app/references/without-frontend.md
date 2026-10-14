# Without the frontend

The checklist behind `starting-an-app`'s "Choose the app's shape" for an **API-only**
app: one that keeps the FastAPI API and drops the React screen, the browser test, and
the Node.js toolchain. Each section names what one change to the template added, under
the template's issue number, and how an API-only app removes it. Do it in one pull
request on a branch, and describe the app's shape there as a design change
(`AGENTS.md`'s "Before changing the architecture").

Delete the whole areas first, then edit the files that name them, then finish with the
steps at the end. A recipe, path, or skill a file still names after its deletion fails
`just check-harness` or `just verify`, which is how a missed line shows up.

## The pnpm workspace and the screen (#19; #20, #28, #29)

#20 (router, server state, styling), #28, and #29 (the to-do screen) added nothing
outside `frontend/` but a `.gitignore` line, so they go with these:

- delete `frontend/` whole (its `package.json`, `src/`, `tests/`, `openapi.json`, the
  Biome, `tsc`, Vite, Vitest, and generator config, its `justfile`, `AGENTS.md`, and
  `CLAUDE.md`), and the root `package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`,
  and `.node-version`; remove the untracked `node_modules/` directories too;
- the root `justfile`: `mod frontend` and its comment; in `install`, the
  `pnpm install --frozen-lockfile` line, its error message, and the `pnpm_status`
  handling, so the recipe exits 0 once the hooks check passes; `frontend::fmt` from
  `fmt`, `frontend::lint` from `lint`, `frontend::test` from `test`, and
  `frontend::build` from `verify`, with the comments that name them; and
  `frontend/dist/` and `frontend/coverage/` in `clean`;
- `.gitignore`: the Node.js block (`node_modules/`, `frontend/dist/`,
  `frontend/coverage/`, and #20's `frontend/.tanstack/`);
- `typos.toml`: `pnpm-lock.yaml` in `extend-exclude`;
- `.editorconfig`: the `[{package.json,frontend/**}]` section;
- `.pre-commit-config.yaml`: `check-yaml`'s `--allow-multiple-documents` exists for
  `pnpm-lock.yaml`'s two documents, and may go with its comment;
- `AGENTS.md`: the Overview rows for `frontend/` and `e2e/`, the root row's
  `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, and `.node-version`, the
  "Working under `frontend/`" bullet, the Quick Reference lines of the `frontend`
  module's recipes and the frontend parts of the `install`, `fmt`, `lint`, `test`, and
  `verify` lines,
  `pnpm` and `frontend::` in the "Without Just" paragraph, and the `frontend/` row of
  "Validating a change";
- `CONTRIBUTING.md`: the Node.js 24 and pnpm prerequisites, `frontend/justfile` in the
  Just item, and the workflow block's lines for the `frontend` module and the
  `contract` recipe;
- tests: the pnpm cases of `tests/test_just_install.py` (each test whose name says
  `pnpm`, and the fake `pnpm` they install), and
  `tests/harness/test_just_recipes.py::test_module_tree_reads_repository_frontend_module`;
- CI: only the `Frontend`, `Contract Drift`, and `E2E` jobs set up pnpm and Node.js
  (`pnpm/action-setup`, `actions/setup-node`), and they go whole below, so no job that
  stays needs an edit.

## One `just dev` for both servers (#21)

- the root `justfile`'s `dev` recipe becomes `dev: backend::dev` with a one-line
  comment, as before #21; `tests/test_just_dev.py` goes (#119 extended it);
- the Vite proxy goes with `frontend/` (`frontend/vite.config.ts`,
  `frontend/tests/dev-proxy.test.ts`); `backend/justfile`'s `dev` keeps
  `MY_APP_API_PORT`, but its comment stops naming `frontend/vite.config.ts`;
- `.devcontainer/devcontainer.json`: the `ghcr.io/devcontainers/features/node` feature,
  `corepack enable && ` in `postCreateCommand`, and `5173` in `forwardPorts`;
- `running-the-app`: item 4 of "Evidence, cheapest first", the section "Running a
  `just dev` pair of your own", `references/own-dev-pair.md`, and the Vite, `5173`, and
  `VITE_PORT` mentions in "The developer's server is not yours";
- `AGENTS.md`: the screen in `just dev`'s line under "Long-running", the `frontend`
  module's `dev` line there, and that recipe in the paragraph after them.

## The frontend's CI job (#22)

- `.github/workflows/ci.yml`'s `frontend` job (`Frontend`), `frontend` in `ci-result`'s
  `needs:`, and its `needs.frontend.result != 'success'` term in the failing step's
  `if:`. `tests/harness/test_ci_aggregate.py` fails while `needs:` names a job that is
  gone;
- `changing-gates`: `Frontend` in "The layers and what each sees" and in the `needs:`
  list of "CI workflows and required checks".

## Supply-chain checks for JavaScript (#23)

- `.github/dependabot.yml`: the `npm` update, with its comment and its TypeScript
  `ignore`. `tests/harness/test_dependabot_cooldown.py` pairs the `npm` cooldown with
  `pnpm-workspace.yaml` only while an `npm` update exists; its npm fixtures test that
  pairing and may go with it;
- `.github/workflows/osv-scanner.yml`: `pnpm-lock.yaml` in both `paths:` lists and the
  `--lockfile=pnpm-lock.yaml` argument;
- `.github/workflows/codeql.yml`: `javascript-typescript` in the language matrix,
  together with its `Analyze (javascript-typescript)` context in
  `.github/rulesets/main.json` and in `tests/test_apply_ruleset.py`'s expected list:
  `tests/harness/test_ruleset_contexts.py` fails on a required context no job reports.
  The live ruleset is the owner's, at the end;
- `references/private-repository.md` (this skill) then has one context fewer to remove.

## The frontend's and e2e's commit hooks (#24, #122)

- `.pre-commit-config.yaml`: the `biome`, `tsc`, `biome-e2e`, and `tsc-e2e` hooks and
  the comments above them; `mypy-backend`'s `files:` back to `^backend/` (drop the
  `e2e/verify_persistence\.py` alternative) and its comment; `tests/test_frontend_hooks.py`;
- `smart-commit`: `biome`, `tsc`, `biome-e2e`, and `tsc-e2e` in its description, their
  bullets and rows in `references/pre-commit-hook.md`, and `e2e/verify_persistence.py`
  in its `mypy-backend` line;
- `changing-gates`: the "`biome` and `tsc`, the frontend and e2e hooks" and
  "`mypy-backend` and `e2e/verify_persistence.py`" sections of
  `references/pre-commit-layer.md`, and the hooks' rows in "The layers and what each
  sees" (`references/frontend-gates.md` goes with the frontend, below).

## Worktrees (#25): nothing

`just worktree-prepare`, `shipping-issues`' worktree and preflight scripts, and
`codex-shipping-issues` run `pnpm install --frozen-lockfile` only when `pnpm-lock.yaml`
exists. With it gone they skip pnpm on their own; their prose may keep saying so.

## Node.js 24 in cloud sessions (#40)

`cloud-claude-shipping-issues`: the `pnpm --dir frontend exec node --version` check in
step 1, the stop condition on that check and on `pnpm install --frozen-lockfile`, and
the Node.js 24 and pnpm part of `references/cloud-host.md`'s "What the session starts
with".

## The committed contract and the generated client (#26, #27)

- the root `justfile`'s `contract` and `contract-check` recipes, `contract-check` in
  `verify`, and their lines in `AGENTS.md`'s Quick Reference;
- `.github/workflows/ci.yml`'s `contract-drift` job (`Contract Drift`), its `needs:`
  entry, and its term in `ci-result`'s failing step;
- `scripts/check_generated_client.py` and `tests/test_check_generated_client.py`;
  `frontend/openapi.json` and `frontend/src/api/generated/` went with `frontend/`;
- the owner's choice: an app that publishes its contract keeps
  `backend/src/my_app/api/contract.py` and `backend/tests/api/test_contract.py`,
  re-points `contract`'s `--output` (and `contract-check`'s) at a path that stays, drops
  `contract`'s generator line and `contract-check`'s client check, and keeps the job
  without its pnpm steps; otherwise both files go with the recipes;
- `building-api-routes`' step of "Adding a route" that regenerates the contract and
  commits `frontend/openapi.json`, and `updating-docs`' generated-contract row.

## The browser test (#30)

- delete `e2e/` whole (`package.json`, `playwright.config.ts`, `environment.ts`,
  `tests/`, `verify_persistence.py`, its Biome and `tsc` config); its `- "e2e"` line
  went with `pnpm-workspace.yaml`;
- the root `justfile`: the `e2e` and `e2e-lint` recipes and their comments, `e2e-lint`
  in `lint`, the `pnpm --dir e2e` line in `fmt`, and `e2e/test-results/` and
  `e2e/playwright-report/` in `clean`; `.gitignore`'s Playwright lines;
- `.github/workflows/ci.yml`'s `e2e` job (`E2E`), its `needs:` entry, and its term;
- `tests/test_just_e2e.py` and `backend/tests/test_e2e_persistence.py`;
  `backend/pyproject.toml`'s mypy `files` entry `../e2e/verify_persistence.py` and the
  comment above it;
- `running-the-app`: item 3 of "Evidence, cheapest first" and `references/e2e.md`;
- `AGENTS.md`: the Quick Reference lines of the `e2e` and `e2e-lint` recipes, the
  `e2e/` row of "Validating a change", and the browser test in the CI row of
  "Enforcement layers"; `CONTRIBUTING.md`'s browser-test lines.

## The frontend skills (#31, #32)

- delete `.agents/skills/building-screens/` and its row in `AGENTS.md`'s Skills table;
- remove the frontend side #32 gave these skills, each with the frontend words in its
  description and its `AGENTS.md` Skills row:
  - `managing-dependencies`: "The JavaScript side", `references/pnpm.md`, and pnpm,
    `minimumReleaseAge`, and `pnpm-lock.yaml` in the window and scanner sections;
  - `merging-dependency-prs`: the `npm` and `npm_and_yarn` parts of its steps,
    "`npm_and_yarn` PRs" in `references/review-checklist.md`, the pnpm lines of
    `references/failure-modes.md` and `references/landing.md`, and `Frontend`,
    `Contract Drift`, and `E2E` in `failure-modes.md`'s list of gating jobs;
  - `placing-tests`: "The frontend and the browser test", and the Vitest lines of
    "Running tests" and "The coverage floor";
  - `writing-tests`: "A frontend test", `references/frontend-tests.md`, and its
    Vitest anti-patterns;
  - `tdd`: "The frontend", and `frontend/src/` in "Where the code lives";
  - `changing-gates`: the frontend bullet of "What weakening a gate means here",
    `references/frontend-gates.md`, and the frontend rows of "The layers and what each
    sees";
  - `updating-docs`: the `frontend/AGENTS.md` row, the `VITE_` variables, and the
    generated contract;
- then `just agents-sync`.

## README (#36)

- Quickstart: the Node.js 24 and pnpm prerequisites, the screen on port 5173, and the
  browser and Vite half of the request-flow diagram;
- Configuration: the `VITE_PORT`, `E2E_API_PORT`, and `E2E_WEB_PORT` rows;
- Architecture: the `frontend/` line and the pointer to `frontend/AGENTS.md`;
- Development: the screen in `just dev`'s description, the sentences on the
  `frontend` module and the `contract` and `e2e` recipes, and the `pnpm install` note.

## Finish

1. `uv lock`: no Python package went, so it should leave `uv.lock` as it is; a change
   means a Python file was dropped by mistake.
2. `just agents-sync`, then search the tree:
   `git grep -nE "pnpm|vite|playwright|frontend|e2e"`. Judge each hit: a mention of
   this checklist, or a skill's sentence that pnpm runs only once `pnpm-lock.yaml`
   exists, can stay.
3. `just verify` in a shell with no Node.js or pnpm on `PATH`
   (`command -v node pnpm corepack` prints nothing): it proves nothing that stays
   still calls them.
4. **The ruleset, for the owner** (**human**, an admin): this pull request removed
   `Analyze (javascript-typescript)` from `.github/rulesets/main.json`. If the ruleset is
   not applied yet, step 9 of the order applies it as it is. If it is already live, the
   pull request can never report that context, so the owner applies the edited file with
   `just ruleset` from this branch before merging it; an agent never runs it.
