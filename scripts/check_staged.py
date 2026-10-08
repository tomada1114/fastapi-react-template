"""Refuse a commit that would put a secret into history, judged from the index.

This is the secret gate of the pre-commit layer (`.pre-commit-config.yaml`,
hook id `check-staged`). It runs on `git commit` itself, so it holds for every
author -- a human, Claude Code, Codex CLI, or any other tool -- rather than only
for the agent whose hook configuration happened to be loaded.

The scope is deliberately narrow: a secret-shaped path (`.env`, `secrets/**`,
a key file, a personal agent settings file) or credential-shaped content in a
staged file. Anything else a commit might do is a judgement call that belongs
in the pull request. A hook that refuses legitimate work teaches its author to
reach for `--no-verify`, which switches this check off along with the rest.

Each staged path is judged in two phases: the path first, then -- only when the
path passes -- the staged blob. Staged blobs are read by id from the index
through one `git cat-file --batch` process; the allowlist, when present, through
one more, before it. A partially staged file is judged exactly as it will be
committed, and a refused path's content is never read. Output names the path
and the rule, never the matched text.

Exemptions live in one place: `.check-staged-allow` at the repository root,
read from the index the commit is made from (never the working tree), so the
exemption that applies is the one this commit contains. Each entry sits below a
`# reason` comment and is exact. `path <file>` lets one file past the path
rules; its content is still scanned. `content <file> <blob id>` lets that one
staged content of that file past the content patterns; any edit changes the
blob id, and the content is judged again. Globs, directories, and `.` are
refused, and an entry the index no longer matches -- a file gone or renamed,
content edited, a path no rule refuses, content no pattern matches -- fails the
commit until it is removed. A malformed or too broad allowlist judges nothing.

Deletions are not inspected: removing a file cannot add a secret, and refusing
it would block the very commit that removes one. Git runs with the inherited
environment on purpose: `git commit -a` and `git commit -- <path>` hand the hook
a temporary index through `GIT_INDEX_FILE`, and that index is what is committed.

During a merge, a staged entry whose blob (and mode) is identical to the one at
the same path in a commit being merged in is not judged again: that content was
judged when it entered the other side's history. Re-judging it would refuse
every later merge of that branch once anything matching had landed on it, and
the only way out would be to drop the other side's file. Conflict resolutions
and any other content new to both sides are still judged.

The script is stdlib-only and runs on Python 3.10+, the oldest interpreter
pre-commit itself supports, because pre-commit runs it (`language: python`)
with its own interpreter rather than the project's environment.

Usage:
    python scripts/check_staged.py

Exit codes:
    0  nothing staged is refused (including when nothing is staged)
    1  a staged path or staged content was refused
    2  git could not list or read the staged changes
    3  .check-staged-allow is malformed, too broad, or stale
"""

from __future__ import annotations

import argparse
import enum
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence

# A submodule entry names a commit in another repository; there is no blob here.
GITLINK_MODE: Final = "160000"
SYMLINK_MODE: Final = "120000"
REGULAR_FILE_MODES: Final = ("100644", "100755")
# `--no-renames` reports a rename as a deletion plus an addition, so every
# entry carries exactly one path; deletions (D) are left out on purpose.
STAGED_STATUS_FILTER: Final = "ACMT"
RAW_FIELDS_PER_ENTRY: Final = 2
RAW_META_WORDS: Final = 5
BATCH_HEADER_WORDS: Final = 3
LS_FILES_META_WORDS: Final = 3
MERGED_STAGE: Final = "0"
BLOB_TYPE: Final = "blob"
FRAME_TERMINATOR: Final = b"\n"

ENV_FILE_NAME: Final = ".env"
DIRENV_FILE_NAME: Final = ".envrc"
# A `.env.*` or `.envrc.*` name ending in one of these is a copy meant to be
# committed; its content is still scanned.
SAMPLE_SUFFIXES: Final = (".example", ".sample", ".template")
SECRETS_DIRECTORY: Final = "secrets"
KEY_FILE_SUFFIXES: Final = (".pem", ".key")
SSH_KEY_PREFIX: Final = "id_rsa"

CLAUDE_DIRECTORY: Final = ".claude"
CLAUDE_LOCAL_SETTINGS_NAME: Final = "settings.local.json"
CODEX_LOCAL_RULES_PATH: Final = ".codex/rules/local.rules"
MERGE_HEAD_REF: Final = "MERGE_HEAD"
GITHEAD_ENV_PREFIX: Final = "GITHEAD_"
OBJECT_ID: Final = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
# Shared by every listing so user configuration cannot change its shape:
# `diff.relative` (paths relative to the current directory), colour, and
# rename or copy detection (two paths per entry).
RAW_DIFF_ARGS: Final = (
    "diff",
    "--cached",
    "--raw",
    "-z",
    "--no-abbrev",
    "--no-renames",
    "--no-relative",
    "--no-color",
)

