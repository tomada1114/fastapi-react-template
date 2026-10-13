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
├── src/
│   ├── main.tsx          # The entry point: QueryClientProvider around RouterProvider
│   ├── router.ts         # createAppRouter(queryClient, options?) and the Register declaration
│   ├── routeTree.gen.ts  # Generated from routes/ by the router plugin; committed, never hand-edited
│   ├── routes/           # File-based routes: __root.tsx (the layout), index.tsx (/)
│   ├── lib/              # App-wide helpers: query-client.ts (the retry policy)
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

## Routing, server state, and styling

- **Routes** live in `src/routes/`, one file per route, under TanStack Router's
  file-based conventions: `__root.tsx` is the layout every page renders inside
  (a `<header>` and an `<Outlet />`), `index.tsx` is `/`. Its root route is
  made with `createRootRouteWithContext`, so every loader reads the query
  client from `context.queryClient`.
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
- **Server state goes through TanStack Query**, with the client from
  `src/lib/query-client.ts`'s `createQueryClient()`. `main.tsx` creates one and
  hands the same instance to `QueryClientProvider` and `createAppRouter`; a
  test creates its own. The retry policy (`shouldRetry`): a query whose error
  carries a numeric `status` in 400-499 is never retried (the same request
  gets the same answer); any other failure — a 5xx, a network error with no
  `status` — is retried once. Mutations keep TanStack's default of no retry,
  and every other option stays TanStack's default. An API error type sets
  `status` for this policy to read.
- **Never edit `src/api/generated/`.** Change the backend and run `just contract`;
  import query and mutation options from `src/api/generated/@tanstack/react-query.gen`.
  `just contract-check` generates into a temporary directory and rejects drift
  without changing checkout files. Only the bundled `generated/client/` and
  `generated/core/` runtime carries the owner-approved `@ts-nocheck` exception:
  hey-api 0.99.0 fails `exactOptionalPropertyTypes` there. Generated types, SDK,
  query options, and handwritten code keep every strict flag; the scope gate
  in `just frontend lint` also verifies newly generated output during the contract check.
  `generate-api.ts` corrects the pinned generator's nullable infinite-page branch
  and supplies the required single-page defaults without suppression directives.
  Consumers override `getNextPageParam` with their response-specific cursor rule.
- **Tailwind CSS 4 is the only styling layer**, through `@tailwindcss/vite`:
  utility classes in the markup, and `src/styles.css` (`@import "tailwindcss";`)
  imported by `main.tsx` alone. No CSS modules, CSS-in-JS, other stylesheets,
  or UI kit. Biome parses Tailwind's directives (`css.parser.tailwindDirectives`).

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
- `pnpm-workspace.yaml`'s `trustPolicyExclude` holds one owner-approved
  exception (2026-10-13, #20): `semver@6.3.1`, which lacks the provenance
  earlier semver releases carry, so `trustPolicy: no-downgrade` refuses it.
  Only `@tanstack/router-plugin`'s Babel 7 reaches it. Drop the entry once 6.3.1
  regains provenance or nothing reaches for `semver@6` (the plugin moves to
  Babel 8). Any other trust exception is a new owner decision.
- `strictDepBuilds` fails the install when a dependency wants a lifecycle
  script. Each `allowBuilds` entry is a reviewed exception with a comment saying
  what the script does and why: `false` when the package works without it,
  `true` only with the owner's sign-off, like a new package.
- `package.json` and `pnpm-lock.yaml` move in the same commit.
