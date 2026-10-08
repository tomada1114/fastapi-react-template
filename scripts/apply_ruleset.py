"""Create or update the default-branch ruleset from `.github/rulesets/main.json`.

The JSON file is the single source of truth for the ruleset. It is upserted by
name through `gh api repos/{owner}/{repo}/rulesets`: created when no ruleset
carries its name, updated in place by id when one does. The script never
deletes a ruleset, so one a person added by hand survives. Writing rulesets
needs repository admin rights, so running it is a human step.

Usage:
    uv run --locked python scripts/apply_ruleset.py                 # apply via gh
    uv run --locked python scripts/apply_ruleset.py --repo OWNER/REPO
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RULESET_FILE = REPO_ROOT / ".github" / "rulesets" / "main.json"
REQUIRED_KEYS = ("name", "target", "enforcement", "conditions", "rules")
HUMAN_STEP = (
    "a repository admin runs `just ruleset` with an authenticated `gh` "
    "(`gh auth status`)"
)
_DENIED_MARKERS = ("HTTP 403", "HTTP 404")
_PLAN_MARKERS = ("upgrade to github pro", "make this repository public")


class RulesetFileError(ValueError):
    """The ruleset file is unreadable, not JSON, or lacks a required key."""


class GhError(RuntimeError):
    """A `gh` invocation exited non-zero."""


def load_ruleset(path: Path) -> dict[str, Any]:
    """Read and validate the ruleset JSON.

    Returns:
        The parsed ruleset. ``Any``: values are arbitrary JSON.

    Raises:
        RulesetFileError: On an unreadable file, invalid JSON, a non-object
            document, or a missing required key.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise RulesetFileError(str(error)) from error
    except json.JSONDecodeError as error:
        msg = f"invalid JSON: {error}"
        raise RulesetFileError(msg) from error
    if not isinstance(data, dict):
        msg = "top level must be a JSON object"
        raise RulesetFileError(msg)
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        msg = f"missing required keys: {missing}"
        raise RulesetFileError(msg)
    if not isinstance(data["name"], str) or not data["name"]:
        msg = "name must be a non-empty string"
        raise RulesetFileError(msg)
    return data


def _gh(args: list[str], stdin: str | None = None) -> str:
    command = ["gh", *args]
    try:
        result = subprocess.run(  # noqa: S603 -- fixed argv, no shell
            command, check=False, capture_output=True, text=True, input=stdin
        )
    except FileNotFoundError as error:
        msg = f"gh not found on PATH: {error}"
        raise GhError(msg) from error
    if result.returncode != 0:
        msg = f"gh {' '.join(args)}: {result.stderr.strip()}"
        raise GhError(msg)
    return result.stdout


def _gh_json(args: list[str], stdin: str | None = None) -> Any:
    # Any: gh returns arbitrary JSON; callers check its shape.
    output = _gh(args, stdin)
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        msg = f"gh {' '.join(args)}: output is not JSON: {output[:200]!r}"
        raise GhError(msg) from error


def current_repo() -> str:
    """Return ``owner/repo`` of the checkout, as `gh repo view` reports it.

    Raises:
        GhError: When `gh` fails or reports no ``owner/repo``.
    """
    repo = _gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    repo = repo.strip()
    owner, _, name = repo.partition("/")
    if not owner or not name:
        msg = f"gh repo view returned no owner/repo: {repo!r}"
        raise GhError(msg)
    return repo


def find_ruleset_id(repo: str, name: str) -> int | None:
    """Return the id of this repository's own branch ruleset called ``name``.

    Rulesets inherited from an organization are excluded, so an org ruleset
    of the same name is never overwritten.

    Raises:
        GhError: When `gh` fails or returns an unexpected shape.
    """
    # --slurp wraps every page in one array, so the output stays valid JSON.
    pages = _gh_json(
        [
            "api",
            f"repos/{repo}/rulesets?includes_parents=false",
            "--paginate",
            "--slurp",
        ]
    )
    if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
        msg = f"ruleset listing is not a JSON array of pages: {pages!r}"
        raise GhError(msg)
    for entry in (item for page in pages for item in page):
        if (
            isinstance(entry, dict)
            and entry.get("name") == name
            and entry.get("source_type") == "Repository"
            and entry.get("target") == "branch"
        ):
            return int(entry["id"])
    return None


def upsert_command(repo: str, ruleset_id: int | None) -> list[str]:
    """Return the `gh api` argv that creates (POST) or updates (PUT) the ruleset."""
    if ruleset_id is None:
        return ["api", "--method", "POST", f"repos/{repo}/rulesets", "--input", "-"]
    return [
        "api",
        "--method",
        "PUT",
        f"repos/{repo}/rulesets/{ruleset_id}",
        "--input",
        "-",
    ]


def _fail(code: str, detail: str, expected: str, next_step: str) -> int:
    print(f"{code}: {detail}", file=sys.stderr)
    print(f"Expected: {expected}", file=sys.stderr)
    print(f"Next: {next_step}", file=sys.stderr)
    return 1


def _report_gh_error(detail: str) -> int:
    if any(marker in detail.lower() for marker in _PLAN_MARKERS):
        return _fail(
            "ERR_RULESET_PLAN_UNSUPPORTED",
            detail,
            "a public repository, or a plan that supports rulesets on private ones",
            "make the repository public or upgrade its plan, then rerun `just ruleset`",
        )
    denied = any(marker in detail for marker in _DENIED_MARKERS)
    return _fail(
        "ERR_RULESET_GH",
        detail,
        "an authenticated `gh` with admin rights on the repository",
        HUMAN_STEP if denied else "check `gh auth status` and rerun `just ruleset`",
    )


def main(argv: list[str] | None = None, ruleset_file: Path = RULESET_FILE) -> int:
    """Upsert the ruleset and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="OWNER/REPO; defaults to `gh repo view`")
    args = parser.parse_args(argv)
    try:
        ruleset = load_ruleset(ruleset_file)
    except RulesetFileError as error:
        return _fail(
            "ERR_RULESET_FILE",
            f"{ruleset_file}: {error}",
            f"a JSON object with keys {list(REQUIRED_KEYS)}",
            f"fix {ruleset_file} and rerun `just ruleset`",
        )
    try:
        repo = args.repo or current_repo()
        ruleset_id = find_ruleset_id(repo, ruleset["name"])
        applied = _gh_json(upsert_command(repo, ruleset_id), stdin=json.dumps(ruleset))
    except GhError as error:
        return _report_gh_error(str(error))
    applied_id = (
        applied.get("id", ruleset_id) if isinstance(applied, dict) else ruleset_id
    )
    verb = "created" if ruleset_id is None else "updated"
    print(f"{verb}: ruleset {ruleset['name']!r} id {applied_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
