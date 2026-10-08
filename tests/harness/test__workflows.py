"""Workflow triggers, matrix checks and skip behavior independent of rulesets."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from tests.harness._needs import unfailed_needs
from tests.harness._workflows import Check, can_skip, every_pr_checks
from tests.harness._yaml import UnreadableYamlError


def _workflow(tmp_path: Path, text: str) -> Path:
    (tmp_path / "w.yml").write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("trigger", "expected"),
    [
        ("on:\n  pull_request:\n", True),
        ("on:\n  pull_request:\n    types: [opened, synchronize, reopened]\n", True),
        ("on:\n  pull_request:\n    types: [opened]\n", False),
        ("on:\n  pull_request:\n    types: [opened, reopened, edited]\n", False),
        ("on:\n  pull_request:\n    branches: [main]\n", True),
        ("on:\n  pull_request:\n    branches: ['**']\n", True),
        ("on:\n  pull_request:\n    branches: [release/*]\n", False),
        ("on:\n  pull_request:\n    branches: ['*', '!main']\n", False),
        ("on:\n  pull_request:\n    branches-ignore: [wip/*]\n", False),
        ("on:\n  pull_request:\n    paths: [uv.lock]\n", False),
        ("on:\n  pull_request:\n    paths-ignore: [docs/**]\n", False),
        ("on:\n  push:\n    paths: [a]\n  pull_request:\n", True),
        ("on:\n  schedule:\n    - cron: '0 0 * * 0'\n", False),
        ("on: pull_request\n", True),
        ("on: [push, pull_request]\n", True),
        ("on: push\n", False),
        ("on:\n    pull_request:\n        paths:\n            - a\n", False),
        ('"on":\n  pull_request:\n', True),
    ],
    ids=[
        "bare",
        "types-all-three",
        "types-opened-only",
        "types-without-synchronize",
        "branches-main",
        "branches-glob",
        "branches-not-main",
        "branches-negated",
        "branches-ignore",
        "paths",
        "paths-ignore",
        "push-paths-only",
        "no-pr",
        "inline-scalar",
        "inline-list",
        "inline-push",
        "four-space-indent",
        "quoted-on",
    ],
)
def test_every_pr_checks_honours_trigger_filters(
    tmp_path: Path, trigger: str, *, expected: bool
) -> None:
    root = _workflow(tmp_path, f"name: W\n{trigger}jobs:\n  job:\n    name: Job\n")

    assert ("Job" in every_pr_checks(root)) is expected


def test_every_pr_checks_expands_matrix_names(tmp_path: Path) -> None:
    root = _workflow(
        tmp_path,
        "on: pull_request\njobs:\n    a:\n        name: A (${{ matrix.x }})\n"
        "        strategy:\n            matrix:\n                x: [one, two]\n",
    )

    assert set(every_pr_checks(root)) == {"A (one)", "A (two)"}


@pytest.mark.parametrize(
    ("job", "message"),
    [
        (
            "    name: A (${{ matrix.x }})\n    strategy: {matrix: {x: one}}\n",
            r"matrix\.x: expected sequence",
        ),
        ("    name: A (${{ matrix.x }})\n", r"matrix\.x is not declared"),
        ("    name: A\n   if: odd\n", r"while parsing"),
    ],
    ids=["scalar-matrix-axis", "undeclared-matrix", "bad-indent"],
)
def test_every_pr_checks_fails_closed_on_unreadable_layout(
    tmp_path: Path, job: str, message: str
) -> None:
    root = _workflow(tmp_path, f"on: pull_request\njobs:\n  a:\n{job}")

    with pytest.raises(UnreadableYamlError, match=message):
        every_pr_checks(root)


@pytest.mark.parametrize(
    ("trigger", "message"),
    [
        ("on:\n  pull_request: [a]\n", r"on.pull_request: expected mapping"),
        ("on: [push,\n  pull_request\n", r"while parsing"),
        ("name: no trigger\n", r"no `on:` trigger"),
        ("on:\n  pull_request:\n    tags: [v1]\n", r"unknown pull_request filter"),
        ("on:\n  pull_request:\n  pull_request:\n", r"duplicate key 'pull_request'"),
    ],
    ids=[
        "pull-request-sequence",
        "unclosed-flow-list",
        "no-trigger",
        "unknown-filter",
        "duplicate-key",
    ],
)
def test_every_pr_checks_rejects_unreadable_trigger(
    tmp_path: Path, trigger: str, message: str
) -> None:
    root = _workflow(tmp_path, f"{trigger}jobs:\n  a:\n    name: A\n")

    with pytest.raises(UnreadableYamlError, match=message):
        every_pr_checks(root)


@pytest.mark.parametrize(
    ("if_expr", "has_needs", "expected"),
    [
        (None, False, False),
        (None, True, True),
        ("${{ !cancelled() }}", True, False),
        ("always()", True, False),
        ("${{ needs.test.result == 'success' }}", True, True),
        ("github.event_name == 'push'", False, True),
    ],
    ids=[
        "plain",
        "needs-unguarded",
        "not-cancelled",
        "always",
        "success-only",
        "event-if",
    ],
)
def test_can_skip(if_expr: str | None, *, has_needs: bool, expected: bool) -> None:
    assert can_skip(Check("J", if_expr, has_needs)) is expected


def test_every_pr_checks_strips_comment_from_if(tmp_path: Path) -> None:
    root = _workflow(
        tmp_path,
        "on: pull_request\njobs:\n  a:\n    name: A\n    needs: b\n"
        "    if: ${{ !cancelled() }} # report even when b fails\n",
    )

    assert can_skip(every_pr_checks(root)["A"]) is False


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(("a.yml", "b.yml"), id="skippable-last"),
        pytest.param(("b.yml", "a.yml"), id="skippable-first"),
    ],
)
def test_every_pr_checks_duplicate_name_keeps_skippable(
    tmp_path: Path, files: tuple[str, str]
) -> None:
    plain, skippable = files
    (tmp_path / plain).write_text(
        "on: pull_request\njobs:\n  a:\n    name: A\n", encoding="utf-8"
    )
    (tmp_path / skippable).write_text(
        "on: pull_request\njobs:\n  a:\n    name: A\n    if: github.actor == 'x'\n",
        encoding="utf-8",
    )

    assert can_skip(every_pr_checks(tmp_path)["A"]) is True


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(("a.yml", "b.yml"), id="needs-job-first"),
        pytest.param(("b.yml", "a.yml"), id="needs-job-last"),
    ],
)
def test_every_pr_checks_duplicate_name_keeps_every_problem(
    tmp_path: Path, files: tuple[str, str]
) -> None:
    needs_job, skippable = files
    (tmp_path / needs_job).write_text(
        "on: pull_request\njobs:\n  a:\n    name: A\n    needs: b\n    if: always()\n",
        encoding="utf-8",
    )
    (tmp_path / skippable).write_text(
        "on: pull_request\njobs:\n  a:\n    name: A\n    if: github.actor == 'x'\n",
        encoding="utf-8",
    )

    check = every_pr_checks(tmp_path)["A"]

    assert can_skip(check) is True
    assert unfailed_needs(check) == ("b",)


@pytest.mark.parametrize(
    ("trigger", "matrix", "expected"),
    [
        pytest.param(
            "on: [push,\n  pull_request]\n",
            "x:\n          - one\n          - two",
            {"A (one)", "A (two)"},
            id="multiline-and-block",
        ),
        pytest.param(
            "on: {pull_request: {types: [opened, synchronize, reopened]}}\n",
            "include:\n          - x: linux\n          - x: macos",
            {"A (linux)", "A (macos)"},
            id="include-only",
        ),
        pytest.param(
            "on: pull_request\n",
            "x: [one, two]\n        exclude: [{x: two}]\n        include: [{x: two}]",
            {"A (one)", "A (two)"},
            id="include-restores-excluded",
        ),
        pytest.param(
            "on: pull_request\n",
            "x: [one, two]\n        exclude: [{x: two}]",
            {"A (one)"},
            id="partial-exclusion",
        ),
    ],
)
def test_every_pr_checks_valid_yaml_layouts_expand_checks(
    tmp_path: Path, trigger: str, matrix: str, expected: set[str]
) -> None:
    root = _workflow(
        tmp_path,
        f"{trigger}jobs:\n  a:\n    name: A (${{{{ matrix.x }}}})\n    strategy:\n      matrix:\n        {matrix}\n",
    )
    assert set(every_pr_checks(root)) == expected


def test_every_pr_checks_include_updates_original_combinations(tmp_path: Path) -> None:
    root = _workflow(
        tmp_path,
        """on: pull_request
