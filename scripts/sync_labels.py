"""Create or update this repository's GitHub labels from `.github/labels.yml`.

The YAML file is the single source of truth for label names, colours, and
descriptions. Each label is upserted with `gh label create --force`; a label the
file does not mention is never deleted, so a label a person added by hand
survives. The file uses a fixed, flat shape (a list of `name` / `color` /
`description` mappings), read by a small scanner here so the script needs no
YAML dependency.

Usage:
    uv run --locked python scripts/sync_labels.py            # apply via gh
    uv run --locked python scripts/sync_labels.py --dry-run  # print the plan
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LABELS_FILE = REPO_ROOT / ".github" / "labels.yml"
_FIELD = re.compile(
    r"^(?P<lead>- |  )(?P<key>name|color|description):\s*(?P<value>.*)$"
)
_COLOR = re.compile(r"^[0-9a-f]{6}$")


class LabelsFileError(ValueError):
    """`.github/labels.yml` does not have the shape this script reads."""


@dataclass(frozen=True, slots=True)
class Label:
    """One declared label."""

    name: str
    color: str
    description: str


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:  # noqa: PLR2004
        return value[1:-1]
    return value


def _finish(current: dict[str, str], line_number: int) -> Label:
    missing = {"name", "color", "description"} - current.keys()
    if missing:
        msg = f"label ending before line {line_number} lacks {sorted(missing)}"
        raise LabelsFileError(msg)
    if not _COLOR.match(current["color"]):
        msg = f"label {current['name']!r}: color must be 6 lowercase hex digits"
        raise LabelsFileError(msg)
    return Label(current["name"], current["color"], current["description"])


def parse_labels(text: str) -> list[Label]:
    """Parse the flat label list, rejecting duplicates and malformed entries.

    Raises:
        LabelsFileError: On an unknown line, a missing field, a bad colour, or a
            duplicated label name.
    """
    labels: list[Label] = []
    current: dict[str, str] | None = None
    line_number = 0
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = _FIELD.match(raw)
        if match is None:
            msg = f"line {line_number}: unexpected content {raw!r}"
            raise LabelsFileError(msg)
        if match["lead"] == "- ":
            if current is not None:
                labels.append(_finish(current, line_number))
            current = {}
        elif current is None:
            msg = f"line {line_number}: field outside a list item"
            raise LabelsFileError(msg)
        current[match["key"]] = _unquote(match["value"])
    if current is not None:
        labels.append(_finish(current, line_number + 1))
    names = [label.name for label in labels]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        msg = f"duplicated label names: {duplicates}"
        raise LabelsFileError(msg)
    return labels


def gh_command(label: Label) -> list[str]:
    """Return the `gh` invocation that creates or updates ``label``."""
    return [
        "gh",
        "label",
        "create",
        label.name,
        "--color",
        label.color,
        "--description",
        label.description,
        "--force",
    ]


def _fail(code: str, detail: str, expected: str, next_step: str) -> int:
    print(f"{code}: {detail}", file=sys.stderr)
    print(f"Expected: {expected}", file=sys.stderr)
    print(f"Next: {next_step}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None, labels_file: Path = LABELS_FILE) -> int:
    """Upsert every declared label (or print the plan) and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="print the gh commands, run none"
    )
    args = parser.parse_args(argv)
    try:
        labels = parse_labels(labels_file.read_text(encoding="utf-8"))
    except (OSError, LabelsFileError) as error:
        return _fail(
            "ERR_LABELS_FILE",
            f"{labels_file}: {error}",
            "a flat label list with name, color (6 lowercase hex digits), and description",
            f"fix {labels_file} and rerun `just labels`",
        )
    failures = 0
    for label in labels:
        command = gh_command(label)
        if args.dry_run:
            print(shlex.join(command))
            continue
        try:
            result = subprocess.run(  # noqa: S603 -- fixed argv, no shell
                command, check=False, capture_output=True, text=True
            )
        except OSError as error:
            return _fail(
                "ERR_LABELS_GH",
                f"cannot run gh: {error}",
                "gh available on PATH and executable",
                "install GitHub CLI or fix its executable permissions, then rerun "
                "`just labels`",
            )
        if result.returncode != 0:
            failures += 1
            print(f"failed: {label.name}: {result.stderr.strip()}", file=sys.stderr)
        else:
            print(f"synced: {label.name}")
    if failures:
        return _fail(
            "ERR_LABELS_SYNC",
            f"{failures} label(s) failed",
            "every declared label created or updated",
            "resolve the gh errors above (check authentication and repository access), "
            "then rerun `just labels`",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
