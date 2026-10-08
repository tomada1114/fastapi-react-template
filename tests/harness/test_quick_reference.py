"""(i) AGENTS.md's Quick Reference indexes every recipe and spells out ``verify``.

The Quick Reference calls itself the justfile's index, and it is the one place
that lists ``just verify``'s steps; every other document points at it. So:

- every justfile recipe and alias but ``default`` (``just --list``) appears as
  ``just <name>`` in command position in the section (fenced or inline, as
  check (c) reads code), and
- the comment on its ``just verify`` line lists ``verify``'s dependencies in
  the justfile's order, as ``<label>: a → b → c``: prior and subsequent
  (``&&``) ones alike, a ``(name arg ...)`` dependency by its name.

The section runs from ``## Quick Reference`` to the next ``## `` heading. A
missing AGENTS.md, section, or ``just verify`` line fails closed; a justfile
with no ``verify`` recipe (an app that dropped it) skips the second rule.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.harness.test_just_recipes import code_snippets, commands, justfile_recipes

if TYPE_CHECKING:
    from collections.abc import Callable

    type MakeRoot = Callable[[str, str], Path]

REPO_ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = "justfile"
AGENTS = "AGENTS.md"
HEADING = "## Quick Reference"
# `just --list`'s own recipe: running it is `just`, not `just default`.
UNINDEXED = frozenset({"default"})
ARROW = "→"

_NAME = r"[A-Za-z_][A-Za-z0-9_-]*"
_CALL = re.compile(rf"^just\s+(?P<name>{_NAME})")
_VERIFY_HEADER = re.compile(r"^@?verify(?:[ \t]+[^:]*?)?[ \t]*:(?!=)(?P<deps>.*)$")
_VERIFY_LINE = re.compile(r"^\s*just\s+verify\b[^#]*#(?P<comment>.*)$")
_QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
# A dependency is a bare name or `(name arg ...)`; `&&` only marks the ones
# after it as running after the body, and verify's body is empty.
_DEPENDENCY = re.compile(rf"\(\s*(?P<call>{_NAME})[^)]*\)|(?P<name>{_NAME})")


def verify_dependencies(text: str) -> list[str] | None:
    """Return the ``verify`` recipe's dependencies in order, or None without it."""
    for line in text.splitlines():
        if match := _VERIFY_HEADER.match(line):
            deps = _QUOTED.sub(" ", match["deps"]).split("#", 1)[0]
            return [dep["call"] or dep["name"] for dep in _DEPENDENCY.finditer(deps)]
    return None


def _section(text: str) -> tuple[int, int] | None:
    """Return the Quick Reference's ``(first, last)`` line numbers, or None."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.rstrip() == HEADING:
            end = next(
                (
                    number
                    for number, later in enumerate(lines[index + 1 :], start=index + 1)
                    if later.startswith("## ")
                ),
                len(lines),
            )
            return index + 1, end
    return None


def quick_reference_findings(root: Path) -> list[str]:
    """Return each way AGENTS.md's Quick Reference disagrees with the justfile."""
    justfile, agents = root / JUSTFILE, root / AGENTS
    missing = [name for name in (JUSTFILE, AGENTS) if not (root / name).is_file()]
    if missing:
        return [f"{name} is missing" for name in missing]
    recipes_text = justfile.read_text(encoding="utf-8")
    text = agents.read_text(encoding="utf-8")
    bounds = _section(text)
    if bounds is None:
        return [f"{AGENTS} has no `{HEADING}` section"]
    first, last = bounds
    indexed = {
        match["name"]
        for number, code in code_snippets(text)
        if first <= number <= last
        for command in commands(code)
        if (match := _CALL.match(command))
    }
    findings = [
        f"{AGENTS}: `just {name}` is a {JUSTFILE} recipe the Quick Reference "
        "does not index"
        for name in sorted(justfile_recipes(recipes_text) - UNINDEXED - indexed)
    ]
    deps = verify_dependencies(recipes_text)
    if deps is None:
        return findings
    section_lines = text.splitlines()[first - 1 : last]
    comment = next(
        (m["comment"] for line in section_lines if (m := _VERIFY_LINE.match(line))),
        None,
    )
    expected = f" {ARROW} ".join(deps)
    if comment is None:
        findings.append(
            f"{AGENTS}: the Quick Reference has no commented `just verify` line; "
            f"its comment lists the {JUSTFILE}'s steps: {expected}"
        )
        return findings
    listed = [step.strip() for step in comment.split(":", 1)[-1].split(ARROW)]
    if listed != deps:
        findings.append(
            f"{AGENTS}: the `just verify` line lists {f' {ARROW} '.join(listed)!r}, "
            f"the {JUSTFILE}'s verify runs {expected!r}"
        )
    return findings


# --- the repository ---


def test_quick_reference_matches_repository_justfile() -> None:
    assert quick_reference_findings(REPO_ROOT) == []


# --- fixtures ---

JUSTFILE_TEXT = """\
alias t := test

default:
    @just --list

# Run the tests
test:
    uv run pytest

lint:
    uv run ruff check .

lock-check:
    uv lock --check

# The gate
verify: lock-check lint test # cheap first
"""

