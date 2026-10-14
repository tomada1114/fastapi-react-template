# About This Template

This is a FastAPI + React full-stack template: a to-do screen, an async HTTP API,
and SQLite persistence, with the checks needed to extend a fresh copy. This file
explains the template's choices; `scripts/bootstrap.py` deletes it from an app.
The [tracking issue](https://github.com/tomada1114/fastapi-react-template/issues/3)
holds the owner's decisions. The Python-only sibling,
[`tomada1114/uv-template`](https://github.com/tomada1114/uv-template), remains the
starting point for command-line tools and API-only services.

## Using This Template

Follow the `starting-an-app` skill (`.agents/skills/starting-an-app/SKILL.md`,
mirrored to `.claude/skills/`): "Use this template", bootstrap the copy, fill its
Product section, then `just install` and `just dev` for the screen and API.
Its `references/bootstrap.md` owns the rename procedure; its GitHub settings
reference marks the owner-only steps. A fresh-copy CI smoke test runs the
bootstrap, verification and browser test (merged PR #134).

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

## Design Philosophy

Each section gives the alternatives, the current choice and its reason. D1-D17
refer to the decisions in the tracking issue; merged code is the current shape.

### Why a separate full-stack template? (D1)

Rather than rewrite the Python-only sibling or start with an empty repository,
this repository was generated from `tomada1114/uv-template` at `10d6ae5`.
It retains that template's harness while giving browser applications their own
starting point. References to the sibling's issues use the full
`tomada1114/uv-template#NN` form so their repository stays unambiguous.

### Why backend and frontend workspaces? (D2)

A root Python app plus `web/`, and an `apps/api` + `apps/web` layout were considered.
The choice is `backend/` and `frontend/`, with root uv and pnpm workspaces; `e2e/`
is another pnpm member. Each area has its own manifest, guide and narrow checks.
A later infrastructure member can join without moving the app again.

### Why `backend/src/` layout?

A package at the repository root can accidentally satisfy imports from the working
directory. `backend/src/my_app/` instead requires installing the app, so a missing
module or broken package configuration fails during testing. The root holds the
harness; `backend/` holds the application.

### Why an async call path? (D3)

Rather than mix synchronous services with async adapters, ports, services, routes
and repositories are `async def`. The SQL drivers and engine need that path;
future outbound calls can use real cancellation and concurrency without replacing
the domain interfaces. Tests use AnyIO's pytest integration. This is a storage and
extension choice, with no model-provider layer required.

### Why a framework-free core? (D5)

Putting API schemas or database models in the core would tie domain rules to their
entry point or storage. The core instead imports the standard library and itself:
values are frozen dataclasses, ports are `typing.Protocol`s, and the composition
root wires adapters into services. Pydantic belongs at the API/settings edges.
Ruff's banned-api rules and import tests keep that boundary explicit.

### Why SQLAlchemy Core, Alembic and store-independent ports? (D4)

No persistence, SQLModel/ORM entities, and a PostgreSQL-first Docker setup were
considered. The choice is SQLAlchemy's asyncio Core API with explicit tables and
statements inside the SQL adapter, plus Alembic revisions. SQLite with `aiosqlite`
is the local default; PostgreSQL with the optional `asyncpg` extra runs the same
contract and migration tests in CI. An app keeps data from its first feature,
without needing Docker for its first run or passing database objects into its core.

The ports preserve six rules: application-generated UUIDv7 ids; one method per
access pattern; opaque cursor pages rather than offsets; domain values rather than
ORM/row/query types across the boundary; one method for an atomic multi-item write;
and timezone-aware timestamps. D4 specifies UTC: the default clock returns UTC and
SQL storage normalizes to it. The current Clock/domain contract accepts any aware
offset, however, and the in-memory adapter preserves it; UTC is not an enforced
invariant across every port implementation. These rules keep a later key-value
adapter possible. The DynamoDB recipe is deferred in #38; it is not shipped here.

Migrations run explicitly through `just backend db-upgrade` (also before the dev
server), rather than at app startup or through `create_all`: missing revisions
stay visible and simultaneous startups do not race to alter the schema.
`persisting-data` owns the procedure. The selected PostgreSQL driver is Apache-2.0;
psycopg's LGPL license does not fit the runtime license allowlist
([asyncpg](https://pypi.org/project/asyncpg/0.31.0/),
[psycopg](https://pypi.org/project/psycopg/), checked 2026-10-09).

### Why callback-only process-resource ownership?

A Container outlives individual requests and owns lazy process resources such as the
SQL engine. `ResourceClosers` therefore accepts disposal callbacks that can run on the
resource's event loop in a separate Task/Context. This lets one cleanup task finish
under both cancellation scopes and direct task cancellation, while concurrent callers
wait for the same LIFO drain. Cancellation propagates after disposal; cleanup failures
run the remaining callbacks and then propagate.

An entered context manager can carry ownership of its caller's task, cancellation
scope, or context-variable token. Transferring its exit to the cleanup task breaks that
ownership. Those managers belong in the acquiring caller's scope instead. This is an
intentional change from accepting a generic `AsyncExitStack`: the Container rejects
that stack at construction, seals callback registration when it takes ownership, and
never suppresses a body exception. Preserving arbitrary manager entry and suppression
would leave the cancellation guarantee dependent on hidden adapter behavior. The
owner chose the explicit ownership boundary in issue #95.

### Why no LLM layer or sample? (D6, D12)

Rather than keep a provider adapter or an unused model port, the template leaves
both out. The owner's planned applications choose their own provider; a sample
would be code each deletes, and an unexercised port would guess their needs. An app
adds its own port and adapter under `designing-core-logic` and rewrites its present
state design description. AWS/CDK, deployment, Dockerfiles, auth, SSE, i18n, a UI kit,
a form library and OpenTelemetry are also outside the template's scope.

### Why an HTTP contract shaped for a browser? (D7)

Instead of client-specific error parsing and unstable generated names, resource
routers live under `/api`, `/healthz` stays at the root, and each operation id is
its route function's name. Errors use RFC 9457 Problem Details
(`application/problem+json`) with `type`, `title`, `status`, `detail`, a stable
`code`, and `request_id`; request parsing failures add `errors` entries with
`loc`, `message` and `type`. Unhandled failures return generic details while server
diagnostics are sanitized. The format follows
[RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html) (checked 2026-10-14).
An empty `MY_APP_CORS_ORIGINS` adds no CORS middleware; the development proxy needs
none, while an app can configure origins when it serves the API separately.

### Why pnpm, Node 24, Vitest and Biome? (D8)

The owner first chose bun for installation, running and testing, then chose pnpm 11,
Node 24 and Vitest under the rule "compatible, simple, no workarounds". The reasons
recorded in [#3 D8](https://github.com/tomada1114/fastapi-react-template/issues/3)
(2026-10-08) are:

- Claude Code cloud documents Bun proxy problems for package fetching
  ([cloud environments](https://code.claude.com/docs/en/cloud-environments),
  checked 2026-10-14).
- GitHub's dependency graph lists `pnpm-lock.yaml` but no Bun lockfile, and the
  decision recorded no Bun security-update support; that prevented relying on
  Dependency Review and Dependabot alerts for a Bun graph
  ([graph ecosystems](https://docs.github.com/en/code-security/reference/supply-chain-security/dependency-graph-supported-package-ecosystems),
  checked 2026-10-14; security-update observation in #3, checked 2026-10-08).
- Vite, Vitest, Playwright and the generator document Node runtime requirements
  ([Vite](https://vite.dev/guide/), [Vitest](https://vitest.dev/guide/),
  [Playwright](https://playwright.dev/docs/intro),
  [Hey API](https://heyapi.dev/docs/openapi/typescript/get-started), checked 2026-10-14).
- The recorded macOS arm64 probe found that MSW 3 did not intercept `fetch` under
  bun 1.4.2 (#3 D8, observed 2026-10-08); this is a probe result, not a claim about
  every subsequent Bun release.
- `bun test` cannot supply this template's branch-coverage floor; its documented
  thresholds cover lines and functions
  ([Bun coverage](https://bun.sh/docs/test/code-coverage), checked 2026-10-14).

The frontend uses React 19, Vite 8, TanStack Router, TanStack Query and Tailwind 4;
Vitest 5 runs with jsdom, Testing Library and MSW 3. Biome handles lint and format
in one configuration, avoiding ESLint + Prettier's plugin peer-range exceptions
(`peerDependencyRules.allowedVersions` in the sibling comparison recorded in #3 D8).
Many type-aware Biome rules are still nursery, so strict `tsc --noEmit` carries type
safety ([Biome types rules](https://biomejs.dev/linter/domains/#types), checked
2026-10-14). `building-screens` owns the conventions.

### Why strict types and lint from the start?

Rather than relax checks for early code and inherit a cleanup backlog, strict mypy
and comprehensive Ruff rules cover Python, while strict tsc and Biome cover the
frontend. Generated code has the narrow exception below. The same constraints
apply whether a human or an agent writes the change.

### Why commit the API contract and generated client? (D9)

A handwritten client can drift from its server. `just contract` instead exports
`create_app().openapi()` without a server, commits the stable JSON plus generated
fetch SDK and TanStack Query options, and `just contract-check` detects drift.
The backend remains the validation authority; the screen can present its Problem
Details field errors. Input-dependent types, SDK and query options stay checked;
only the approved bundled runtime exception remains. The pinned generator's
pagination, query-key and 204 corrections live in generation, not hand edits
(merged PR #108). `building-screens` owns use of the generated options.

### Why one development command and no CLI? (D10, D11)

Starting the API and screen independently invites mismatched origins and forgotten
migrations. `just dev` migrates SQLite, then runs both reload servers as one process
lifecycle: Vite serves the screen on 5173 and proxies `/api` and `/healthz` to the API
on 8000. `MY_APP_API_PORT` and `VITE_PORT` move the pair together.
The removed Typer CLI and `cli/serve.py` added a second entry point without a
product need; operations are recipes and Alembic commands. An app with an admin
command can add Typer deliberately. `running-the-app` owns agent-run observation
on separate free ports.

### Why a browser test on every PR? (D13)

Separate API and component tests cannot show that a built screen talks to the real
server and persists data. Playwright drives Chromium against that pair on free
ports and a disposable SQLite database, including persistence verification.
`just e2e` runs this independently of the developer's servers; CI runs it on every
PR rather than leaving integration failures to a release.

### Why stdlib logging and request ids? (D14)

Rather than add a logging or telemetry dependency, stdlib logging supports text
and JSON through `MY_APP_LOG_LEVEL` and `MY_APP_LOG_FORMAT`. Middleware accepts a
validated `X-Request-ID` or generates one, echoes it, and puts it in logs and
Problem Details. One access record gives method, path, status and duration without
request bodies, query strings or secrets, so failures can be correlated without
collecting sensitive input.

### Why optional backend dotenv settings? (D15)

Requiring shell exports for every local value makes setup cumbersome; putting
secrets in frontend variables exposes them to the browser. pydantic-settings reads
optional `backend/.env` from the backend module location, with `MY_APP_*` environment
values taking precedence. `backend/.env.example` documents the shape. Frontend
`VITE_` values are public, never credentials; README owns the configuration table.

### Why one CI aggregate and shared supply-chain policy? (D16, D17)

Instead of editing the live ruleset for every CI job, `CI result` fails unless all
its gating jobs succeed: backend lint/types and coverage, frontend, PostgreSQL,
spelling, workflow security, contract drift and E2E. The template smoke test runs
separately as a non-required job, so it does not change the ordinary app gates.
PR title, Dependency Review and CodeQL's Python, Actions and JavaScript/TypeScript
checks are separate required contexts. The owner applies the ruleset; #39 records
that settings step as completed. `changing-gates` owns the check list.

Python and JavaScript releases share the 7-day window, with matched monthly
Dependabot cooldowns. pnpm also rejects missing release times, trust downgrades,
exotic subdependencies, peer conflicts and unreviewed install scripts; frozen
installs and `verifyDepsBeforeRun: error` keep execution tied to the lock.
Owner-approved exceptions are narrow and documented in `pnpm-workspace.yaml`.
OSV scans both lockfiles; Dependency Review and Dependabot use GitHub's graph,
whose pnpm 11 limits are recorded below. `managing-dependencies` owns changes.

### Why Just over Make?

Rather than use Make's build-target model, Just expresses development tasks and
area modules directly. The root combines `backend/` and `frontend/` recipes into
one install and verification entry point; individual checks remain available
without copying their command lists into every document.

### Why AGENTS.md and the agent configuration?

Rather than put all instructions in one agent's configuration, root `AGENTS.md`
sets shared agreements and `backend/AGENTS.md` and `frontend/AGENTS.md` add area
rules; `CLAUDE.md` imports the guide. Skills are authored in `.agents/skills/` and
mirrored with `just agents-sync`. Both hosts define four tiers: `executor`,
`architect`, `scout` and `worker`. Permission allowlists, personal model choices,
plugin marketplaces and editor hooks belong to the developer's local settings.

### Why a pre-commit layer instead of agent hooks?

A check in one agent's hook misses other authors. Normal Git hooks instead run the
same staged-secret, lint/type, spelling and mirror gates for every commit, including
Biome and tsc for frontend and E2E changes. The secret gate also runs on merge
commits. Linked worktrees preserve the primary checkout's shared hooks.
`changing-gates` explains the full layers and which history operations do not
invoke them; the weekly gitleaks scan covers committed history.

### Why 80% coverage minimum?

Rather than require 100% or no floor, backend tests require 80% branch coverage;
frontend tests require 80% on lines, functions, statements and branches, excluding
`src/api/generated/**` and `src/routeTree.gen.ts`. This catches untested decisions
while leaving room for code whose exhaustive testing adds little value.
`placing-tests` and `writing-tests` own how to make those tests meaningful.

## Known gaps

- Dependabot documents pnpm v7-v10, while this template keeps pnpm 11 by owner
  decision. A sibling update succeeded (#3 cites
  [nextjs-app-template PR #248](https://github.com/tomada1114/nextjs-app-template/pull/248));
  that does not establish this repository's next update. Record a failed job rather
  than changing the toolchain to work around it
  ([supported ecosystems](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories),
  checked 2026-10-14).
- GitHub lists pnpm lockfiles, but PR #100's review links upstream reports of pnpm
  11's two-document format missing dependency-graph entries. A green check alone
  does not prove frontend graph coverage; OSV's direct lockfile scan stays separate
  ([PR #100](https://github.com/tomada1114/fastapi-react-template/pull/100), checked
  2026-10-14). The graph claim is conditional on actual entries being present.
- TypeScript stays `~6.0.3`: the recorded compiler-API probe crashed generator
  0.99.0 with TypeScript 7. Only generated `client/**` and `core/**` carry approved
  `// @ts-nocheck` for strict optional-property errors; remove it when that runtime
  passes the full flags. The route tree has no exception
  ([PR #108](https://github.com/tomada1114/fastapi-react-template/pull/108), checked
  2026-10-14).
- Claude Code cloud starts with Node 22 on `PATH`. pnpm's `devEngines.runtime`
  downloads and locks Node 24 for project tools: #40 / merged PR #106 records a real
  2026-10-13 session using pnpm 11.18.0 and Node 24.21.0 with install and verification
  passing. Check `pnpm --dir frontend exec node --version`; a failed download is a
  stop, not a reason to ignore the runtime requirement
  ([cloud tools](https://code.claude.com/docs/en/cloud-environments#installed-tools),
  [pnpm runtime](https://pnpm.io/package_json#devenginesruntime), checked 2026-10-14;
  `cloud-claude-shipping-issues/references/cloud-host.md` owns the observed route).
- Dependency Review has `fail-on-scopes: runtime`. #3/#23 expected Python dev-group
  packages outside the license gate, while pnpm dev-scope behavior was unchecked.
  The action documents that option as a vulnerability filter, so that expectation
  is not evidence of license scope. Keep actual development-license coverage
  unverified unless a run demonstrates it. PR #108's successful
  [Dependency Review job](https://github.com/tomada1114/fastapi-react-template/actions/runs/38462477249/job/115520906025)
  listed the direct dev dependency `@hey-api/openapi-ts` from `frontend/package.json`
  but its Licenses group was empty: it did not demonstrate dev-scope or transitive
  license coverage
  ([action documentation](https://github.com/actions/dependency-review-action#configuration),
  [merged PR #100](https://github.com/tomada1114/fastapi-react-template/pull/100),
  checked 2026-10-14).
