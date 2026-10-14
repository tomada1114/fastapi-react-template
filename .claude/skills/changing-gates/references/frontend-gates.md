# Frontend and pnpm gates

Read when changing a file that gates the JavaScript side: `frontend/vitest.config.ts`,
`frontend/biome.json` or `e2e/biome.json`, `frontend/tsconfig.json` or
`e2e/tsconfig.json`, `scripts/check_generated_client.py`, `pnpm-workspace.yaml`, the
`npm` entry in `.github/dependabot.yml`, `frontend/justfile`'s `lint`, `test`, or
`build`, or a CI job that installs pnpm. `SKILL.md`'s rule holds: each item below is a
weakening, and an agent never makes one to get a run green; it stops, says which gate
looks wrong and why, and a human decides.

## What weakening a gate means on the frontend

- **Coverage:** lowering a `coverage.thresholds` value in `frontend/vitest.config.ts`
  below 80, or dropping one of `lines`, `functions`, `statements`, and `branches`;
  adding anything to `coverage.exclude` beyond the generated `src/api/generated/**` and
  `src/routeTree.gen.ts`; narrowing `coverage.include`; a coverage-ignore comment in a
  source file; dropping `--coverage` from `just frontend test`.
- **Vitest:** `allowOnly: true`, or removing `allowOnly: false`; narrowing `include` so
  a test file stops running; an `it.skip`, `it.todo`, `it.only`, a deleted test, or a
  weakened assertion (`.skip` and `.todo` pass the run, so review is their gate;
  `writing-tests`).
- **Biome:** turning a rule off or down in `frontend/biome.json` or `e2e/biome.json`,
  leaving its `recommended` set, or excluding a hand-written path in `files.includes`
  (only the generated `src/routeTree.gen.ts`, `openapi.json`, and `src/api/generated`
  are excluded); a `biome-ignore` suppression comment whose explanation gives no real
  reason; `biome check` in place of `biome ci` in a gate.
- **TypeScript:** removing a strict flag from `frontend/tsconfig.json` (the set is
  listed in `frontend/AGENTS.md`'s "Layout") or `e2e/tsconfig.json`; dropping a file
  from its `include`; an `any` or a double cast (`as unknown as T`) that only silences
  an error, without a reason. `scripts/check_generated_client.py --scope-only`, the first
  step of `just frontend lint`, refuses every `@ts-ignore` and `@ts-expect-error` under
  `frontend/`, reason or not, and `@ts-nocheck` anywhere but
  `frontend/src/api/generated/{client,core}/**`, the owner-approved exception for the
  generator's bundled runtime. Widening that scope, or a directive the check does not
  scan (`e2e/`), is a weakening.
- **The contract:** a hand edit under `frontend/src/api/generated/` or to
  `frontend/openapi.json` (both come from `just contract`); removing `contract-check`
  from `just verify` or the `Contract Drift` job.
- **The build:** removing `frontend::build` from `just verify` or the route-tree check
  from `just frontend build`.
- **The pnpm window:** `SKILL.md`'s "The supply-chain window" bullet.
- **The pnpm policy:** `minimumReleaseAgeStrict: false`,
  `minimumReleaseAgeIgnoreMissingTime: true`, `strictDepBuilds: false`,
  `strictPeerDependencies: false`, `trustLockfile: true`, `blockExoticSubdeps: false`,
  `trustPolicy` removed, `verifyDepsBeforeRun` set to anything but `error`, or
  `pmOnFail` or `devEngines`' `onFail` set to `ignore` or `warn`; a new or widened
  `allowBuilds`, `minimumReleaseAgeExclude`, `trustPolicyExclude`, `overrides`, or
  `peerDependencyRules` entry without the owner (`managing-dependencies`' "The
  JavaScript side").
- **Installs:** `pnpm install` without `--frozen-lockfile` in CI or a recipe, or a second
  lockfile (`package-lock.json`, `yarn.lock`, `bun.lock`).
- **Hooks:** removing the `biome`, `tsc`, `biome-e2e`, or `tsc-e2e` pre-commit hook, or
  narrowing its `files`
  ([pre-commit-layer.md](pre-commit-layer.md)).
- **The browser test:** removing `e2e-lint` from `just lint`, or the `E2E` job from
  `CI result`'s `needs`; raising Playwright's `retries` from 0 or dropping
  `forbidOnly` in `e2e/playwright.config.ts`.

## Where each gate lives

| Gate | File | Run by |
|---|---|---|
| Vitest, `allowOnly`, the coverage floor | `frontend/vitest.config.ts` | `just frontend test`; CI `Frontend` |
| Biome | `frontend/biome.json`, `e2e/biome.json` | `just frontend lint`, `just e2e-lint`; the `biome` and `biome-e2e` hooks; CI `Frontend`, `E2E` |
| `tsc` and the strict flags | `frontend/tsconfig.json`, `e2e/tsconfig.json` | the same, and the `tsc` and `tsc-e2e` hooks |
| The `@ts-*` directive scope | `scripts/check_generated_client.py` | `just frontend lint`, `just contract-check` |
| Contract and client drift | `just contract-check` | `just verify`; CI `Contract Drift` |
| The pnpm policy and window | `pnpm-workspace.yaml` | every `pnpm install` |
| Window equality | `tests/harness/test_dependabot_cooldown.py` | `just check-harness` |
| Licenses and advisories in `pnpm-lock.yaml` | `.github/workflows/dependency-review.yml`, `osv-scanner.yml` | CI `Dependency Review`, `Scan lockfiles` |
| CodeQL over the TypeScript | `.github/workflows/codeql.yml` (`javascript-typescript`) | CI `Analyze (javascript-typescript)` |
