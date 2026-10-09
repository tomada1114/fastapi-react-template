---
name: authoring-skills
description: >
  Covers how a skill in this repository is authored under .agents/skills/, mirrored into
  .claude/skills/ by scripts/sync_agents.py, and kept from silently failing to load.
  Use when adding, editing, or reviewing a SKILL.md, running just agents-sync or just
  agents-check, adding a script or test under a skill's scripts/ directory, deciding
  whether new material belongs in AGENTS.md or a new skill, or investigating why a skill
  never fires in Claude Code or Codex CLI.
---

# Authoring Skills

**Owns:** how a skill in this repository is authored, mirrored, and kept from silently
failing to load. **Does not own:** the content of any individual skill; the conventions
for code under `backend/src/` and `scripts/` (`writing-python`, `writing-repo-scripts`);
which document a change owes (`updating-docs`).

## The single source of truth

- Author every skill once, under `.agents/skills/<name>/` — the path Codex CLI discovers
  project skills from. `scripts/sync_agents.py` mirrors that tree into
  `.claude/skills/`, the only path Claude Code reads.
- Both copies are real, committed files. A symlink would work from this checkout but not
  from a fresh clone on every platform, and Codex follows a linked directory into its
  own subdirectories, registering a nested `SKILL.md` as a second, nameless skill.
- Loop: edit the `.agents/` copy, run `just agents-sync`, commit both sides. Never
  hand-edit anything under `.claude/skills/` — the next sync overwrites it silently, and
  a hand edit there drifts from the source it should mirror.
- Drift between the two trees fails `just agents-check` (part of `just verify`),
  `tests/test_sync_agents.py`, the `agents-check` pre-commit hook, and CI's
  `Lint & Type Check` job — all compare the trees byte for byte, not just spot-check
  `name`. The pre-commit hook and `just agents-check` judge the working tree, so a
  commit that stages only one of the two trees still passes there; they match the
  commit only when the tree is clean. CI judges the commit.

## Layout

- Exactly one directory level under `.agents/skills/`: `.agents/skills/<name>/SKILL.md`
  plus optional `references/`, `scripts/`, or asset subdirectories beneath that same
  skill directory. No category subfolders — both hosts and the mirror assume one path
  segment between the skills root and the skill's own files.
- No file below a skill root may itself be named `SKILL.md`. A nested one registers as a
  second, nameless skill in both hosts. Name reference files for their content instead
  (`failure-modes.md`, not another `SKILL.md`).
- No symlinks anywhere under either tree. Enforced by: `scripts/sync_agents.py`, which
  refuses a symlinked skills root or entry.

## Frontmatter

Exactly two keys, `name` and `description`, with `description` written as a folded
block scalar (`description: >`). Do not add any third key — no `paths`, no `globs`, no
`allowed-tools`, no `metadata`, no host-specific extension. Claude Code's own `paths`
field would gate auto-invocation on a glob, but Codex CLI has no such field: it ignores
an unknown key and matches only on `description`. The same skill would then auto-fire
on different terms per host, so a portable skill keeps `description` as its one trigger
surface.

- `name` is byte-identical to the directory name: lowercase letters, digits, and
  hyphens.
- English only, per `AGENTS.md`'s "Overview".
- The description is a retrieval string describing the situation that should load the
  skill (file globs, command names, error strings, decisions), never a summary of the
  skill's internal workflow. Both hosts select a skill on the description's _meaning_,
  so a trigger keyword mirrored into another language buys nothing.
- Keep the description at most 600 characters of printable ASCII — well under the
  1,024-character limit of the Agent Skills format; a longer one is not a better
  trigger. Avoid an unquoted plain value containing `: ` or ` #`, which a strict YAML
  parser rejects.

Enforced by: `tests/harness/test_skills.py` (`just check-harness`), which reads the
frontmatter strictly and fails on a third key, a `name` that is not the directory, a
`description` not written as `description: >`, or one that is not printable ASCII
within 600 characters. It does not judge whether the description is a good trigger.

## When a new skill is warranted

Add a skill only for work that recurs and needs a workflow, local references, or policy
loaded on demand — not for a fact stated once. Extend an existing skill instead of
creating a near-duplicate when the new material is a variant of what that skill already
covers.

On a surface someone else documents (Python, uv, pytest, ruff, mypy, GitHub Actions), a
skill holds only this repository's decisions, their reasons, the mechanics that are ours
(paths, recipes, error codes), and the traps met here. It holds nothing a vendor already
documents: general platform knowledge stays with official documentation, which the
project skill links instead of restating.

**External claims.** A version, availability, default, limit, or policy claim about an
external tool carries `(<URL>, checked YYYY-MM-DD)`, and the author opened that page on
that date. A link that only explains a concept needs no date. An observed fact says so:
"observed with `<command>`, YYYY-MM-DD". A claim that is neither is dropped.

One home per rule: a rule stated in both `AGENTS.md` and a skill costs context twice and
the two copies drift apart. `AGENTS.md` holds only what every task needs, in its eight
sections — Overview, Product, Quick Reference, Validating a change, Skills, Sub-agents,
Security and human approval, Enforcement layers; an area's own `AGENTS.md`
(`backend/AGENTS.md`) holds what every task in that area needs, its narrowest checks
and its architecture; and a procedure or a convention for one kind of change is a
skill. The one exception is a prohibition
an agent needs even while its own declared task is something else entirely (for
example, never lower the coverage threshold or weaken a gate to make a run pass) — that
stays in `AGENTS.md`, where every agent reads it regardless of task, and a
task-specific skill holds only the reasoning an agent doing that task needs.