jobs:
  a:
    name: A (${{ matrix.os }}-${{ matrix.version }}-${{ matrix.color }})
    strategy:
      matrix:
        os: [linux, macos]
        version: [1, 2]
        exclude: [{os: macos, version: 2}]
        include:
          - color: green
          - os: linux
            color: pink
          - os: windows
            version: 3
            color: blue
""",
    )
    assert set(every_pr_checks(root)) == {
        "A (linux-1-pink)",
        "A (linux-2-pink)",
        "A (macos-1-green)",
        "A (windows-3-blue)",
    }


@pytest.mark.parametrize(
    ("value", "context"), [("2026-10-08", "2026-10-08"), ("010", "10")]
)
def test_every_pr_checks_core_scalars_render_actual_context(
    tmp_path: Path, value: str, context: str
) -> None:
    root = _workflow(
        tmp_path,
        "on: pull_request\njobs:\n  a:\n"
        "    name: A (${{ matrix.x }})\n"
        f"    strategy:\n      matrix:\n        x: [{value}]\n",
    )

    assert set(every_pr_checks(root)) == {f"A ({context})"}


def test_every_pr_checks_partial_include_missing_name_property_is_empty(
    tmp_path: Path,
) -> None:
    root = _workflow(
        tmp_path,
        """on: pull_request
