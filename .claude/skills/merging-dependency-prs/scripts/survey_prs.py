#!/usr/bin/env python3
"""Survey open Dependabot PRs and emit a triage table.

Usage:
    python3 .agents/skills/merging-dependency-prs/scripts/survey_prs.py [--json]

Requires the `gh` CLI, authenticated against the current repository.
Read-only: this script never mutates PR or branch state, and it is the only
step of the skill that runs without human approval.

Stdlib-only on purpose, so it runs with the system `python3` and needs no
project environment. The classifiers are pure functions, covered by
`scripts/tests/test_survey_prs.py` (`just test-skills`).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import TypedDict, cast


class CheckRun(TypedDict, total=False):
    conclusion: str | None
    state: str | None
    status: str | None
    name: str | None
    context: str | None


class NamedLabel(TypedDict):
    name: str


class ChangedFile(TypedDict, total=False):
    path: str


class Author(TypedDict, total=False):
    login: str


class RawPr(TypedDict, total=False):
    number: int
    title: str
    url: str
    headRefName: str
    baseRefName: str | None
    author: Author | None
    statusCheckRollup: list[CheckRun] | None
    mergeable: str | None
    mergeStateStatus: str | None
    files: list[ChangedFile] | None
    labels: list[NamedLabel] | None
    createdAt: str | None


Row = TypedDict(
    "Row",
    {
        "number": int,
        "title": str,
        "url": str,
        "branch": str,
        "base": "str | None",
        "package": "str | None",
        "from": "str | None",
        "to": "str | None",
        "level": str,
        "pre_one_minor": bool,
        "ecosystem": str,
        "mergeable": "str | None",
        "merge_state": "str | None",
        "checks": str,
        "failing_checks": list[str],
        "files": list[str],
        "labels": list[str],
        "created_at": "str | None",
    },
)

FIELDS = (
    "number,title,author,headRefName,baseRefName,mergeable,mergeStateStatus,"
    "statusCheckRollup,labels,files,createdAt,url"
)

# Matches Dependabot titles such as "bump actions/checkout from 7.0.0 to 7.1.0"
# and "update mypy requirement from >=2.1.0 to >=2.2.0".
BUMP_RE = re.compile(
    r"(?:bump|update)\s+(?P<pkg>\S+?)(?:\s+requirement)?\s+from\s+"
    r"(?P<old>\S+)\s+to\s+(?P<new>\S+)",
    re.IGNORECASE,
)
# A range like ">=3.7" has no patch component, so that group stays optional.
VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")

# The only conclusions that let a PR through the survey's merge gate. An
# allow-list on purpose: a classifier whose default branch is "accept" turns a
# CI state nobody has heard of (STARTUP_FAILURE, STALE, an entry with no
# conclusion at all) into a merge recommendation. NEUTRAL and SKIPPED are how
# a conditional job reports "not applicable", not a failure.
PASSING_STATES = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})
# Not concluded yet: the answer is "come back later", not either verdict.
PENDING_STATES = frozenset({"PENDING", "IN_PROGRESS", "QUEUED", "WAITING", "EXPECTED"})
UNKNOWN_STATE = "UNKNOWN"
# Branch-name ecosystem segments that .github/dependabot.yml configures.
KNOWN_ECOSYSTEMS = frozenset({"github_actions", "pre_commit", "uv"})
# Files every uv PR may share; that overlap lands one PR at a time. The root
# pyproject.toml is the uv workspace root; backend/pyproject.toml is its member.
UV_MANIFEST_FILES = frozenset({"uv.lock", "pyproject.toml", "backend/pyproject.toml"})


class GhError(Exception):
    """The `gh` CLI was unavailable or a read-only call failed."""


def emit(line: str = "") -> None:
    """Write one line to stdout."""
    sys.stdout.write(f"{line}\n")


def gh_json(*args: str) -> list[RawPr]:
    """Run a read-only `gh ... --json` command and return the parsed payload.

    Raises:
        GhError: When `gh` is missing or exits non-zero.
    """
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        msg = (
            "ERR_GH_UNAVAILABLE: could not run the GitHub CLI.\n"
            f"Actual: {exc}\n"
            "Next: install the GitHub CLI, then run `gh auth status`."
        )
        raise GhError(msg) from exc
    if proc.returncode != 0:
        msg = (
            f"ERR_GH_FAILED: `gh {' '.join(args)}` exited with {proc.returncode}.\n"
            f"Actual: {proc.stderr.strip()}\n"
            "Next: run `gh auth status` and confirm this directory has a GitHub remote."
        )
        raise GhError(msg)
    parsed = json.loads(proc.stdout or "[]")
    return cast("list[RawPr]", parsed) if isinstance(parsed, list) else []


def parse_versions(title: str) -> tuple[str | None, str | None, str | None]:
    """Return (package, old_version, new_version) parsed from a PR title."""
    match = BUMP_RE.search(title)
    if not match:
        return None, None, None
    return match["pkg"], match["old"], match["new"]


def _version_parts(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = VERSION_RE.search(value)
    if not match:
        return None
    return int(match[1]), int(match[2])


def semver_level(old: str | None, new: str | None) -> str:
    """Classify a bump's risk, treating a pre-1.0 minor change as major.

    Returns:
        `major`, `minor`, `patch`, or `unknown` when a version is unparsable.
    """
    before, after = _version_parts(old), _version_parts(new)
    if before is None or after is None:
        return "unknown"
    if before[0] != after[0]:
        return "major"
    if before[1] == after[1]:
        return "patch"
    return "major" if before[0] == 0 else "minor"


def is_pre_one_minor_bump(old: str | None, new: str | None) -> bool:
    """Whether both versions are 0.x with different minor numbers."""
    before, after = _version_parts(old), _version_parts(new)
    return (
        before is not None
        and after is not None
        and before[0] == 0
        and after[0] == 0
        and before[1] != after[1]
    )


def check_summary(rollup: list[CheckRun] | None) -> tuple[str, list[str]]:
    """Reduce statusCheckRollup to an overall state plus the failing checks.

    Fails closed: only PASSING_STATES pass and only PENDING_STATES hold; any
    other value, including a conclusion GitHub adds later or none at all, is
    named in the failing list.

    Returns:
        One of `NONE`, `PASSING`, `PENDING`, `FAILING`, and the failing checks
        as `name=STATE`.
    """
    if not rollup:
        return "NONE", []
    failing: list[str] = []
    pending = False
    for check in rollup:
        # Check runs report conclusion/status; commit statuses report state.
        state = str(check.get("conclusion") or check.get("state") or "").upper()
        status = str(check.get("status") or "").upper()
        name = check.get("name") or check.get("context") or "?"
        if not state and status and status != "COMPLETED":
            pending = True  # a check run still in flight has no conclusion yet
        elif state in PENDING_STATES:
            pending = True
        elif state not in PASSING_STATES:
            failing.append(f"{name}={state or UNKNOWN_STATE}")
    if failing:
        return "FAILING", failing
    return ("PENDING", []) if pending else ("PASSING", [])


def ecosystem_of(branch: str) -> str:
    """Classify a Dependabot branch name into an ecosystem.

    `.github/dependabot.yml` configures `github-actions`, `pre-commit`, and `uv`; Dependabot
    names a branch `dependabot/<ecosystem>/<dependency or group>`, so they are
    matched on that segment alone, never on a dependency or group name that
    happens to contain `uv` or `github_actions`. Anything else (a security
    update the repository settings enabled, say) is `other`.
    """
    parts = branch.split("/")
    if len(parts) > 2 and parts[0] == "dependabot" and parts[1] in KNOWN_ECOSYSTEMS:
        return parts[1]
    return "other"


def lands_one_at_a_time(path: str, nums: list[int], rows: list[Row]) -> bool:
    """Whether a contested path is only uv PRs' lock or manifest.

    Two `uv` PRs always contest `uv.lock` (and often `pyproject.toml`); they
    land one at a time while Dependabot regenerates the next lock, so that
    overlap alone does not call for a combined branch.
    """
    uv_numbers = {row["number"] for row in rows if row["ecosystem"] == "uv"}
    return path in UV_MANIFEST_FILES and set(nums) <= uv_numbers


def contested_files(rows: list[Row]) -> dict[str, list[int]]:
    """Map each file touched by more than one PR to the PR numbers touching it."""
    seen: dict[str, list[int]] = {}
    for row in rows:
        for path in row["files"]:
            seen.setdefault(path, []).append(row["number"])
    return {path: nums for path, nums in seen.items() if len(nums) > 1}


def to_row(pr: RawPr) -> Row:
    """Shape one raw `gh pr list` object into a triage row."""
    pkg, old, new = parse_versions(pr.get("title") or "")
    state, failing = check_summary(pr.get("statusCheckRollup"))
    branch = pr.get("headRefName") or ""
    return {
        "number": pr["number"],
        "title": pr.get("title") or "",
        "url": pr.get("url") or "",
        "branch": branch,
        "base": pr.get("baseRefName"),
        "package": pkg,
        "from": old,
        "to": new,
        "level": semver_level(old, new),
        "pre_one_minor": is_pre_one_minor_bump(old, new),
        "ecosystem": ecosystem_of(branch),
        "mergeable": pr.get("mergeable"),
        "merge_state": pr.get("mergeStateStatus"),
        "checks": state,
        "failing_checks": failing,
        "files": [f["path"] for f in pr.get("files") or [] if f.get("path")],
        "labels": [label["name"] for label in pr.get("labels") or []],
        "created_at": pr.get("createdAt"),
    }


def select_bot_rows(prs: list[RawPr]) -> list[Row]:
    """Keep the Dependabot-authored PRs, as triage rows ordered by PR number."""
    rows = [
        to_row(pr)
        for pr in prs
        if "dependabot" in ((pr.get("author") or Author()).get("login") or "")
    ]
    rows.sort(key=lambda row: row["number"])
    return rows


def report(rows: list[Row]) -> None:
    """Print the human-readable triage table."""
    emit(f"{len(rows)} open Dependabot PR(s)")
    emit()
    for row in rows:
        emit(
            f"  #{row['number']:<4} [{row['ecosystem']:<14}] {row['level']:<7} "
            f"checks={row['checks']:<8} merge={row['merge_state'] or '?'}"
        )
        emit(f"        {row['title']}")
        if row["pre_one_minor"]:
            emit("        FLAG: 0.x minor change; review and approve as major.")
        if row["level"] == "unknown":
            emit("        FLAG: versions not parsed from the title; inspect the diff.")
        if row["failing_checks"]:
            emit(f"        FAILING: {', '.join(row['failing_checks'])}")
        emit(f"        files: {', '.join(row['files']) or '(none)'}")
    contested = sorted(contested_files(rows).items())
    one_at_a_time = [
        (path, nums)
        for path, nums in contested
        if lands_one_at_a_time(path, nums, rows)
    ]
    combined = [item for item in contested if item not in one_at_a_time]
    if one_at_a_time:
        emit()
        emit("Overlapping uv files (land one at a time; Dependabot rebases the next):")
        for path, nums in one_at_a_time:
            emit(f"  {path}: {', '.join(f'#{n}' for n in nums)}")
    if combined:
        emit()
        emit("Overlapping files (favor a combined branch):")
        for path, nums in combined:
            emit(f"  {path}: {', '.join(f'#{n}' for n in nums)}")


def main(argv: list[str] | None = None) -> int:
    """Survey the PRs and emit the requested format."""
    parser = argparse.ArgumentParser(description="Survey open Dependabot PRs.")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    try:
        prs = gh_json(
            "pr", "list", "--state", "open", "--limit", "100", "--json", FIELDS
        )
    except GhError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    rows = select_bot_rows(prs)
    if args.json:
        emit(json.dumps(rows, indent=2))
    elif not rows:
        emit("No open Dependabot PRs.")
    else:
        report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