AGENTS_TEXT = """\
# Guide

## Quick Reference

```bash
just test            # Run the tests
just t               # Alias for test
just lint            # Lint
just verify          # Gate: lock-check → lint → test
```

Run `just lock-check` when the lock may be stale.

## Architecture

Run `just docs` here, which is outside the section.
"""


@pytest.fixture
def make_root(tmp_path: Path) -> MakeRoot:
    def make(justfile: str, agents: str) -> Path:
        (tmp_path / JUSTFILE).write_text(justfile, encoding="utf-8")
        (tmp_path / AGENTS).write_text(agents, encoding="utf-8")
        return tmp_path

    return make


def test_verify_dependencies_reads_order_and_drops_comment() -> None:
    assert verify_dependencies(JUSTFILE_TEXT) == ["lock-check", "lint", "test"]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        pytest.param(
            "verify: lint && test", ["lint", "test"], id="subsequent-dependency"
        ),
        pytest.param(
            'verify: (build "main") lint', ["build", "lint"], id="dependency-arguments"
        ),
        pytest.param(
            "verify: (build 'a#b' main) && (deploy \"x\")",
            ["build", "deploy"],
            id="quoted-hash-in-argument",
        ),
        pytest.param("verify:", [], id="no-dependencies"),
    ],
)
def test_verify_dependencies_reads_every_dependency_form(
    header: str, expected: list[str]
) -> None:
    assert verify_dependencies(f"{header}\n    echo done\n") == expected


def test_verify_dependencies_without_verify_is_none() -> None:
    assert verify_dependencies("test:\n    uv run pytest\n") is None


def test_quick_reference_findings_indexed_section_passes(make_root: MakeRoot) -> None:
    assert quick_reference_findings(make_root(JUSTFILE_TEXT, AGENTS_TEXT)) == []


def test_quick_reference_findings_unindexed_recipe_is_named(
    make_root: MakeRoot,
) -> None:
    agents = AGENTS_TEXT.replace(
        "Run `just lock-check` when the lock may be stale.\n", ""
    )

    findings = quick_reference_findings(make_root(JUSTFILE_TEXT, agents))

    assert findings == [
        (
            f"{AGENTS}: `just lock-check` is a {JUSTFILE} recipe the Quick "
            "Reference does not index"
        )
    ]


def test_quick_reference_findings_recipe_outside_section_does_not_count(
    make_root: MakeRoot,
) -> None:
    agents = AGENTS_TEXT.replace(
        "Run `just lock-check` when the lock may be stale.\n", ""
    ).replace("`just docs`", "`just lock-check`")

    findings = quick_reference_findings(make_root(JUSTFILE_TEXT, agents))

    assert len(findings) == 1
    assert "`just lock-check`" in findings[0]


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param("lint → lock-check → test", id="reordered"),
        pytest.param("lock-check → test", id="step-dropped"),
        pytest.param("lock-check, lint, test", id="not-arrows"),
    ],
)
def test_quick_reference_findings_verify_line_disagrees_is_named(
    make_root: MakeRoot, steps: str
) -> None:
    agents = AGENTS_TEXT.replace("lock-check → lint → test", steps)

    findings = quick_reference_findings(make_root(JUSTFILE_TEXT, agents))

    assert len(findings) == 1
    assert "the `just verify` line lists" in findings[0]
    assert "'lock-check → lint → test'" in findings[0]


def test_quick_reference_findings_verify_line_missing_fails(
    make_root: MakeRoot,
) -> None:
    agents = AGENTS_TEXT.replace(
        "just verify          # Gate: lock-check → lint → test\n", ""
    )

    findings = quick_reference_findings(make_root(JUSTFILE_TEXT, agents))

    assert findings == [
        (
            f"{AGENTS}: `just verify` is a {JUSTFILE} recipe the Quick "
            "Reference does not index"
        ),
        (
            f"{AGENTS}: the Quick Reference has no commented `just verify` line; "
            f"its comment lists the {JUSTFILE}'s steps: lock-check → lint → test"
        ),
    ]


def test_quick_reference_findings_without_verify_recipe_checks_index_only(
    make_root: MakeRoot,
) -> None:
    justfile = JUSTFILE_TEXT.replace(
        "# The gate\nverify: lock-check lint test # cheap first\n", ""
    )
    agents = AGENTS_TEXT.replace(
        "just verify          # Gate: lock-check → lint → test\n", ""
    )

    assert quick_reference_findings(make_root(justfile, agents)) == []


def test_quick_reference_findings_without_section_fails(make_root: MakeRoot) -> None:
    root = make_root(JUSTFILE_TEXT, "# Guide\n\nRun `just test`.\n")

    assert quick_reference_findings(root) == [f"{AGENTS} has no `{HEADING}` section"]


@pytest.mark.parametrize("absent", [JUSTFILE, AGENTS])
def test_quick_reference_findings_missing_file_fails(
    make_root: MakeRoot, absent: str
) -> None:
    root = make_root(JUSTFILE_TEXT, AGENTS_TEXT)
    (root / absent).unlink()

    assert quick_reference_findings(root) == [f"{absent} is missing"]
