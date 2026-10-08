"""Tests for scripts/sync_labels.py.

That every label the repository applies is declared is the harness check in
tests/harness/test_labels.py.
"""

from __future__ import annotations

import importlib.util
import shlex
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sync_labels", REPO_ROOT / "scripts" / "sync_labels.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules while the class body runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync_labels = _load_module()

VALID = """\
# comment
- name: bug
  color: d73a4a
  description: "Reproducible incorrect behavior."

- name: "priority: P0"
  color: b60205
  description: 'Ship now.'
"""


def test_committed_labels_file_parses() -> None:
    labels = sync_labels.parse_labels(sync_labels.LABELS_FILE.read_text("utf-8"))

    assert {"bug", "chore", "tracking", "priority: P0"} <= {lbl.name for lbl in labels}


def test_parse_labels_reads_quoted_and_bare_values() -> None:
    labels = sync_labels.parse_labels(VALID)

    assert labels == [
        sync_labels.Label("bug", "d73a4a", "Reproducible incorrect behavior."),
        sync_labels.Label("priority: P0", "b60205", "Ship now."),
    ]


@pytest.mark.parametrize(
    ("text", "pattern"),
    [
        ("- name: a\n  color: ffffff\n", r"lacks \['description'\]"),
        ("- name: a\n  color: FFF\n  description: x\n", r"6 lowercase hex"),
        ("  name: a\n", r"outside a list item"),
        ("labels:\n", r"unexpected content"),
        (
            (
                "- name: a\n  color: ffffff\n  description: x\n"
                "- name: a\n  color: ffffff\n  description: y\n"
            ),
            r"duplicated label names: \['a'\]",
        ),
    ],
    ids=["missing-field", "bad-color", "orphan-field", "unknown-line", "duplicate"],
)
def test_parse_labels_rejects_malformed_file(text: str, pattern: str) -> None:
    with pytest.raises(sync_labels.LabelsFileError, match=pattern):
        sync_labels.parse_labels(text)


def test_main_dry_run_prints_one_command_per_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    labels_file = tmp_path / "labels.yml"
    labels_file.write_text(
        VALID + '- name: "shell; $(echo nope)"\n  color: ffffff\n'
        '  description: "Owner\'s $value; `command`"\n',
        encoding="utf-8",
    )

    def refuse_run(*_: object, **__: object) -> None:
        pytest.fail("dry-run must not invoke a subprocess")

    monkeypatch.setattr(sync_labels.subprocess, "run", refuse_run)

    assert sync_labels.main(["--dry-run"], labels_file=labels_file) == 0
    out = capsys.readouterr().out.splitlines()
    assert [shlex.split(line) for line in out] == [
        [
            "gh",
            "label",
            "create",
            "bug",
            "--color",
            "d73a4a",
            "--description",
            "Reproducible incorrect behavior.",
            "--force",
        ],
        [
            "gh",
            "label",
            "create",
            "priority: P0",
            "--color",
            "b60205",
            "--description",
            "Ship now.",
            "--force",
        ],
        [
            "gh",
            "label",
            "create",
            "shell; $(echo nope)",
            "--color",
            "ffffff",
            "--description",
            "Owner's $value; `command`",
            "--force",
        ],
    ]


def test_main_reports_unreadable_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sync_labels.main([], labels_file=tmp_path / "absent.yml") == 1
    error = capsys.readouterr().err
    assert "ERR_LABELS_FILE" in error
    assert "Expected: a flat label list" in error
    assert "Next: fix " in error
    assert "`just labels`" in error


def test_main_counts_gh_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    labels_file = tmp_path / "labels.yml"
    labels_file.write_text(VALID, encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        code = 1 if command[3] == "bug" else 0
        return subprocess.CompletedProcess(command, code, "", "boom")

    monkeypatch.setattr(sync_labels.subprocess, "run", fake_run)

    assert sync_labels.main([], labels_file=labels_file) == 1
    assert [c[3] for c in calls] == ["bug", "priority: P0"]
    captured = capsys.readouterr()
    assert "synced: priority: P0" in captured.out
    assert "ERR_LABELS_SYNC: 1 label(s) failed" in captured.err
    assert "failed: bug: boom" in captured.err
    assert "Expected: every declared label created or updated" in captured.err
    assert "Next: resolve the gh errors above" in captured.err


def test_main_missing_gh_reports_actionable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    labels_file = tmp_path / "labels.yml"
    labels_file.write_text(VALID, encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path))

    def missing_gh(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        message = "No such file or directory: gh"
        raise FileNotFoundError(message)

    monkeypatch.setattr(sync_labels.subprocess, "run", missing_gh)

    assert sync_labels.main([], labels_file=labels_file) == 1
    captured = capsys.readouterr()
    assert "ERR_LABELS_GH:" in captured.err
    assert "Expected: gh available on PATH" in captured.err
    assert "Next: install GitHub CLI" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
