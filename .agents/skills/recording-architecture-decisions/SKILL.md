---
name: recording-architecture-decisions
description: >
  Covers the ADR tree under docs/architecture/: its README.md index, adr/template.md,
  and the numbered adr/NNNN-*.md records. Use when a change adds a runtime dependency,
  a new top-level package or layer under backend/src/, a persistence or data format
  choice, an external service or network boundary, a change to requires-python, or a
  distribution change; when proposing, accepting, amending, rejecting, or superseding
  an ADR; when writing a version, an availability, a price, or a vendor policy into a
  document; or when deciding whether a change owes an ADR at all.
---

# Recording Architecture Decisions

**Owns:** `docs/architecture/` — whether a change owes an ADR or a status change, an
ADR's shape, numbering, and statuses, amending versus superseding, keeping the index
true, and how a fact is written into any of it. **Does not own:** the project's
direction (`steering-the-roadmap`, which owns `docs/architecture/roadmap.md`); how a
skill is written (`authoring-skills`); whether a dependency may be added
(`managing-dependencies`); the decisions themselves — those are the ADRs.

## What the tree is for

- `docs/architecture/README.md` is the index: the status legend, how an ADR changes,
  and one row per ADR with its status.
- `docs/architecture/adr/template.md` is the shape every ADR copies.
- `docs/architecture/adr/NNNN-<kebab-case-title>.md` records one decision each.

`backend/AGENTS.md`'s "Architecture" section describes the app's layout every project
starts with. It is not an ADR and takes no status: when an ADR moves a boundary it
describes, the ADR records why and the "Architecture" section is updated to describe
the result, in the same pull request.

<!-- template-only -->
## The template or a project

The template repository ships the index empty, on purpose. Its own reasoning lives in
`TEMPLATE.md`'s "Design Philosophy", and ADRs belong to the projects cut from it. So:

- In the template itself, before `scripts/bootstrap.py` has renamed it, a change that
  hits a trigger below updates `TEMPLATE.md`'s "Design Philosophy", not the tree. Never
  seed the template's index with an ADR.
- In a project, the same change owes an ADR.
<!-- /template-only -->

## When a change owes an ADR

A decision owes one when it is expensive to reverse, or when someone outside the change
will build on it. The triggers, each with why it is expensive:

- **A runtime dependency** — a package under `[project] dependencies` is installed by
  every user and constrains every later upgrade; the review record in
  `managing-dependencies` is the evidence the ADR cites. A dev-only tool in
  `[dependency-groups]` owes none unless it changes a gate.
- **A package boundary** — a new top-level package or layer under `backend/src/`, or a
  change to what may import what. It fixes a dependency direction every later module
  obeys.
- **The public contract** — what `__init__.py`'s `__all__` promises, or the shape of a
  CLI command, an HTTP route, or a file format other programs read. Callers outside the
  repository build on it, so a change later is a breaking release.
- **Persistence** — where and in what format state lives (files, SQLite, a database
  server, a cache). Stored data outlives the code that wrote it, so a change later is a
  migration.
- **An external service** — a network API, a cloud provider, a message queue — and how
  its credentials reach the process. It decides failure modes, cost, and what a test
  must fake.
- **`requires-python`** — the interpreter floor in `backend/pyproject.toml`. Raising it
  drops users; every syntax and library choice below it assumes it.
- **Distribution** — a wheel on a package index, a container image, a tool installed
  with `uv tool`, a hosted service. It constrains packaging, the release workflow, and
  what a user must have installed.

A refactor inside a module, a test, a rename that crosses no boundary, or a fix that
restores what an ADR already says owes none. Saying so in the pull request is a
legitimate outcome, not a skipped step. The test to apply: if a reviewer a year from now
would ask "why is it like this?" and the code cannot answer, the answer belongs in an
ADR.

An ADR records reasoning; it grants nothing. A new dependency or a remote write still
needs the sign-off `AGENTS.md`'s "Security and human approval" asks for, whether or not
an ADR exists.

## Shape and statuses

- Copy `adr/template.md` to `adr/NNNN-<kebab-case-title>.md` with the next free number.
  Numbers start at `0001` and are never reused, even for a rejected proposal. Keep the
  template's section order; a section with nothing to say says "None.".
- Statuses run **Proposed** (recommended, awaiting the owner) → **Accepted** (the owner
  confirmed it) → **Superseded by ADR-NNNN**, with **Rejected** for a proposal the owner
  declined. A partly settled decision says which part is which ("Accepted: SQLite as
  the store. Proposed: the table layout.").
- Only the owner accepts or rejects. An agent writes Proposed, names what acceptance
  needs, and edits a Proposed ADR freely until the owner decides.
- An Accepted ADR takes small corrections in place — a re-checked fact, a clarified
  consequence, a follow-up that landed — each recorded as an `Amended YYYY-MM-DD` line
  under the status saying what changed. If the correction would change what was
  decided, it is not small.
- A decision that is replaced gets a new ADR that says what it replaces and why. The old
  one changes only its status line to `Superseded by ADR-NNNN`, with a link forward; its
  body stays as it was, so the reasoning that held at the time is still readable.
- Update `docs/architecture/README.md`'s table in the same change as the ADR — a new
  row, or a changed status.

## Fact discipline

Keep three kinds of statement apart, in every file of the tree:

- **Verified fact** — every external claim carries a primary-source URL and
  "checked YYYY-MM-DD", listed in the ADR's Sources section. Check it against the
  source itself, never from memory: the Python documentation or a PEP for a language or
  standard-library behavior; a package's own repository, release page, and
  `pyproject.toml` for its version, license, and Python floor; a provider's own
  documentation for a service's limits and prices.
- **Decision or recommendation** — its reason and the alternatives it beat.
- **Unverified** — prefixed `Unverified:` and listed under the ADR's Open questions. It
  leaves that list only by being verified (and cited) or by deleting the claim that
  needed it. Never fill a gap from memory to complete a table.

The facts an ADR here leans on move: the Python version a feature needs, a package's
latest release or license, a provider's price or rate limit. A price carries its unit
and date; availability and deprecation carry the version and date. An ADR is read by
people judging the design, and one confidently wrong fact costs the credibility of every
correct one beside it.

## Public-repository hygiene

Nothing in the tree carries a credential, an API key, an account ID, a private hostname,
an unannounced product name, a personal name or email, or any user's data. Call the
person who decides "the owner". The secret rules are `AGENTS.md`'s "Security and human
approval"; this is their application to prose.

## Writing

English, per `AGENTS.md`'s "Overview". Spend words on trade-offs and on what
the code cannot say; do not restate it. Name a module, a symbol, or a `pyproject.toml`
key rather than a `path:line`, which rots with the next edit. Keep sketches small enough
to check by eye — a `Protocol`, a table layout, a config shape — because nothing runs a
fenced block in these documents. `typos` spell-checks the tree; nothing formats
Markdown, so wrap prose by hand.
