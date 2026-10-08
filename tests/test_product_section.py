"""AGENTS.md's Product section: a skeleton in the template, filled in an app.

The section is the one part of AGENTS.md about the application rather than the
harness. In the template its entries are ``TODO:`` markers; once the bootstrap
has run (``.template-origin`` exists), a marker left there means an agent has no
in-repo answer to "is this in scope?". Both directions are one invariant: the
template must keep a marker, so filling the skeleton in the template cannot
quietly make the app-side rule vacuous. Nothing here judges the prose: the
marker is the whole signal.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
ORIGIN_FILE = ".template-origin"
HEADING = "## Product"
# The colon is part of the marker: a bare "TODO" would also reject an app
# whose product is, say, a to-do list.
MARKER = "TODO:"
ENTRY_LABELS = (
    "What it is, and who it is for",
    "The core interaction",
    "Non-goals",
    "Where these decisions are recorded",
)


def _product_section(agents_text: str) -> list[tuple[int, str]] | None:
    """Return ``(line number, line)`` for the section's body, or None if absent."""
    lines = agents_text.splitlines()
    try:
        start = lines.index(HEADING)
    except ValueError:
        return None
    body: list[tuple[int, str]] = []
    for number, line in enumerate(lines[start + 1 :], start=start + 2):
        if line.startswith("## "):
            break
        body.append((number, line))
    return body


def product_section_problems(root: Path) -> list[str]:
    """Return what is wrong with root's Product section for its state."""
    section = _product_section((root / "AGENTS.md").read_text(encoding="utf-8"))
    if section is None:
        return [f"AGENTS.md has no {HEADING!r} section"]
    text = "\n".join(line for _, line in section)
    problems = [
        f"the Product section lost its {label!r} entry"
        for label in ENTRY_LABELS
        if f"**{label}**" not in text
    ]
    markers = [number for number, line in section if MARKER in line]
    if (root / ORIGIN_FILE).exists():
        problems.extend(
            f"AGENTS.md:{number}: {MARKER} left in the Product section; "
            "write the entry from what the owner decided"
            for number in markers
        )
    elif not markers:
        problems.append(
            f"the template's Product section must keep its {MARKER} markers: "
            "every app writes its own"
        )
    return problems


def test_product_section_in_this_repository_has_no_problem() -> None:
    assert product_section_problems(REPO_ROOT) == []


def test_product_section_filling_only_its_entries_satisfies_the_app_check(tmp_path):
    # What an app's owner does, and what CI's bootstrap smoke job does: replace
    # each entry's marker, in the text the bootstrap leaves (no template-only
    # block). Any other marker in the section, in its prose say, would leave
    # the check failing after every entry is written.
    text = re.sub(
        r"^<!-- template-only -->$.*?^<!-- /template-only -->$\n",
        "",
        (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8"),
        flags=re.MULTILINE | re.DOTALL,
    )
    filled = re.sub(rf"(\*\*[^*]+\*\* — ){MARKER} ", r"\1", text)
    (tmp_path / "AGENTS.md").write_text(filled, encoding="utf-8")
    (tmp_path / ORIGIN_FILE).write_text("commit: unknown\n", encoding="utf-8")

    assert product_section_problems(tmp_path) == []


def _entries(*, is_filled: bool) -> str:
    value = "Decided by the owner." if is_filled else f"{MARKER} write this."
    return "\n".join(f"- **{label}** — {value}" for label in ENTRY_LABELS)


@pytest.fixture
def make_repository(tmp_path: Path) -> Callable[..., Path]:
    """Write an AGENTS.md (and, for an app, .template-origin) under tmp_path."""

    def make(product_body: str | None, *, is_app: bool) -> Path:
        section = "" if product_body is None else f"{HEADING}\n\n{product_body}\n\n"
        (tmp_path / "AGENTS.md").write_text(
            f"# Project Guide\n\n## Overview\n\nText.\n\n{section}"
            f"## Quick Reference\n\nA {MARKER} outside the section.\n",
            encoding="utf-8",
        )
        if is_app:
            (tmp_path / ORIGIN_FILE).write_text("commit: unknown\n", encoding="utf-8")
        return tmp_path

    return make


@pytest.mark.parametrize(
    ("is_app", "is_filled"),
    [
        pytest.param(False, False, id="template-skeleton"),
        pytest.param(True, True, id="app-filled"),
    ],
)
def test_product_section_matching_its_state_has_no_problem(
    make_repository, is_app, is_filled
):
    root = make_repository(_entries(is_filled=is_filled), is_app=is_app)

    assert product_section_problems(root) == []


def test_product_section_in_an_app_with_a_marker_left_names_each_line(
    make_repository,
):
    body = _entries(is_filled=True).replace(
        "**Non-goals** — Decided by the owner.", f"**Non-goals** — {MARKER} later."
    )
    root = make_repository(body, is_app=True)

    problems = product_section_problems(root)

    assert len(problems) == 1
    assert problems[0].startswith("AGENTS.md:11: TODO: left in the Product section")


def test_product_section_in_an_app_with_every_marker_left_fails(make_repository):
    root = make_repository(_entries(is_filled=False), is_app=True)

    assert len(product_section_problems(root)) == len(ENTRY_LABELS)


def test_product_section_filled_in_the_template_fails(make_repository):
    root = make_repository(_entries(is_filled=True), is_app=False)

    assert product_section_problems(root) == [
        (
            "the template's Product section must keep its TODO: markers: every app "
            "writes its own"
        )
    ]


@pytest.mark.parametrize("is_app", [False, True], ids=["template", "app"])
def test_product_section_missing_fails(make_repository, is_app):
    root = make_repository(None, is_app=is_app)

    assert product_section_problems(root) == ["AGENTS.md has no '## Product' section"]


def test_product_section_without_an_entry_names_the_lost_label(make_repository):
    body = "\n".join(
        line
        for line in _entries(is_filled=True).splitlines()
        if "Non-goals" not in line
    )
    root = make_repository(body, is_app=True)

    assert product_section_problems(root) == [
        "the Product section lost its 'Non-goals' entry"
    ]