jobs:
  build:
    name: Build (${{ matrix.os }}-${{ matrix.version }})
    strategy:
      matrix:
        os: [linux]
        version: [1, 2]
        include: [{os: windows}]
""",
    )
    assert set(every_pr_checks(root)) == {
        "Build (linux-1)",
        "Build (linux-2)",
        "Build (windows-)",
    }


@pytest.mark.parametrize(
    ("matrix", "expected"),
    [
        ("OS: [linux, windows]", {"Build (linux-)", "Build (windows-)"}),
        (
            "OS: [linux, windows]\n        exclude: [{os: windows}]",
            {"Build (linux-)"},
        ),
        (
            (
                "OS: [linux, windows]\n"
                "        include: [{os: linux, Color: green}, {Os: macos, COLOR: blue}]"
            ),
            {"Build (linux-green)", "Build (windows-)", "Build (macos-blue)"},
        ),
    ],
)
def test_every_pr_checks_matrix_keys_ignore_case(
    tmp_path: Path, matrix: str, expected: set[str]
) -> None:
    root = _workflow(
        tmp_path,
        "on: pull_request\njobs:\n  a:\n"
        "    name: Build (${{ MaTrIx.os }}-${{ matrix.COLOR }})\n"
        f"    strategy:\n      matrix:\n        {matrix}\n",
    )

    assert set(every_pr_checks(root)) == expected


def test_every_pr_checks_workflow_merge_keys_fail_closed(tmp_path: Path) -> None:
    root = _workflow(
        tmp_path,
        "on: pull_request\njobs:\n  a: &defaults {name: A}\n"
        "  b: {<<: *defaults, name: B}\n",
    )

    with pytest.raises(UnreadableYamlError, match=r"merge keys.*GitHub Actions"):
        every_pr_checks(root)


def test_every_pr_checks_ambiguous_matrix_keys_fail_closed(tmp_path: Path) -> None:
    root = _workflow(
        tmp_path,
        "on: pull_request\njobs:\n  a:\n    name: A (${{ matrix.os }})\n"
        "    strategy:\n      matrix: {OS: [linux], os: [windows]}\n",
    )

    with pytest.raises(UnreadableYamlError, match="duplicate case-insensitive"):
        every_pr_checks(root)
