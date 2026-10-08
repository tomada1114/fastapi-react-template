"""Preview or clean explicitly selected merged worktrees.

Usage:
    just worktree-clean <worktree-root> <branch>
    just worktree-clean-apply <worktree-root> <branch>

Exit codes:
    0  the cleanup helper completed
    2  invalid scope or arguments
    otherwise the cleanup helper's exit code
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
CLEANUP_SCRIPT: Final = (
    REPO_ROOT / ".agents" / "skills" / "shipping-issues" / "scripts" / "cleanup_run.sh"
)


def _fail(code: str, detail: str, expected: str, next_step: str) -> int:
    """Report an actionable error without echoing command output or file contents."""
    print(f"{code}: {detail}", file=sys.stderr)
    print(f"Expected: {expected}", file=sys.stderr)
    print(f"Next: {next_step}", file=sys.stderr)
    return 2


def _resolve_worktree_root(path: Path) -> Path | None:
    """Resolve a specific worktree parent; report invalid paths immediately."""
    try:
        worktree_root = path.expanduser().resolve(strict=True)
    except OSError:
        _fail(
            "ERR_WORKTREE_ROOT",
            str(path),
            "an existing directory containing only the worktrees to consider",
            "create the directory or pass its correct path",
        )
        return None
    if not worktree_root.is_dir() or worktree_root == Path(worktree_root.anchor):
        _fail(
            "ERR_WORKTREE_ROOT",
            str(worktree_root),
            "an existing, non-root directory containing only the worktrees to consider",
            "pass the specific worktree parent directory",
        )
        return None
    return worktree_root


def _resolve_executables(cleanup_script: Path) -> tuple[str, str] | None:
    """Resolve the helper and its runtimes before starting any subprocess."""
    if not cleanup_script.is_file():
        _fail(
            "ERR_WORKTREE_CLEANUP_SCRIPT",
            str(cleanup_script),
            "the repository's shipping-issues cleanup helper",
            "restore the helper from .agents/skills/shipping-issues/scripts/cleanup_run.sh",
        )
        return None

    git_executable = shutil.which("git")
    bash_executable = shutil.which("bash")
    if git_executable is None or bash_executable is None:
        _fail(
            "ERR_WORKTREE_TOOLS",
            "git or bash is unavailable on PATH",
            "git and bash to run the repository cleanup helper",
            "restore the local toolchain, then rerun the dry run",
        )
        return None
    return git_executable, bash_executable


def _validate_branches(git_executable: str, branches: Sequence[str]) -> int:
    """Reject invalid branch arguments before invoking cleanup."""
    for branch in branches:
        result = subprocess.run(  # noqa: S603 - fixed argv without a shell
            [
                git_executable,
                "check-ref-format",
                "--branch",
                branch,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return _fail(
                "ERR_WORKTREE_BRANCH",
                branch,
                "a valid local branch name",
                "correct the branch name and retry the dry run",
            )
    return 0


def _run_cleanup(command: list[str], *, apply: bool) -> int:
    """Run the existing helper and translate startup errors into guidance."""
    if apply:
        print(
            "Applying cleanup for the selected merged branches. Ignored files "
            "inside removed worktrees are deleted too."
        )
    else:
        command.append("--dry-run")
        print("Dry run only. Review every listed path; nothing will be removed.")
    try:
        result = subprocess.run(  # noqa: S603 - fixed script path and argv; no shell
            command, check=False
        )
    except OSError as error:
        return _fail(
            "ERR_WORKTREE_CLEANUP_START",
            str(error),
            "bash and Git to be available",
            "restore the local toolchain, then rerun the dry run",
        )
    return result.returncode


def main(
    argv: Sequence[str] | None = None,
    *,
    cleanup_script: Path = CLEANUP_SCRIPT,
) -> int:
    """Run the existing cleanup helper with a narrow, preview-first scope."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="parent directory containing the linked worktrees to consider",
    )
    parser.add_argument(
        "--branch",
        action="append",
        required=True,
        metavar="NAME",
        help="only consider this branch; repeat to select more than one",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the cleanup (the default is a dry run)",
    )
    args = parser.parse_args(argv)

    worktree_root = _resolve_worktree_root(args.root)
    if worktree_root is None:
        return 2
    executables = _resolve_executables(cleanup_script)
    if executables is None:
        return 2
    git_executable, bash_executable = executables
    branches = list(dict.fromkeys(args.branch))
    result = _validate_branches(git_executable, branches)
    if result != 0:
        return result
    command = [
        bash_executable,
        str(cleanup_script),
        "--worktree-root",
        str(worktree_root),
        "--merged-only",
    ]
    for branch in branches:
        command.extend(("--branch", branch))
    return _run_cleanup(command, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