# `--full-name` prints paths from the repository root wherever the hook runs,
# and `:(top...)` matches from the root; `literal` turns off glob magic. Only
# these two constant pathspecs are ever passed: allowlist entries are resolved
# against the whole listing in Python, so no entry path reaches argv.
LS_FILES_ARGS: Final = ("ls-files", "--stage", "-z", "--full-name", "--")
ALLOWLIST_PATHSPEC: Final = ":(top,literal).check-staged-allow"
WHOLE_INDEX_PATHSPEC: Final = ":(top)"

ALLOWLIST_PATH: Final = ".check-staged-allow"
PATH_KEYWORD: Final = "path"
CONTENT_KEYWORD: Final = "content"
COMMENT_PREFIX: Final = "#"
BYTE_ORDER_MARK: Final = "\ufeff"
GLOB_CHARACTERS: Final = frozenset("*?")
DRIVE_LETTER: Final = re.compile(r"[A-Za-z]:")
IMPLICIT_SEGMENTS: Final = frozenset({"", ".", ".."})
# Lines split on "\n" alone, as git, GitHub, and editors do. Any other control
# or line-separator character is refused outright: a splitter that broke on it
# would see two lines where a reviewer reads one. A tab is allowed.
LINE_SEPARATOR: Final = "\n"
CARRIAGE_RETURN: Final = "\r"
FORBIDDEN_CHARACTERS: Final = re.compile("[\x00-\x08\x0a-\x1f\x7f\x85\u2028\u2029]")

FIX_HINT: Final = (
    "Remove the secret from the file and `git add` it again, or take the path "
    "out of the index with `git rm --cached <path>` and list it in .gitignore. "
    "A file you believe is not a secret (a public certificate, a test fixture) "
    "is a human's call: they can exempt it with a reviewed entry in "
    ".check-staged-allow (see "
    ".agents/skills/changing-gates/references/pre-commit-layer.md). "
    "Never bypass this check with --no-verify."
)
MERGE_FIX_HINT: Final = (
    "A merge is in progress: remove the secret from each refused file and "
    "`git add` it again. Do not `git rm --cached` or `git restore --staged` a "
    "path here -- that would also drop the other side's change to it. "
    "Never bypass this check with --no-verify."
)


class ExitCode(enum.IntEnum):
    """Process exit status of this script."""

    OK = 0
    BLOCKED = 1
    GIT_FAILED = 2
    ALLOWLIST_INVALID = 3


# `str, Enum` rather than StrEnum, which needs 3.11 (see the module docstring).
class BlockedPath(str, enum.Enum):
    """Why a staged path is refused on its name alone."""

    ENV_FILE = (
        "an environment file (.env, .env.*) can hold real values; "
        "commit a .example, .sample, or .template copy instead"
    )
    DIRENV_FILE = "a direnv file (.envrc, .envrc.*) can export real values"
    SECRETS_DIRECTORY = "files under a secrets/ directory hold credentials"
    KEY_FILE = "a .pem or .key file is a key or certificate container"
    SSH_KEY = "an id_rsa* file is an SSH key"
    PERSONAL_SETTINGS = "personal agent settings stay local (they are gitignored)"


class SecretKind(str, enum.Enum):
    """A credential shape searched for in staged content."""

    AWS_ACCESS_KEY = "AWS access key"
    GITHUB_PAT = "GitHub token"
    GITHUB_FINE_GRAINED_PAT = "GitHub fine-grained token"
    ANTHROPIC_API_KEY = "Anthropic API key"
    OPENAI_PROJECT_KEY = "OpenAI project key"
    OPENROUTER_API_KEY = "OpenRouter API key"
    SLACK_CREDENTIAL = "Slack token"
    STRIPE_LIVE_KEY = "Stripe live secret key"
    PRIVATE_KEY = "private key"


