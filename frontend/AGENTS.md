# Frontend Guide

The React app: a pnpm workspace member built with Vite and TypeScript, linted
and formatted by Biome, type-checked by `tsc`, and tested by Vitest. This file
adds the frontend's own rules to the root `AGENTS.md`, which still applies in
full — its approval rules and gates above all.

## Toolchain

Node.js 24 and pnpm 11 are the only toolchain; no `npm`, `yarn`, or `bun`
command runs here, and no lockfile but the root `pnpm-lock.yaml` is committed.

- The root `package.json` pins pnpm (`packageManager`, with
  `pmOnFail: download` in `pnpm-workspace.yaml`) and requires Node.js
  `^24.19.0` through `devEngines.runtime` with `onFail: download`:
  `pnpm install` records the exact Node.js 24 release and its checksum in
  `pnpm-lock.yaml` and runs every frontend tool on it, whatever `node` is on
  `PATH`. Check the runtime with `pnpm --dir frontend exec node --version`,
  never `node --version`. Never set `runtimeOnFail` (or `pmOnFail`) to
  `ignore` or `warn`: when the download fails, the remedy is a reachable
  `nodejs.org` or Node.js 24 per `.node-version`.
- Get pnpm with `corepack enable` (Node.js 24 still ships Corepack) or any
  pnpm 11, which fetches the pinned version itself.
- Install with `just frontend install` (`pnpm install --frozen-lockfile` at the
  workspace root; `just install` runs it too). `pnpm exec` and `pnpm run`
  refuse a `node_modules` that no longer matches the lockfile
  (`verifyDepsBeforeRun: error`), so reinstall after the lockfile moves.

## Validating a change

Every command here runs from anywhere in the repository. Run the narrowest
check that can fail while iterating, then `just verify` before a completion
claim.

| What you changed | The narrowest check that can fail |
|---|---|
| A file's formatting or lint | `just frontend lint` (`just frontend fmt` applies Biome's fixes) |
| Types, or `tsconfig.json` | `pnpm --dir frontend exec tsc --noEmit` |
| One test file | `pnpm --dir frontend exec vitest run tests/<name>.test.tsx` |
| Anything under `src/`, or `vitest.config.ts` | `just frontend test` (the coverage floor) |
| `vite.config.ts`, `index.html`, or anything the bundle includes | `just frontend build` |
| The whole frontend | `just frontend lint && just frontend test` |

`just frontend dev` is the developer's Vite server, human-run: an agent never
starts, stops, or restarts it (the root `AGENTS.md`'s Quick Reference,
`running-the-app`).

## Layout

```
frontend/
├── package.json      # The app's scripts and dependencies (ranges; pnpm-lock.yaml at the root pins them)
├── justfile          # A just module of the root justfile: `just frontend <recipe>`
├── biome.json        # Biome: formatter (2 spaces, 88 columns) and the recommended lint rules
├── tsconfig.json     # One project for src/, tests/, and both configs, under the strict flag set
├── vite.config.ts    # Vite and its plugins (the only place plugins are declared)
├── vitest.config.ts  # Merges vite.config.ts; jsdom, the setup file, and the coverage floor
├── index.html        # The page Vite serves and builds: <div id="root">
├── src/              # The app: main.tsx (the entry point) and its components
└── tests/            # Vitest tests (*.test.ts, *.test.tsx) and setup.ts
```

- `tsconfig.json` and `biome.json` are strict JSON (`check-json` parses them):
  no comments, no trailing commas.
- `tsc --noEmit` is the type gate, under `strict`, `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`, `noImplicitOverride`,
  `noPropertyAccessFromIndexSignature`, `noUncheckedSideEffectImports`,
  `noImplicitReturns`, `useUnknownInCatchVariables`, `verbatimModuleSyntax`,
  `isolatedModules`, and `moduleDetection: "force"`. Loosening any of them, or a
  `@ts-ignore`, `@ts-expect-error`, or `@ts-nocheck` in a hand-written source
  or test file, weakens a gate (`changing-gates`).
- `skipLibCheck` is on: `@testing-library/jest-dom` 7.0.1's Vitest types
  declare `Assertion<T>`, which conflicts with Vitest 5's `Assertion<R, T>`
  inside `node_modules`. It skips checking third-party declaration files only;
  every file under `src/` and `tests/` is still fully checked, matchers
  included.
- `typescript` stays on `~6.0.3`: moving to 7.x waits for the API client
  generator to support it.

## Tests and the coverage floor

- Tests live in `frontend/tests/`, never beside the source, and match
  `tests/**/*.test.{ts,tsx}`. `tests/setup.ts` registers the jest-dom matchers
  and runs Testing Library's `cleanup` after each test (Vitest runs without
  `globals`).
- `just frontend test` fails when lines, functions, statements, or branches
  fall below 80% over `src/**/*.{ts,tsx}` — the backend's bar. The only
  exclusions are generated code, `src/api/generated/**` and
  `src/routeTree.gen.ts`; anything else untested is covered by a test, never
  excluded. Lowering a threshold or widening the exclusions weakens a gate.
- `.only` fails the run (`allowOnly: false`), and mocks, stubbed globals, and
  stubbed environment variables are restored after each test.

## Dependencies

- A new package — runtime or dev — needs the owner's sign-off and
  `managing-dependencies`' review record before `pnpm add` runs. Add it with
  `pnpm --dir frontend add <package>` (`-D` for a dev dependency) rather than
  typing a version.
- `pnpm-workspace.yaml`'s `minimumReleaseAge` holds every version back until it
  is 7 days old, the same window as the root `pyproject.toml`'s
  `exclude-newer`: a package lands only once the window admits it. A
  `minimumReleaseAgeExclude` entry, an override, or a peer-range exception is
  the owner's decision, never an implementer's.
- `strictDepBuilds` fails the install when a dependency wants a lifecycle
  script. Each `allowBuilds` entry is a reviewed exception with a comment saying
  what the script does and why: `false` when the package works without it,
  `true` only with the owner's sign-off, like a new package.
- `package.json` and `pnpm-lock.yaml` move in the same commit.
