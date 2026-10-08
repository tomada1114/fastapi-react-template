# Architecture Decisions

This tree records the decisions a project cut from this template makes on top of the
layout it starts with, one Architecture Decision Record (ADR) per decision, and why each
was made. It is written for anyone reviewing the design — including the owner six months
from now — and assumes no context beyond the repository.

Three places hold the reasoning, and each has one job:

- `AGENTS.md`'s "Architecture" section describes the layout every project starts with —
  the `src/` package layout and where new code goes. It is
  the ground the ADRs build on, not a record of choices.
<!-- template-only -->
- `TEMPLATE.md`'s "Design Philosophy" holds the template's own reasoning: why the `src/`
  layout, strict mypy and Ruff, Just, the coverage floor. The template ships no ADRs of
  its own, and `scripts/bootstrap.py` deletes `TEMPLATE.md` from a new project.
<!-- /template-only -->
- `.template-origin` identifies the template repository and revision for an app
  that needs to look up the original layout rationale.
- The ADRs below record what the project decided after that: its runtime dependencies,
  its package boundaries, where it keeps state, which services it talks to, its Python
  floor, and how it ships.

`recording-architecture-decisions` is the skill that names the changes owing an ADR and
writes one.

Beside the ADRs, [`roadmap.md`](roadmap.md) records the project's direction — which
outcomes come now, next, and later — and links the issues and ADRs each one needs. It is
not an ADR: it takes no status and no number, has no row in the table below, and
authorizes nothing. The template ships it as a skeleton; `steering-the-roadmap` is the
skill that changes it.

## Status legend

| Status | Meaning |
|---|---|
| Proposed | A recommendation with its reasoning, not yet confirmed by the owner. Work may start on it only as an experiment. |
| Accepted | Confirmed by the owner. Work builds on it. |
| Rejected | Declined by the owner. Kept, with its number, for the reasoning. |
| Superseded | Replaced by a later ADR, which it names. Kept for the reasoning, never edited into agreement. |

## How an ADR changes

- A Proposed ADR is a draft: edit it freely until the owner decides.
- It becomes Accepted, or Rejected, when the owner confirms; the change is a one-line
  edit to its status, with the date.
- An Accepted ADR takes small corrections in place — a re-checked fact, a clarified
  consequence, a follow-up that landed — each recorded as an `Amended YYYY-MM-DD` line
  under its status saying what changed. What it decided stays the same.
- A decision that is replaced gets a new ADR. The old one becomes
  `Superseded by ADR-NNNN`, gains a link forward, and is otherwise left as it was.
- Numbers run from `0001` and are never reused, even for a rejected proposal.

## Adding an ADR

1. Copy [`adr/template.md`](adr/template.md) to `adr/NNNN-<kebab-case-title>.md`, using
   the next free number.
2. Fill it in, with status Proposed.
3. Add its row to the table below in the same change.

## Decisions

<!-- template-only -->
The template ships this table empty: its own reasoning is in `TEMPLATE.md`'s Design
Philosophy.
<!-- /template-only -->
The first row is the project's first ADR.

| ADR | Decision | Status |
|---|---|---|
