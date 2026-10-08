"""Reads GitHub Actions workflows through the shared safe YAML loader.

Shared by the ruleset check (which jobs run on every pull request) and the
workflow hygiene check (triggers, jobs, steps). Any layout the scanner cannot
read raises `UnreadableYamlError`, so a workflow is never classified as running
on every pull request, or as clean, by accident. Whether a required job with
``needs:`` fails on its own is ``_needs.py``'s, read from the job each check
keeps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from itertools import product
from typing import TYPE_CHECKING

from tests.harness._yaml import (
    Mapping,
    UnreadableYamlError,
    as_mapping,
    as_sequence,
    as_str,
    load_yaml,
    scalar,
    scalar_list,
)

if TYPE_CHECKING:
    from pathlib import Path

WORKFLOWS_DIR = ".github/workflows"

_MATRIX_REF = re.compile(
    r"\$\{\{\s*matrix\.(?P<key>[A-Za-z0-9_-]+)\s*\}\}", re.IGNORECASE
)
_EXPR = re.compile(r"^\$\{\{\s*(?P<body>.*?)\s*\}\}$")
_GUARDS = {"!cancelled()", "always()"}
# The ruleset protects the default branch; a pull_request filter has to let a PR
# into it through, on each of the events a PR's checks are reported for.
DEFAULT_BRANCH = "main"
PR_ACTIVITY = frozenset({"opened", "synchronize", "reopened"})
_PR_FILTERS = frozenset(
    {"types", "branches", "branches-ignore", "paths", "paths-ignore"}
)


@dataclass(frozen=True, slots=True)
class Check:
    """One check run a workflow job produces."""

    name: str
    if_expr: str | None
    has_needs: bool
    # Every job that reports this check, read only when it is a required context.
    jobs: tuple[JobSource, ...] = field(default=(), compare=False)


@dataclass(frozen=True, slots=True)
class JobSource:
    """A job's mapping and the workflow it came from."""

    path: Path
    job: Mapping


def workflow_files(root: Path) -> list[Path]:
    """Return every workflow file under ``root``, sorted."""
    return sorted((root / WORKFLOWS_DIR).glob("*.y*ml"))


def read_workflow(path: Path) -> Mapping:
    """Return a workflow's validated top-level mapping."""
    # Actions supports aliases but rejects YAML merge keys, including in actions.
    return as_mapping(load_yaml(path, allow_merges=False), str(path))


def triggers(top: Mapping, path: Path) -> Mapping:
    """Read scalar, sequence or mapping trigger syntax from the same loader."""
    if "on" not in top:
        msg = f"{path.name}: no `on:` trigger"
        raise UnreadableYamlError(msg)
    value = top["on"]
    if isinstance(value, str):
        return {value: None}
    if isinstance(value, list):
        return {as_str(event, f"{path}: on"): None for event in value}
    return as_mapping(value, f"{path}: on")


def jobs(top: Mapping, path: Path) -> dict[str, Mapping]:
    """Validate each job before a check consumes it."""
    return {
        job_id: as_mapping(value, f"{path}: jobs.{job_id}")
        for job_id, value in as_mapping(top.get("jobs", {}), f"{path}: jobs").items()
    }


def steps(job: Mapping, path: Path) -> list[Mapping]:
    """Validate every step and name its location when a shape is wrong."""
    return [
        as_mapping(value, f"{path}: steps[{index}]")
        for index, value in enumerate(
            as_sequence(job.get("steps", []), f"{path}: steps")
        )
    ]


def _unfiltered_pull_request(events: Mapping, path: Path) -> bool:
    if "pull_request" not in events:
        return False
    value = events["pull_request"]
    filters = {} if value is None else as_mapping(value, f"{path}: on.pull_request")
    if unknown := sorted(filters.keys() - _PR_FILTERS):
        msg = f"{path.name}: unknown pull_request filter {unknown}"
        raise UnreadableYamlError(msg)
    if {"paths", "paths-ignore", "branches-ignore"} & filters.keys():
        return False
    if "branches" in filters:
        patterns = scalar_list(
            filters["branches"], path, where="on.pull_request.branches"
        )
        if any(p.startswith("!") for p in patterns) or not any(
            fnmatchcase(DEFAULT_BRANCH, p) for p in patterns
        ):
            return False
    if "types" in filters:
        return (
            set(scalar_list(filters["types"], path, where="on.pull_request.types"))
            >= PR_ACTIVITY
        )
    return True