# Every prefix must be followed by a token body, so a document (or this file)
# that merely names a prefix such as `ghp_` is not refused. Each minimum body
# length is at or below the length of the real tokens that issuer hands out.
# A token prefix must also start a word: without that left boundary, prose such
# as "risk-or-reward-..." or "desk-proj-overview-..." would read as a key.
# A Slack token body starts with a digit (a workspace or version number), which
# keeps a word like "xoxo-gossip-..." from matching even at a word start.
WORD_START: Final = r"(?<![A-Za-z0-9_-])"
# The PEM header covers the PEM private-key types (RSA, EC, DSA, OPENSSH,
# ENCRYPTED, and plain PKCS#8); an armored PGP key ("PRIVATE KEY BLOCK") is
# not PEM and is not matched.
SECRET_PATTERNS: Final[tuple[tuple[SecretKind, re.Pattern[str]], ...]] = (
    (SecretKind.AWS_ACCESS_KEY, re.compile(r"AKIA[0-9A-Z]{16}")),
    (SecretKind.GITHUB_PAT, re.compile(rf"{WORD_START}ghp_[A-Za-z0-9]{{36}}")),
    (
        SecretKind.GITHUB_FINE_GRAINED_PAT,
        re.compile(rf"{WORD_START}github_pat_[A-Za-z0-9_]{{22,}}"),
    ),
    (
        SecretKind.ANTHROPIC_API_KEY,
        re.compile(rf"{WORD_START}sk-ant-[A-Za-z0-9_-]{{20,}}"),
    ),
    (
        SecretKind.OPENAI_PROJECT_KEY,
        re.compile(rf"{WORD_START}sk-proj-[A-Za-z0-9_-]{{20,}}"),
    ),
    (
        SecretKind.OPENROUTER_API_KEY,
        re.compile(rf"{WORD_START}sk-or-[A-Za-z0-9_-]{{20,}}"),
    ),
    (
        SecretKind.SLACK_CREDENTIAL,
        re.compile(rf"{WORD_START}xox[abposr]-[0-9][A-Za-z0-9-]{{9,}}"),
    ),
    (
        SecretKind.STRIPE_LIVE_KEY,
        re.compile(rf"{WORD_START}sk_live_[A-Za-z0-9]{{20,}}"),
    ),
    (SecretKind.PRIVATE_KEY, re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
)


class AllowlistProblemKind(str, enum.Enum):
    """What is wrong with `.check-staged-allow`, as its stderr code."""

    FILE = "ERR_STAGED_ALLOWLIST_FILE"
    SYNTAX = "ERR_STAGED_ALLOWLIST_SYNTAX"
    TOO_BROAD = "ERR_STAGED_ALLOWLIST_TOO_BROAD"
    STALE = "ERR_STAGED_ALLOWLIST_STALE"

    @property
    def expected(self) -> str:
        """The `Expected:` line of this problem's report."""
        return ALLOWLIST_REMEDIES[self][0]

    @property
    def next_step(self) -> str:
        """The `Next:` line of this problem's report; `{line}` is the line number."""
        return ALLOWLIST_REMEDIES[self][1]


ALLOWLIST_REMEDIES: Final[dict[AllowlistProblemKind, tuple[str, str]]] = {
    AllowlistProblemKind.FILE: (
        f"a regular UTF-8 text file named {ALLOWLIST_PATH} at the repository root",
        (
            f"replace it with a regular UTF-8 file, git add {ALLOWLIST_PATH}, "
            "and commit again"
        ),
    ),
    AllowlistProblemKind.SYNTAX: (
        (
            "`path <file>` or `content <file> <blob id>` below a `# reason` comment, "
            "the file's path from the repository root, unquoted, as "
            "`git -c core.quotePath=false ls-files --full-name` prints it"
        ),
        (
            f"fix line {{line}} of {ALLOWLIST_PATH}, git add {ALLOWLIST_PATH}, "
            "and commit again"
        ),
    ),
    AllowlistProblemKind.TOO_BROAD: (
        'one exact file per entry; globs, directories, and "." are not accepted',
        (
            "list each file on its own line (`git ls-files -- <directory>` prints "
            f"them), git add {ALLOWLIST_PATH}, and commit again"
        ),
    ),
    AllowlistProblemKind.STALE: (
        (
            "every entry names a file in this commit that the gate would otherwise "
            "refuse; a content entry carries the file's current blob id "
            "(`git rev-parse :<file>`)"
        ),
        (
            f"remove line {{line}} of {ALLOWLIST_PATH} if this change deleted or "
            "renamed its file; any other edit to it is a human's reviewed decision; "
            f"then git add {ALLOWLIST_PATH} and commit again"
        ),
    ),
}


class GitError(Exception):
    """Git could not list or read the staged changes."""


@dataclass(frozen=True, slots=True)
class StagedEntry:
    """One path in the index, with the mode and blob id it is staged with."""

    path: str
    mode: str
    blob_id: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One refused staged path and the rule that refused it."""

    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class AllowEntry:
    """One exemption in `.check-staged-allow`.

    A `path` entry has no blob id; a `content` entry always has one.
    """

    kind: Literal["path", "content"]
    path: str
    blob_id: str | None
    line: int


@dataclass(frozen=True, slots=True)
class AllowlistProblem:
    """One reason `.check-staged-allow` cannot be used as it stands.

    `detail` never quotes the line: a token pasted into a malformed line must
    not reach the terminal.
    """

    kind: AllowlistProblemKind
    line: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class Allowlist:
    """The valid entries of `.check-staged-allow`, in file order."""

    entries: tuple[AllowEntry, ...]
    # Derived from `entries` once, in __post_init__; never passed in.
    paths: frozenset[str] = field(init=False, compare=False)
    contents: dict[tuple[str, str], int] = field(init=False, compare=False)

    def __post_init__(self) -> None:
        """Index the entries: the exempt paths, and each content pair's line."""
        object.__setattr__(
            self,
            "paths",
            frozenset(
                entry.path for entry in self.entries if entry.kind == PATH_KEYWORD
            ),
        )
        object.__setattr__(
            self,
            "contents",
            {
                (entry.path, entry.blob_id): entry.line
                for entry in self.entries
                if entry.blob_id is not None
            },
        )


EMPTY_ALLOWLIST: Final = Allowlist(entries=())


@dataclass(frozen=True, slots=True)
class Verdict:
    """What judging the index found: refused paths, and stale content entries."""

    findings: tuple[Finding, ...]
    problems: tuple[AllowlistProblem, ...]


def _run_git(args: Sequence[str], stdin: bytes | None = None) -> bytes:
    """Run git in the current directory and return its standard output.

    Raises:
        GitError: git could not be started or exited non-zero.
    """
    command = ["git", *args]
    try:
        # Arguments are constants or commit ids: no path read from the index or
        # the allowlist ever reaches argv, so this error text never holds one.
        completed = subprocess.run(  # noqa: S603 -- constant argv, no shell
            command,
            input=stdin,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        msg = f"could not run `{' '.join(command)}`: {error}"
        raise GitError(msg) from error
    if completed.returncode != 0:
        stderr = os.fsdecode(completed.stderr).strip()
        msg = f"`{' '.join(command)}` exited {completed.returncode}: {stderr}"
        raise GitError(msg)
    return completed.stdout


def _raw_diff(*args: str) -> list[StagedEntry]:
    """Run `git diff --cached --raw` with `args` and parse its records.

    Raises:
        GitError: git failed or printed a record of an unexpected shape.
    """
    fields = _run_git([*RAW_DIFF_ARGS, *args]).split(b"\0")
    entries = []
    for index in range(0, len(fields) - 1, RAW_FIELDS_PER_ENTRY):
        meta = fields[index].decode("ascii").split()
        if len(meta) != RAW_META_WORDS:
            msg = f"unexpected `git diff --raw` record: {fields[index]!r}"
            raise GitError(msg)
        _, new_mode, _, new_blob_id, _ = meta
        entries.append(
            StagedEntry(
                path=os.fsdecode(fields[index + 1]),
                mode=new_mode,
                blob_id=new_blob_id,
            ),
        )
    return entries


def staged_entries() -> list[StagedEntry]:
    """List the staged additions, modifications, and type changes.

    Returns:
        One entry per staged path that has content to commit, in index order.

    Raises:
        GitError: git could not list the index.
    """
    return _raw_diff(f"--diff-filter={STAGED_STATUS_FILTER}")


def merge_heads() -> list[str]:
    """Return the commits being merged in, or an empty list outside a merge.

    Two sources, because git exposes the merge differently per hook. A clean
    `git merge` runs pre-merge-commit before it writes MERGE_HEAD, but exports
    a `GITHEAD_<commit id>` variable for each head it merges; the `git commit`
    that concludes a conflicted merge has MERGE_HEAD on disk instead.

    Raises:
        GitError: git could not locate the repository's MERGE_HEAD file.
    """
    from_environment = [
        name.removeprefix(GITHEAD_ENV_PREFIX)
        for name in os.environ
        if name.startswith(GITHEAD_ENV_PREFIX)
        and OBJECT_ID.fullmatch(name.removeprefix(GITHEAD_ENV_PREFIX))
    ]
    merge_head = Path(
        os.fsdecode(_run_git(["rev-parse", "--git-path", MERGE_HEAD_REF])).strip(),
    )
    try:
        from_file = merge_head.read_text(encoding="ascii").split()
    except FileNotFoundError:
        from_file = []
    return list(dict.fromkeys([*from_file, *from_environment]))


def paths_identical_in(commit: str, paths: Collection[str]) -> set[str]:
    """Return the paths whose staged blob and mode equal those in `commit`.

    Raises:
        GitError: git could not compare the index with `commit`.
    """
    differing = {entry.path for entry in _raw_diff(commit)}
    return {path for path in paths if path not in differing}


def _is_personal_settings(path: PurePosixPath) -> bool:
    # .claude/settings.local.json is gitignored at any depth; the Codex rules
    # file only at the root.
    is_claude_local = path.parts[-2:] == (CLAUDE_DIRECTORY, CLAUDE_LOCAL_SETTINGS_NAME)
    return is_claude_local or path.as_posix() == CODEX_LOCAL_RULES_PATH


def _is_under_secrets_directory(path: PurePosixPath) -> bool:
    return SECRETS_DIRECTORY in path.parts[:-1]


def _is_variant_of(path: PurePosixPath, name: str) -> bool:
    """Return whether `path` is `name` or a `name.*` variant that is not a sample."""
    if path.name == name:
        return True
    return path.name.startswith(f"{name}.") and not path.name.endswith(SAMPLE_SUFFIXES)


def _is_env_file(path: PurePosixPath) -> bool:
    return _is_variant_of(path, ENV_FILE_NAME)


def _is_direnv_file(path: PurePosixPath) -> bool:
    return _is_variant_of(path, DIRENV_FILE_NAME)


def _is_key_file(path: PurePosixPath) -> bool:
    return path.name.endswith(KEY_FILE_SUFFIXES)


def _is_ssh_key(path: PurePosixPath) -> bool:
    return path.name.startswith(SSH_KEY_PREFIX)


# Checked in order; the first rule that matches names the reason.
PATH_RULES: Final[tuple[tuple[BlockedPath, Callable[[PurePosixPath], bool]], ...]] = (
    (BlockedPath.PERSONAL_SETTINGS, _is_personal_settings),
    (BlockedPath.SECRETS_DIRECTORY, _is_under_secrets_directory),
    (BlockedPath.ENV_FILE, _is_env_file),
    (BlockedPath.DIRENV_FILE, _is_direnv_file),
    (BlockedPath.KEY_FILE, _is_key_file),
    (BlockedPath.SSH_KEY, _is_ssh_key),
)


def blocked_path_reason(path: str) -> BlockedPath | None:
    """Return why a repository-relative path must never be committed.

    Paths are compared case-insensitively: on the case-insensitive file
    systems macOS and Windows use by default, `.ENV` is the same file as
    `.env`.

    Args:
        path: A path relative to the repository root, `/`-separated.

    Returns:
        The rule that refuses the path, or None when the path is allowed.
    """
    lowered = PurePosixPath(path.lower())
    return next((reason for reason, matches in PATH_RULES if matches(lowered)), None)


def secret_kind(content: bytes) -> SecretKind | None:
    """Return the first credential shape found in a blob's content.

    Content that is not valid UTF-8 (an image, an archive) is not scanned:
    the patterns are textual, and a lossy decode would only add noise.

    Args:
        content: The raw bytes of one staged blob.

    Returns:
        The matching credential kind, or None when nothing matches.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    for kind, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return kind
    return None


def read_blobs(blob_ids: Sequence[str]) -> list[bytes]:
    """Read blobs by id through a single `git cat-file --batch` process.

    Args:
        blob_ids: Object ids of blobs in the index.

    Returns:
        The content of each blob, in the order requested.

    Raises:
        GitError: git failed, or answered with anything but the requested blob.
    """
    if not blob_ids:
        return []
    request = "".join(f"{blob_id}\n" for blob_id in blob_ids).encode("ascii")
    output = _run_git(["cat-file", "--batch"], stdin=request)
    contents = []
    offset = 0
    for blob_id in blob_ids:
        header_end = output.find(b"\n", offset)
        header = output[offset : header_end if header_end >= 0 else len(output)]
        words = header.decode("ascii", errors="replace").split()
        if (
            header_end < 0
            or len(words) != BATCH_HEADER_WORDS
            or words[0] != blob_id
            or words[1] != BLOB_TYPE
            or not words[2].isdigit()
        ):
            # The header is not echoed: a misaligned frame could be blob content.
            msg = f"`git cat-file --batch` did not return blob {blob_id}"
            raise GitError(msg)
        start = header_end + 1
        end = start + int(words[2])
        if output[end : end + 1] != FRAME_TERMINATOR:
            msg = f"`git cat-file --batch` returned a truncated blob {blob_id}"
            raise GitError(msg)
        contents.append(output[start:end])
        offset = end + 1
    return contents


def _syntax(line: int, detail: str) -> AllowlistProblem:
    return AllowlistProblem(AllowlistProblemKind.SYNTAX, line, detail)


# Checked in order; the first that holds names the problem with an entry's path.
# Whitespace and NUL come first: the later checks read the path as git would.
PATH_CHECKS: Final[
    tuple[tuple[Callable[[str], bool], AllowlistProblemKind, str], ...]
] = (
    (lambda path: not path, AllowlistProblemKind.SYNTAX, "the entry has no path"),
    (
        lambda path: "\0" in path,
        AllowlistProblemKind.SYNTAX,
        "the path holds a NUL character, which no git path can",
    ),
    (
        lambda path: path != path.strip(),
        AllowlistProblemKind.SYNTAX,
        "the path has leading or trailing whitespace",
    ),
    (
        lambda path: not GLOB_CHARACTERS.isdisjoint(path),
        AllowlistProblemKind.TOO_BROAD,
        "the path is a glob (* or ?)",
    ),
    (
        lambda path: path.endswith("/"),
        AllowlistProblemKind.TOO_BROAD,
        "the path ends with /, so it names a directory",
    ),
    (
        lambda path: path == ".",
        AllowlistProblemKind.TOO_BROAD,
        "the path is ., the whole repository",
    ),
    (
        lambda path: path.startswith("/") or DRIVE_LETTER.match(path) is not None,
        AllowlistProblemKind.SYNTAX,
        "the path is absolute; write it from the repository root, as git does",
    ),
    (
        lambda path: "\\" in path,
        AllowlistProblemKind.SYNTAX,
        "the path contains \\; use /, as git does",
    ),
    (
        lambda path: not IMPLICIT_SEGMENTS.isdisjoint(path.split("/")),
        AllowlistProblemKind.SYNTAX,
        "the path has an empty, ., or .. segment",
    ),
)


def _path_problem(path: str, line: int) -> AllowlistProblem | None:
    return next(
        (
            AllowlistProblem(kind, line, detail)
            for check, kind, detail in PATH_CHECKS
            if check(path)
        ),
        None,
    )


def _parse_entry(line: str, number: int) -> AllowEntry | AllowlistProblem:
    """Parse one line that is neither blank nor a comment."""
    keyword, _, rest = line.partition(" ")
    if keyword == PATH_KEYWORD:
        return _path_problem(rest, number) or AllowEntry(
            kind="path", path=rest, blob_id=None, line=number
        )
    if keyword != CONTENT_KEYWORD:
        indented = line.lstrip().partition(" ")[0] in {PATH_KEYWORD, CONTENT_KEYWORD}
        return _syntax(
            number,
            "an entry starts in column 0"
            if indented
            else "unknown keyword; an entry starts with `path` or `content`",
        )
    path, separator, blob_id = rest.rpartition(" ")
    if not separator or not blob_id:
        return _syntax(number, "a content entry needs a path and a blob id")
    if problem := _path_problem(path, number):
        return problem
    if not OBJECT_ID.fullmatch(blob_id):
        return _syntax(
            number, "the blob id is not 40 or 64 lowercase hexadecimal characters"
        )
    return AllowEntry(kind="content", path=path, blob_id=blob_id, line=number)


def parse_allowlist(text: str) -> tuple[Allowlist, list[AllowlistProblem]]:
    """Parse the text of `.check-staged-allow`, collecting every problem.

    Only the rules that need no git are applied here: the grammar, the reason
    comment each entry sits below, duplicates, and the paths that are too
    broad on their face. `resolve_allowlist` checks the entries against the
    index.

    Args:
        text: The decoded file; CRLF line endings and a leading BOM are fine.
            Lines split on LF alone, so the line numbers are an editor's.

    Returns:
        The valid entries, and a SYNTAX or TOO_BROAD problem for each line
        that is not one, in line order.
    """
    entries: list[AllowEntry] = []
    problems: list[AllowlistProblem] = []
    first_seen: dict[tuple[str, str, str | None], int] = {}
    reason: Literal["none", "empty", "text"] = "none"
    lines = text.removeprefix(BYTE_ORDER_MARK).split(LINE_SEPARATOR)
    if lines[-1] == "":
        lines.pop()
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.removesuffix(CARRIAGE_RETURN)
        if FORBIDDEN_CHARACTERS.search(line):
            problems.append(
                _syntax(
                    number,
                    "the line holds a control or line-separator character "
                    "(only a tab is allowed)",
                ),
            )
            reason = "none"
            continue
        if not line.strip():
            reason = "none"
            continue
        comment = line.lstrip()
        if comment.startswith(COMMENT_PREFIX):
            has_text = comment.removeprefix(COMMENT_PREFIX).strip()
            reason = "text" if has_text else "empty"
            continue
        parsed = _parse_entry(line, number)
        if isinstance(parsed, AllowlistProblem):
            problems.append(parsed)
        elif reason == "none":
            problems.append(
                _syntax(number, "the entry has no # reason comment directly above it")
            )
        elif reason == "empty":
            problems.append(
                _syntax(number, "an entry needs a reason comment with text")
            )
        elif (key := (parsed.kind, parsed.path, parsed.blob_id)) in first_seen:
            problems.append(_syntax(number, f"duplicates line {first_seen[key]}"))
        else:
            first_seen[key] = number
            entries.append(parsed)
    return Allowlist(entries=tuple(entries)), problems


def _ls_files(pathspec: str) -> tuple[list[StagedEntry], set[str]]:
    """List the index records `pathspec`, one of the constants above, matches.

    Returns:
        The merged records, and the paths of the unmerged ones (stage not 0).

    Raises:
        GitError: git failed or printed a record of an unexpected shape.
    """
    output = _run_git([*LS_FILES_ARGS, pathspec])
    entries: list[StagedEntry] = []
    unmerged: set[str] = set()
    if not output:
        return entries, unmerged
    for record in output.removesuffix(b"\0").split(b"\0"):
        meta, tab, raw_path = record.partition(b"\t")
        words = meta.decode("ascii", errors="replace").split()
        if (
            not tab
            or len(words) != LS_FILES_META_WORDS
            or not OBJECT_ID.fullmatch(words[1])
        ):
            msg = f"unexpected `git ls-files --stage` record: {meta!r}"
            raise GitError(msg)
        mode, blob_id, stage = words
        path = os.fsdecode(raw_path)
        if stage == MERGED_STAGE:
            entries.append(StagedEntry(path=path, mode=mode, blob_id=blob_id))
        else:
            unmerged.add(path)
    return entries, unmerged


def _unmerged_error() -> GitError:
    # The path is not named: it may be an allowlist entry's.
    return GitError(
        f"the index holds an unmerged path that {ALLOWLIST_PATH} names; "
        "resolve it and `git add` it first"
    )


def _at_or_under(path: str, entry_path: str) -> bool:
    return path == entry_path or path.startswith(f"{entry_path}/")


def _file_problem(detail: str) -> list[AllowlistProblem]:
    return [AllowlistProblem(AllowlistProblemKind.FILE, None, detail)]


def read_allowlist() -> tuple[Allowlist, list[AllowlistProblem]]:
    """Read and parse `.check-staged-allow` from the index.

    The index is the one the commit is made from, which includes the temporary
    index `git commit -a` and `git commit -- <path>` pass in `GIT_INDEX_FILE`.

    Returns:
        The allowlist (empty when the index has none) and its FILE, SYNTAX,
        and TOO_BROAD problems.

    Raises:
        GitError: git could not list or read the index.
    """
    records, unmerged = _ls_files(ALLOWLIST_PATHSPEC)
    if unmerged:
        raise _unmerged_error()
    if not records:
        return EMPTY_ALLOWLIST, []
    if any(record.path != ALLOWLIST_PATH for record in records):
        return EMPTY_ALLOWLIST, _file_problem("is a directory in the index")
    (record,) = records
    if record.mode not in REGULAR_FILE_MODES:
        kind = {SYMLINK_MODE: "a symbolic link", GITLINK_MODE: "a submodule"}
        what = kind.get(record.mode, "not a regular file")
        return EMPTY_ALLOWLIST, _file_problem(f"is {what} in the index")
    (content,) = read_blobs([record.blob_id])
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return EMPTY_ALLOWLIST, _file_problem("is not valid UTF-8")
    return parse_allowlist(text)


def _stale_detail(entry: AllowEntry, record: StagedEntry) -> str | None:
    """Say why an entry naming a file in the index is stale, or None if it is not."""
    if entry.kind == PATH_KEYWORD:
        if blocked_path_reason(entry.path) is None:
            return "no path rule refuses this file, so it needs no path entry"
        return None
    if record.mode == GITLINK_MODE:
        return "names a submodule, whose content is never scanned"
    if record.blob_id != entry.blob_id:
        return (
            "the blob id is not the content staged at this path "
            "(`git rev-parse :<file>` prints it)"
        )
    return None


def resolve_allowlist(allowlist: Allowlist) -> list[AllowlistProblem]:
    """Check each entry against the index.

    Returns:
        A TOO_BROAD problem for an entry that names a directory in the index,
        and a STALE problem for one the index does not match: no such file, a
        path no rule refuses, a blob id that is not the staged one, or a
        content entry on a submodule. A content entry whose staged content
        matches no pattern is found later, by `find_violations`.

    Each entry is matched against one listing of the whole index, exactly:
    byte for byte and case-sensitively, as git compares paths.

    Raises:
        GitError: git could not list the index, it printed a malformed record,
            or an entry names an unmerged path or a directory holding one.
    """
    if not allowlist.entries:
        return []
    records, unmerged = _ls_files(WHOLE_INDEX_PATHSPEC)
    if any(
        _at_or_under(path, entry.path)
        for entry in allowlist.entries
        for path in unmerged
    ):
        raise _unmerged_error()
    by_path = {record.path: record for record in records}
    directories = {
        parent.as_posix()
        for record in records
        for parent in PurePosixPath(record.path).parents
    }
    problems = []
    for entry in allowlist.entries:
        if entry.path in directories:
            problems.append(
                AllowlistProblem(
                    AllowlistProblemKind.TOO_BROAD,
                    entry.line,
                    "names a directory in the index",
                ),
            )
        elif (record := by_path.get(entry.path)) is None:
            problems.append(
                AllowlistProblem(
                    AllowlistProblemKind.STALE,
                    entry.line,
                    "names no file in the index "
                    "(`git ls-files -- ':(icase)<path>'` finds its exact spelling)",
                ),
            )
        elif detail := _stale_detail(entry, record):
            problems.append(
                AllowlistProblem(AllowlistProblemKind.STALE, entry.line, detail),
            )
    return problems


def _judge(
    entry: StagedEntry,
    path_reason: BlockedPath | None,
    content: bytes | None,
    allowlist: Allowlist,
) -> Finding | AllowlistProblem | None:
    """Judge one staged entry: refuse it, report its content entry stale, or pass."""
    if path_reason is not None and entry.path not in allowlist.paths:
        return Finding(entry.path, path_reason.value)
    if content is None:
        return None
    kind = secret_kind(content)
    line = allowlist.contents.get((entry.path, entry.blob_id))
    if line is None:
        if kind is None:
            return None
        return Finding(entry.path, f"content matches the {kind.value} pattern")
    if kind is not None:
        return None
    return AllowlistProblem(
        AllowlistProblemKind.STALE,
        line,
        "the staged content matches no credential pattern, "
        "so it needs no content entry",
    )


def find_violations(
    merge_commits: Sequence[str] = (),
    allowlist: Allowlist = EMPTY_ALLOWLIST,
) -> Verdict:
    """Judge every staged change in the current repository.

    Args:
        merge_commits: The commits being merged in (`merge_heads()`); a staged
            entry identical to the same path in one of them is not judged.
        allowlist: The resolved `.check-staged-allow`: a `path` entry lets
            that file past the path rules, a `content` entry lets that exact
            staged content past the content patterns.

    Returns:
        Every refused path, in index order, and a STALE problem for each
        content entry whose staged content matches no pattern; both empty when
        the commit is safe.

    Raises:
        GitError: git could not list or read the staged changes.
    """
    entries = staged_entries()
    inherited: set[str] = set()
    for commit in merge_commits:
        inherited |= paths_identical_in(commit, {entry.path for entry in entries})
    entries = [entry for entry in entries if entry.path not in inherited]
    path_reasons = {entry.path: blocked_path_reason(entry.path) for entry in entries}
    exempt_paths = allowlist.paths
    to_read = [
        entry
        for entry in entries
        if (path_reasons[entry.path] is None or entry.path in exempt_paths)
        and entry.mode != GITLINK_MODE
    ]
    contents = dict(
        zip(
            (entry.path for entry in to_read),
            read_blobs([entry.blob_id for entry in to_read]),
            strict=True,
        ),
    )
    findings: list[Finding] = []
    problems: list[AllowlistProblem] = []
    for entry in entries:
        result = _judge(
            entry, path_reasons[entry.path], contents.get(entry.path), allowlist
        )
        if isinstance(result, Finding):
            findings.append(result)
        elif result is not None:
            problems.append(result)
    return Verdict(findings=tuple(findings), problems=tuple(problems))


def _report_problems(problems: Sequence[AllowlistProblem]) -> None:
    """Print each problem as an `ERR_` block, in line order.

    A FILE problem, the only kind without a line, is always reported alone.
    """
    for problem in sorted(problems, key=lambda problem: problem.line or 0):
        location = (
            ALLOWLIST_PATH
            if problem.line is None
            else f"{ALLOWLIST_PATH}:{problem.line}"
        )
        print(f"{problem.kind.value}: {location}: {problem.detail}", file=sys.stderr)
        print(f"Expected: {problem.kind.expected}", file=sys.stderr)
        print(
            f"Next: {problem.kind.next_step.format(line=problem.line)}",
            file=sys.stderr,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Check the index and report every refused path on stderr.

    Args:
        argv: Command-line arguments; the script takes none besides --help.

    Returns:
        An `ExitCode` value. A git failure before the allowlist is judged wins
        (2). Once the allowlist has a FILE, SYNTAX, or TOO_BROAD problem the run
        stops there and exits 3 without calling git again; a STALE problem
        lets judging go on, and still exits 3 over a refusal (1).
    """
    parser = argparse.ArgumentParser(
        description="Refuse staged secret-shaped paths and credential-shaped content.",
    )
    parser.parse_args(argv)
    try:
        merge_commits = merge_heads()
        allowlist, problems = read_allowlist()
        if not problems:
            problems = resolve_allowlist(allowlist)
        if any(problem.kind is not AllowlistProblemKind.STALE for problem in problems):
            # Never judge with a partly valid allowlist: that is what keeps
            # `path *` from exempting anything.
            _report_problems(problems)
            return ExitCode.ALLOWLIST_INVALID
        verdict = find_violations(merge_commits, allowlist)
    except GitError as error:
        print(f"check_staged: {error}", file=sys.stderr)
        return ExitCode.GIT_FAILED
    problems = [*problems, *verdict.problems]
    _report_problems(problems)
    for finding in verdict.findings:
        print(
            f"check_staged: refused {finding.path}: {finding.reason}", file=sys.stderr
        )
    if verdict.findings:
        hint = MERGE_FIX_HINT if merge_commits else FIX_HINT
        print(f"check_staged: {hint}", file=sys.stderr)
    if problems:
        return ExitCode.ALLOWLIST_INVALID
    if verdict.findings:
        return ExitCode.BLOCKED
    return ExitCode.OK


if __name__ == "__main__":
    sys.exit(main())