Every skill opens with a two-line ownership block (`**Owns:**` / `**Does not own:**`)
naming what it decides and what a named sibling decides. Cross-reference a sibling skill
by its name in backticks, never by path, and an `AGENTS.md` rule by its section name in
quotes, never by line number. A pointer that sends the reader to a sibling skill
as a step of the task carries one of two markers and no other: `**REQUIRED:** <skill>`
when the task cannot be finished correctly without it, `**BACKGROUND:** <skill>` when it
only explains why.

Do not write down what a config already enforces. Name the gate in one line
(`Enforced by: <file> "<setting>".`) and spend the skill's words on the judgment the
config cannot express.

A skill added, renamed, or deleted gets its row in `AGENTS.md`'s Skills table updated in
the same commit, and widening a skill's subject means widening its row. Enforced by:
`tests/harness/test_skills.py`, which fails when the table and the directories disagree.

## Write an illustration so it can be deleted

Example code in a skill is an illustration no build or test depends on, and a project
built from this template may delete the code it points to. State the rule in its own
sentence and the example in the next, and never make the removable code the subject of
the sentence that carries the rule — so the rule still reads once the example is gone.

## Where a skill lives

A skill lives in `.agents/skills/` (mirrored to `.claude/skills/`), and the template
commits no plugin marketplace — the same decision the sibling templates made. Codex CLI
cannot read Claude Code plugins; `just agents-check`, the review of a pull request, and
CI never see a plugin skill; a plugin update changes behavior without a pull request
unless pinned; and a public template cannot ask its users to trust a personal
marketplace. A personal marketplace belongs in your own settings (`AGENTS.md`'s
"Enforcement layers"). A shared plugin pinned by ref is an option only for a
stack-agnostic skill copied across repositories that demonstrably drifts.

## Size and structure

- Target 150 body lines per `SKILL.md`, never exceed 200 (physical lines after the
  frontmatter, blanks included); past that, move detail into `references/`. Enforced
  by: `tests/harness/test_skills.py`, which also fails on a nested `SKILL.md`.
- A `references/*.md` file stays under 400 lines and is linked with a relative path one
  level deep, never with `@` and never as an absolute path.

## Spell-check and formatting

`typos` checks `.agents/skills/**` (pre-commit and CI's `Spell Check` job) but not
`.claude/skills/`, which `typos.toml` excludes because it is generated. When a technical
term has to be allowed, add it to `typos.toml`'s `default.extend-words` rather than
working around the checker. Markdown has no auto-formatter here, so a `SKILL.md` is
wrapped by hand at the width the neighboring skills use.

## Scripts bundled inside a skill

A script shipped under `.agents/skills/<name>/scripts/` is stdlib-only and runs with the
system `python3` (or bash 3.2 for a `.sh`), so it works in any checkout without the
project environment. Its tests sit beside it in `scripts/tests/test_*.py`, written with
`unittest` so they need no project dependency, and `just test-skills` (part of
`just verify` and CI's `Lint & Type Check` job) runs every
`.agents/skills/*/scripts/tests/` suite — a new skill's tests are picked up without a
runner change.

The floor is Python 3.9 (macOS's `/usr/bin/python3`) and bash 3.2 (macOS's
`/bin/bash`). Ruff holds the scripts to 3.9 syntax (`pyproject.toml`'s
`per-file-target-version`), CI's `Skill Scripts (Python 3.9)` job runs every suite
under 3.9, and the `shellcheck` pre-commit hook (also run by CI's `Lint & Type
Check`) lints every `.sh`. bash 3.2 is checked only locally: `test_shell_syntax.py`
parses each script with `/bin/bash`, which is 3.2 on a Mac and bash 5 on CI's Linux
runners, so CI cannot check it.

These scripts belong to this repository. There is no canonical upstream and no
requirement to keep them close to sibling templates. A useful fix is ported to another
template deliberately, one change at a time; routine local refactoring needs no sync.

Ruff formats the authored scripts and checks them with the remaining justified
`[tool.ruff.lint.per-file-ignores]` in `pyproject.toml`; sibling layout is no reason
for a waiver. Strict mypy checks authored production modules through the shared
`[tool.mypy].files` targets used by `just lint`, CI and the commit hook; mirrored
modules and the stdlib unittest fixtures keep their existing checks. Model JSON
boundaries and payloads explicitly. Add a scoped ignore only with a reason comment,
never by relaxing the global rule set.

## What catches a broken skill

`just agents-check` only proves the two trees are byte-identical; it says nothing about
whether the source tree is well-formed. `typos` spell-checks the file without parsing its
frontmatter. A `SKILL.md` whose frontmatter fails to parse, whose `name` disagrees with
its directory, or whose `description` carries a stray key passes both, mirrors cleanly,
and simply never loads in either host. `just check-harness` (part of `just verify`) is
the check that reads the frontmatter, the body length, and the Skills table; it does not
read the mirror. Before committing a new or changed skill, run:

```bash
just agents-sync
just agents-check
just check-harness
just test-skills
```
