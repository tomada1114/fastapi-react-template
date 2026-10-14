# Frontend Guide

The React app: a pnpm workspace member built with Vite and TypeScript, routed
by TanStack Router, caching server state with TanStack Query, styled with
Tailwind CSS 4, linted and formatted by Biome, type-checked by `tsc`, and
tested by Vitest. This file
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

Every command here runs from the repository root. Run the narrowest
check that can fail while iterating, then `just verify` before a completion
claim.

| What you changed | The narrowest check that can fail |
|---|---|
| A file's formatting or lint | `just frontend lint` (`just frontend fmt` applies Biome's fixes) |
| Types, or `tsconfig.json` | `pnpm --dir frontend exec tsc --noEmit` |
| One test file | `pnpm --dir frontend exec vitest run tests/<name>.test.tsx` |
| Anything under `src/`, or `vitest.config.ts` | `just frontend test` (the coverage floor) |
| `vite.config.ts`, `index.html`, or anything the bundle includes | `just frontend build` |
| A route file under `src/routes/` (added, renamed, removed) | `just frontend build`, then `git add` the regenerated `src/routeTree.gen.ts` |
| The whole frontend | `just frontend lint && just frontend test` |

`just frontend dev` is the developer's Vite server, human-run: an agent never
starts, stops, or restarts it, and never binds 5173. To see the screen served,
an agent runs its own `just dev` pair on free ports instead (the root
`AGENTS.md`'s Quick Reference, `running-the-app`).

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
├── src/
│   ├── main.tsx          # The entry point: QueryClientProvider around RouterProvider
│   ├── router.ts         # createAppRouter(queryClient, options?) and the Register declaration
│   ├── routeTree.gen.ts  # Generated from routes/ by the router plugin; committed, never hand-edited
│   ├── routes/           # File-based routes: __root.tsx (the layout), index.tsx (/)
│   ├── features/         # Screens and components grouped by feature (todos/)
│   ├── lib/              # Cross-feature query policy and Problem Details helpers
│   └── styles.css        # `@import "tailwindcss";`, imported by main.tsx only
└── tests/            # Vitest tests (*.test.ts, *.test.tsx), mirroring src/, and setup.ts
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
  inside `node_modules`. It skips checking every declaration file (`*.d.ts`),
  so add none under `src/` or `tests/`; their `.ts` and `.tsx` files are
  still fully checked, the matchers' types included. Drop it once jest-dom
  ships Vitest 5 types.
- `typescript` stays on `~6.0.3`: moving to 7.x waits for the API client
  generator to support it.

## Routes, the generated client, and screens

How a screen is built — its route and feature, server data through the generated
client, API errors, styling, accessibility, and its component tests — is the
`building-screens` skill's: load it for any change under `src/routes/`,
`src/features/`, or `src/lib/`. Every frontend task keeps these rules:

- **`src/routeTree.gen.ts` is generated and committed.** `@tanstack/router-plugin`
  (in `vite.config.ts`, before `react()`) rewrites it whenever Vite, Vitest, or
  the build runs; never edit it by hand. Its header is replaced so it carries
  no `@ts-nocheck`: `tsc` checks it under the full strict flag set, and a tree
  that fails to type-check is reported, never silenced. Biome skips it
  (`files.includes`), and coverage already excludes it.
- **A route change is staged together with its regenerated tree.** After
  `just frontend build`, the recipe fails, naming the file, when
  `src/routeTree.gen.ts` is untracked or differs from the Git index; the build
  has already rewritten it, so review it and `git add` it. The check reads the
  index, so a staged tree passes before it is committed, and in CI's clean
  checkout the index is the pushed commit.
- **Never edit `src/api/generated/`.** Change the backend and run `just contract`.
  `just contract-check` generates into a temporary directory and rejects drift
  without changing checkout files. Only the bundled `generated/client/` and
  `generated/core/` runtime carries the owner-approved `@ts-nocheck` exception:
  hey-api 0.99.0 fails `exactOptionalPropertyTypes` there. Generated types, SDK,
  query options, and handwritten code keep every strict flag; the scope gate
  in `just frontend lint` also verifies newly generated output during the contract check.
  `generate-api.ts` corrects the pinned generator's nullable infinite-page branch
  and supplies the required single-page defaults without suppression directives.
  Consumers override `getNextPageParam` with their response-specific cursor rule.
- Vite's development server proxies `/api` and `/healthz` to the loopback API.
  `MY_APP_API_PORT` selects that target port (default 8000); the API must be bound
  to the same port. `VITE_PORT` selects Vite's port (default 5173), with strict
  binding. These are process variables, not backend `Settings` or dotenv keys.

## Tests and the coverage floor

- `just frontend test` fails when lines, functions, statements, or branches
  fall below 80% over `src/**/*.{ts,tsx}` — the backend's bar. The only
  exclusions are generated code, `src/api/generated/**` and
  `src/routeTree.gen.ts`; anything else untested is covered by a test, never
  excluded. Lowering a threshold or widening the exclusions weakens a gate.
- `.only` fails the run (`allowOnly: false`), and mocks, stubbed globals, and
  stubbed environment variables are restored after each test.
- One test file runs with
  `pnpm --dir frontend exec vitest run tests/<name>.test.tsx`; the whole suite
  and its floor with `just frontend test`.
- Where a test, a fixture, or an MSW handler goes is `placing-tests`'; how a test
  is written (queries, user-event, matchers, MSW, no `.only`) is `writing-tests`';
  how a screen's test uses them is `building-screens`'.

## Dependencies

A new package — runtime or dev — needs the owner's sign-off and a review record
before `pnpm add` runs, and `package.json` moves with `pnpm-lock.yaml` in one
commit. How it lands (`pnpm --dir frontend add`, `--save-dev` for a dev
dependency), the 7-day `minimumReleaseAge` window, and every
`pnpm-workspace.yaml` exception (`minimumReleaseAgeExclude`,
`trustPolicyExclude`, `allowBuilds`, overrides) are `managing-dependencies`'
(`references/pnpm.md`).
