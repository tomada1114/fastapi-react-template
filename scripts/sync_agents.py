"""Mirror `.agents/skills/` into `.claude/skills/`, byte for byte.

Skills are authored once, under `.agents/skills/` -- the path Codex CLI
discovers project skills from. Claude Code only reads `.claude/skills/`, so the
same tree has to exist there too. A symlink would satisfy both lookups on one
machine but not from a fresh clone on every platform, and Codex follows a
linked directory into its subdirectories, registering a nested
`references/SKILL.md` as a skill of its own. So the second copy is a real,
committed one: generated here (`just agents-sync`) and checked by
`just agents-check`, `tests/test_sync_agents.py`, and the pre-commit hook.

Usage:
    uv run --locked python scripts/sync_agents.py          # rewrite the mirror
    uv run --locked python scripts/sync_agents.py --check  # exit 1 on drift
"""

from __future__ import annotations

import argparse
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = ".agents/skills"
MIRROR_DIRECTORY = ".claude/skills"
# Bytecode a skill's bundled tests leave behind is never part of a skill.
IGNORED_PARTS = frozenset({"__pycache__", ".pytest_cache"})
IGNORED_SUFFIXES = (".pyc",)


class SyncAgentsError(Exception):
    """A skills tree holds an entry the mirror cannot reproduce."""


@dataclass(frozen=True, slots=True)
class TreeDifference:
    """One way in which the mirror disagrees with the source tree."""

    kind: str
    relative: str


def _is_ignored(relative: Path) -> bool:
    return bool(IGNORED_PARTS.intersection(relative.parts)) or relative.name.endswith(
        IGNORED_SUFFIXES
    )


def list_files(directory: Path, label: str) -> list[str]:
    """Return every regular file under ``directory`` as sorted relative paths.

    A missing directory is an empty tree. A symlink anywhere in the tree is
    refused, because a link would make the two copies disagree on a fresh clone.

    Raises:
        SyncAgentsError: When the directory or an entry in it is a symlink or
            neither a file nor a directory.
    """
    if directory.is_symlink():
        msg = (
            f"{label} is a symlink.\n"
            "Expected: a real directory, so syncing cannot overwrite its target.\n"
            "Next: replace the link with a real directory, then run "
            "`just agents-sync`."
        )
        raise SyncAgentsError(msg)
    if not directory.exists():
        return []
    files: list[str] = []
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if _is_ignored(relative):
            continue
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            msg = (
                f"{label}/{relative.as_posix()} is neither a file nor a directory.\n"
                "Expected: real files only, so both copies work from a fresh clone.\n"
                f"Next: replace it with a real file under {SOURCE_DIRECTORY}/, "
                "then run `just agents-sync`."
            )
            raise SyncAgentsError(msg)
        if path.is_file():
            files.append(relative.as_posix())
    return files


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IXUSR)


def diff_trees(source: Path, mirror: Path) -> list[TreeDifference]:
    """Report every way in which ``mirror`` disagrees with ``source``."""
    source_files = list_files(source, SOURCE_DIRECTORY)
    mirror_files = set(list_files(mirror, MIRROR_DIRECTORY))
    differences: list[TreeDifference] = []
    for relative in source_files:
        if relative not in mirror_files:
            differences.append(TreeDifference("missing", relative))
        elif (source / relative).read_bytes() != (mirror / relative).read_bytes() or (
            # A skill script invoked from the mirror must stay runnable there.
            _is_executable(source / relative) != _is_executable(mirror / relative)
        ):
            differences.append(TreeDifference("differs", relative))
        mirror_files.discard(relative)
    differences.extend(
        TreeDifference("extra", relative) for relative in sorted(mirror_files)
    )
    return differences


def sync_trees(source: Path, mirror: Path) -> list[TreeDifference]:
    """Make ``mirror`` an exact copy of ``source`` and return what changed."""
    differences = diff_trees(source, mirror)
    for difference in differences:
        target = mirror / difference.relative
        if difference.kind == "extra":
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / difference.relative, target)
        shutil.copymode(source / difference.relative, target)
    if mirror.exists():
        # Deepest first, so a parent emptied by its children's removal goes too.
        for directory in sorted(
            (p for p in mirror.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)
        ):
            if not any(directory.iterdir()):
                directory.rmdir()
    return differences


def main(argv: list[str] | None = None, root: Path = REPO_ROOT) -> int:
    """Run the sync or the drift check and return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit 1 instead of rewriting the mirror",
    )
    args = parser.parse_args(argv)
    source = root / SOURCE_DIRECTORY
    mirror = root / MIRROR_DIRECTORY
    try:
        if args.check:
            differences = diff_trees(source, mirror)
        else:
            differences = sync_trees(source, mirror)
    except SyncAgentsError as error:
        print(f"ERR_AGENTS_UNSUPPORTED_ENTRY: {error}", file=sys.stderr)
        return 1
    if args.check and differences:
        print(
            f"ERR_AGENTS_DRIFT: {MIRROR_DIRECTORY}/ disagrees with "
            f"{SOURCE_DIRECTORY}/:",
            file=sys.stderr,
        )
        for difference in differences:
            print(f"  {difference.kind}: {difference.relative}", file=sys.stderr)
        print(
            "Expected: identical file contents and executable permissions in both trees.",
            file=sys.stderr,
        )
        print(
            f"Next: edit {SOURCE_DIRECTORY}/ only, then run `just agents-sync` "
            "and stage both trees.",
            file=sys.stderr,
        )
        return 1
    if not args.check:
        print(f"agents-sync: {len(differences)} file(s) updated in {MIRROR_DIRECTORY}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
