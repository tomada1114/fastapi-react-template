# Reviewing dependency PRs

Read this before approving any PR at Step 2 — this is the point of the gate, not a
formality. Step 4 repeats this review whenever a head changes:

- Read the complete current diff. For an approved plan, verify the content still fits
  its Actions, versions and unit completion.
- GitHub Actions bumps must remain **SHA-pinned with a version comment**
  (`uses: owner/repo@<40-hex SHA> # vX.Y.Z`). A diff that replaces a SHA pin with a
  floating tag is a regression — hold it. The zizmor job (`Workflow Security Lint`) and
  the `zizmor` pre-commit hook audit workflows, so such a PR should already be red.
- Check that the SHA belongs to the tag in the comment: `gh api
  repos/<owner>/<repo>/commits/<sha> -q .sha` resolves, and `gh release view <tag>
  --repo <owner>/<repo>` names the same commit. A comment that disagrees with its SHA
  is held.
- For a major bump, read the upstream release notes before approving:
  `gh release view <tag> --repo <owner>/<repo>` or the changelog link in the PR body.
- Treat a **minor change of a `0.x` Action as major risk**. The survey reports it as
  `major` with the `pre_one_minor` flag; call it out and read the release notes.
  Inspect each member of a grouped PR when its title carries no versions.
- A bump that changes anything under `.github/workflows/` beyond the `uses:` lines —
  a new input, a new step, a changed `permissions:` block or trigger — is changing
  _what_ runs rather than _which version_ runs, and goes to "Stop and ask".
- Every pin of the same Action moves together — SKILL.md Step 2.

## `pre-commit` PRs

- Read every remote hook's changed `rev:` and upstream release notes, including
  grouped PR members. Verify the repository and hook IDs are unchanged.
- A hook update changes only its revision. Changes to arguments, file selection,
  stages, or language need a separate decision.
- Run the hooks on all files. CI runs typos and zizmor through these same revisions.

## `uv` PRs

A `dependabot/uv/...` PR moves Python dependencies. Review it as closely as an Action:

- A `uv` PR always moves `uv.lock`, and moves a manifest too when it raises a range:
  `backend/pyproject.toml` for a runtime package or a package in an extra, the root `pyproject.toml`
  for the `dev` group; a grouped PR may move both. A manifest change arrives with the
  `uv.lock` that `uv lock` generated for it, in the same PR; a manifest change without
  its lock is held. A `uv.lock`-only change is a lock refresh inside the existing ranges.
- In either manifest, only the `>=X.Y` lower bound of a dependency that already exists
  under `backend/pyproject.toml`'s `[project] dependencies` or
  `[project.optional-dependencies]`, or the root's `[dependency-groups]`, may change. An
  existing extra's lower bound is reviewed like a required one's: `uv.lock` pins both.
  A new entry, a removed one, a new or removed extra, or anything under `[tool.*]` —
  `exclude-newer` included — goes to "Stop and ask".
- No gate installs an extra: CI syncs `--group dev` and `just install` `--all-groups`,
  and `uv sync` includes an extra only when asked (`--extra <EXTRA>`, "Include optional
  dependencies from the specified extra name"; `uv sync --help`, observed 2026-10-09).
  So green CI says nothing about a package that only an extra brings in. Before
  approving a bump of one, run the backend suite with that extra on a checkout of the PR
  head, `uv run --locked --extra <name> --directory backend pytest`, and hold the PR if
  it fails.
- In `uv.lock`, what matters is that no `[[package]]` appears that the base did not
  lock: that is a new package, transitive or not — "Stop and ask", with
  `managing-dependencies`' review record. These changes are expected and fine:
  - an upgraded package's `version`, `sdist`, and `wheels`;
  - its own `dependencies` and their markers, as the new release declares them;
  - the `my-app` workspace member's `[package.metadata]` `requires-dist`, rewritten
    when a range in `backend/pyproject.toml` moves, and `[manifest.dependency-groups]`,
    rewritten when a `dev` range in the root `pyproject.toml` moves;
  - a `[[package]]` dropping out because nothing requires it any more.

  A change under `[options]` is "Stop and ask".
- `[tool.uv] exclude-newer-package` holds no entry whose timestamp is older than the
  14-day window. Such an entry is stale — its fix is already inside the window — and
  it freezes that package at its date, so Dependabot's proposals for it fail. Put its
  removal (comment included, then `uv lock`) in the plan as its own change; this review
  is the trigger that drops it (`managing-dependencies`).
- CI's `uv sync --group dev --locked` passed on the current head — every job that
  installs the project starts with it,
  and it refuses a lock that disagrees with either manifest. `uv lock --check` (the
  first step of `just verify`) passes on a checkout of that head.
- List every `version =` change of a grouped PR. A 0.x minor among them (`ruff`) is a
  major risk: read its changelog or release notes before approving.
- A `ruff` bump is shared by the local system hooks and CI through `uv.lock`;
  no companion hook revision changes — SKILL.md Step 2.
