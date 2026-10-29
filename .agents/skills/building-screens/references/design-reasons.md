# Why the frontend is built this way

Read before a design change to the frontend: another package manager or runtime, a
different test runner or linter, or reading server data some way other than through the
generated client. `SKILL.md` and `frontend/AGENTS.md` hold the rules; this page holds
what each choice protects and the alternative it rules out. Rewrite the reason here in
the same pull request that changes the choice.

## pnpm, Node.js 24, and Vitest rather than Bun

The rule is compatible and simple, with no workarounds. Bun as installer, runtime, and
test runner was weighed against pnpm 11 on Node.js 24 with Vitest, and lost on each of
these:

- Claude Code cloud sessions document proxy problems with Bun's package fetching
  ([cloud environments](https://code.claude.com/docs/en/cloud-environments), checked
  2026-10-14).
- GitHub's dependency graph lists `pnpm-lock.yaml` but no Bun lockfile, so Dependency
  Review and Dependabot alerts could not cover a Bun graph
  ([graph ecosystems](https://docs.github.com/en/code-security/reference/supply-chain-security/dependency-graph-supported-package-ecosystems),
  checked 2026-10-14).
- Vite, Vitest, Playwright, and the client generator document Node.js as their runtime
  ([Vite](https://vite.dev/guide/), [Vitest](https://vitest.dev/guide/),
  [Playwright](https://playwright.dev/docs/intro),
  [Hey API](https://heyapi.dev/docs/openapi/typescript/get-started), checked 2026-10-14).
- `bun test`'s documented coverage thresholds cover lines and functions, so it cannot
  enforce the frontend's branch floor
  ([Bun coverage](https://bun.sh/docs/test/code-coverage), checked 2026-10-14).

How the toolchain is pinned and fetched is `frontend/AGENTS.md`'s "Toolchain"; what the
package manager enforces on every install is `managing-dependencies`.

## Biome and strict `tsc` rather than ESLint and Prettier

Biome lints and formats from one configuration, with none of the plugin peer-range
exceptions an ESLint and Prettier setup needs. Many of Biome's type-aware rules are
still in its nursery group
([Biome types rules](https://biomejs.dev/linter/domains/#types), checked 2026-10-14),
so `tsc --noEmit` under the strict flag set carries type safety, and Biome is not asked
to.

## A committed contract and a generated client

A hand-written client drifts from its server one field at a time. `just contract`
instead exports `create_app().openapi()` without starting a server and commits the JSON
together with the generated fetch SDK and TanStack Query options, and
`just contract-check` fails on drift. The backend stays the validation authority; the
screen renders its Problem Details field errors rather than repeating its rules. A
correction the pinned generator needs (pagination, query keys, a 204 response) lives in
`frontend/generate-api.ts`, never as a hand edit to the output, so regeneration keeps
it. Why `typescript` stays on `~6.0.3` and where the one `@ts-nocheck` exception sits:
`frontend/AGENTS.md`.
