# Landing the approved dependency plan

Use this after the exact plan in SKILL.md is approved. Keep each remote action within
that recorded scope and follow `AGENTS.md`'s "Security and human approval".

## Individual PRs

Process approved PRs in ascending number, one at a time. Immediately before each merge,
verify its current head, repeat SKILL.md's Step 2 review if that head changed, and check
the complete required check set, feedback and required approvals. Confirm the merged
state and landed commit afterwards.

An earlier approved merge can leave a later approved PR behind the base. Request the
necessary bot rebase covered by the plan, then observe the changed head. Apply Step 4's
review and approval-scope comparison before accepting its new checks. The planned
comment is:

```text
@dependabot rebase
```

That comment is a request, not a successful rebase. Never merge on checks for its old
head. A rerun is allowed only for the run/job and reason the plan covers; a newly
needed one requires fresh approval.

Every merged `uv` PR leaves the next one's `uv.lock` stale, so `uv` PRs land this way
one after another: merge, wait for Dependabot to rebase the next PR on its own (it re-runs
`uv lock`), request that rebase with the comment above only if it has not happened,
review its new head, and only then merge it.

## Combined PR

Start an owned, clean branch (or worktree) from the current default-branch commit.
Record the base and the exact approved Actions and versions. Read each approved PR's
full diff to learn the intended changes; do not integrate its commits or resolve a
conflict by picking whichever version is higher.

Apply one approved change at a time:

- For an Action, edit only the approved `uses:` pins — every occurrence of that Action
  across `.github/workflows/` — copying the full new SHA and the `# vX.Y.Z` version
  comment from the reviewed PR exactly. Changes to permissions, triggers, secrets or
  source require the separate decision in SKILL.md.
- For a pre-commit hook approved in the plan, set its `rev:` in
  `.pre-commit-config.yaml` to the reviewed revision. Nothing else in that file changes.
- For a `uv` package the plan puts on the combined branch, apply the reviewed PR's
  range change to `backend/pyproject.toml` or the root `pyproject.toml`, if it has one,
  by hand, then regenerate the lock with `uv lock --upgrade-package <package>==<version>` for
  each approved package and version. A `python-minor-patch` group holding `ruff` moves
  whole: every member and every range edit the group PR made; the
  group PR closes as superseded only after the combined PR merges. `uv.lock` is never
  hand-edited and never taken
  from a bot branch, and the window still applies. A `[[package]]` the regenerated
  lock adds that the reviewed PR did not is a new package: SKILL.md's "Stop and ask".

### Verify and publish

```bash
just verify
uv run --locked pre-commit run --all-files
```

`just verify` is the non-mutating gate; the pre-commit run adds what it does not cover
for a workflow change — the `zizmor` workflow audit, `typos`, and YAML checks. Apply only
settled mechanical fixes inside the approved scope. A migration, new dependency,
changed supply-chain decision or weakened check is not such a fix.

Commit with the normal hook, inspect the committed tree, and push only the approved
branch. Open or update its PR against the recorded default branch with a Conventional
Commit title (`chore(deps): …`) and `.github/PULL_REQUEST_TEMPLATE.md`, labelled
`dependencies` — the PR-title check skips that label, but a valid title keeps the
history consistent. Include the exact approved original PRs, Action versions and unit
completion, the pin review, executed checks, release-note findings, and the approved
stopping point.

Wait for all required current-head CI, review and approval evidence. A correction push
invalidates the previous head's evidence. Diagnose a required failure instead of waiting
passively; a new rerun or decision outside the plan needs fresh approval.

## Confirm landing before closing originals

For an approved merge, re-read the head and default branch at the landing boundary;
merge only the verified head and confirm the returned merge commit and PR state. An
approved PR-only run leaves the combined PR and originals open.

After a confirmed combined merge, close only the approved superseded originals with a
pointer to the combined PR, then delete only branches the plan authorized. Confirm each
closure and deletion. If the combined PR remains open or is abandoned, leave the
originals open. Report partial cleanup separately from a successful merge.