def _matrix_mapping(value: object, where: str) -> Mapping:
    """Use Actions' case-insensitive matrix property names at every stage."""
    normalized: Mapping = {}
    for key, item in as_mapping(value, where).items():
        folded = key.casefold()
        if folded in normalized:
            msg = f"{where}: duplicate case-insensitive matrix key {key!r}"
            raise UnreadableYamlError(msg)
        normalized[folded] = item
    return normalized


def _matrix_rows(job: Mapping, path: Path) -> list[Mapping]:
    strategy = as_mapping(job.get("strategy", {}), f"{path}: strategy")
    matrix = _matrix_mapping(strategy.get("matrix", {}), f"{path}: strategy.matrix")
    axes = {
        key: as_sequence(value, f"{path}: matrix.{key}")
        for key, value in matrix.items()
        if key not in {"include", "exclude"}
    }
    original = (
        [dict(zip(axes, values, strict=True)) for values in product(*axes.values())]
        if axes
        else []
    )
    exclusions = [
        _matrix_mapping(value, f"{path}: matrix.exclude")
        for value in as_sequence(matrix.get("exclude", []), f"{path}: matrix.exclude")
    ]
    original = [
        row
        for row in original
        if not any(
            all(key in row and row[key] == value for key, value in excluded.items())
            for excluded in exclusions
        )
    ]
    rows = [dict(row) for row in original]
    additions: list[Mapping] = []
    # GitHub applies include after exclude and never merges into added rows.
    for value in as_sequence(matrix.get("include", []), f"{path}: matrix.include"):
        extra = _matrix_mapping(value, f"{path}: matrix.include")
        matched = False
        for base, row in zip(original, rows, strict=True):
            if all(
                key not in axes or base[key] == value for key, value in extra.items()
            ):
                row.update(extra)
                matched = True
        if not matched:
            additions.append(extra)
    return rows + additions


def _checks(path: Path) -> list[Check] | None:
    """Return the checks of a workflow that runs on every PR, else ``None``."""
    top = read_workflow(path)
    if not _unfiltered_pull_request(triggers(top, path), path):
        return None
    checks: list[Check] = []
    for job_id, job in jobs(top, path).items():
        name = as_str(job.get("name", job_id), f"{path}: jobs.{job_id}.name") or job_id
        refs = _MATRIX_REF.findall(name)
        names = [name]
        if refs:
            names = []
            for row in _matrix_rows(job, path):
                expanded = name
                for match in _MATRIX_REF.finditer(name):
                    expanded = expanded.replace(
                        match[0],
                        scalar(
                            row.get(match["key"].casefold(), ""),
                            f"{path}: matrix.{match['key']}",
                        ),
                    )
                names.append(expanded)
            if not names:
                msg = (
                    f"{path.name}: matrix.{refs[0]} is not declared in the job's matrix"
                )
                raise UnreadableYamlError(msg)
        if_expr = entry_value(job.get("if"))
        source = (JobSource(path, job),)
        checks.extend(Check(name, if_expr, "needs" in job, source) for name in names)
    return checks


def every_pr_checks(workflows_dir: Path) -> dict[str, Check]:
    """Return checks from workflows whose pull_request trigger is unfiltered.

    Two jobs with one name report one context; they merge into one check that
    keeps the skippable one's ``if:`` and both jobs, so a duplicate can only make
    the judgement stricter.
    """
    found: dict[str, Check] = {}
    for path in sorted(workflows_dir.glob("*.y*ml")):
        for check in _checks(path) or []:
            found[check.name] = (
                _stricter(found[check.name], check) if check.name in found else check
            )
    return found


def _stricter(kept: Check, other: Check) -> Check:
    base = other if can_skip(other) and not can_skip(kept) else kept
    return replace(base, jobs=(*kept.jobs, *other.jobs))


def can_skip(check: Check) -> bool:
    """Whether a job's ``if:`` (or a failed ``needs:``) could skip its check."""
    if check.if_expr is None:
        return check.has_needs
    match = _EXPR.match(check.if_expr.strip("\"'"))
    body = match["body"] if match else check.if_expr
    return body not in _GUARDS


def entry_value(entry: object) -> str | None:
    """Return an entry's inline scalar, or None when the key is absent."""
    return None if entry is None else scalar(entry)
