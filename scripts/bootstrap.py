"""Turn this template into a new application, once.

Run it from the root of a clean git clone of the template:

    uv run --locked python scripts/bootstrap.py todo-api --author "Jane Doe" \
        --github-user jdoe --github-repository jdoe/todo-api \
        --description "Todo API" --contact-url https://github.com/jdoe

The order is fixed: validate every input and the repository's state, compute
every file's new content in memory, and only then write. A refusal, an invalid
value, or a template file that no longer has the shape this script expects
therefore leaves the tree byte-identical. After the write it records the
template in `.template-origin`, runs `uv lock`, and formats the tree.

The `starting-an-app` skill's `references/bootstrap.md` documents the flags,
the refusals, and everything the run removes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import enum
import json
import keyword
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]

PLACEHOLDER_SLUG = "my-app"
PLACEHOLDER_MODULE = "my_app"
PLACEHOLDER_DISPLAY_NAME = "My App"
PLACEHOLDER_ENV_PREFIX = "MY_APP_"
PLACEHOLDER_REPOSITORY = "your-username/fastapi-react-template"
PLACEHOLDER_AUTHOR = "Your Name"
# The same idea is worded differently per file, so both spellings are replaced.
PLACEHOLDER_DESCRIPTIONS = (
    "A short description of the project.",
    "A short description of what this application does.",
)
# No value may contain one of these tokens, in any case: CI's leftover scan
# looks for them, so a value holding one would read as a placeholder the rename
# missed. They never occur inside ordinary words.
FORBIDDEN_TOKENS = (
    "my-app",
    "my_app",
    "fastapi-react-template",
    "your-username",
    "you@example.com",
)
# No value may equal one of these phrases, in any case. Containing one is fine:
# "Book my appointments" or "Sync my apps" is ordinary prose.
FORBIDDEN_PHRASES = (PLACEHOLDER_DISPLAY_NAME, PLACEHOLDER_AUTHOR)
# Names an app slug may not take, in its hyphenated or its module form: the
# layers' own package names and the placeholders (the issue's settled list);
# the packages the app and its tooling import, which the app's own top-level
# module would shadow; cli and typer for an app that adds a command-line entry
# point back; and every scripts/*.py stem, which `uv run python
# scripts/<stem>.py` puts first on sys.path. Python keywords and stdlib modules
# are checked separately.
RESERVED_NAMES = frozenset(
    {
        "app",
        "src",
        "test",
        "tests",
        "core",
        "api",
        "cli",
        "adapters",
        "settings",
        PLACEHOLDER_SLUG,
        PLACEHOLDER_MODULE,
        "fastapi",
        "typer",
        "pydantic",
        "pydantic_settings",
        "uvicorn",
        "httpx",
        "httpx2",
        "starlette",
        "pytest",
        "ruff",
        "mypy",
        *(path.stem for path in Path(__file__).resolve().parent.glob("*.py")),
    }
)

TEMPLATE_REPOSITORY_URL = "https://github.com/tomada1114/fastapi-react-template"
# The template's first commit. Every clone of the template shares it; GitHub's
# "Use this template" starts a new history without it.
TEMPLATE_ROOT_COMMIT = "d6fdcdbf1020387a6ab74ac02d8efdf38497604c"
ORIGIN_FILE = ".template-origin"
UNKNOWN = "unknown"

SELF = "scripts/bootstrap.py"
# The template's own files: kept, untouched, by --keep-bootstrap; otherwise
# deleted, this script last of all.
KEEPABLE_FILES = (
    "TEMPLATE.md",
    "tests/test_bootstrap.py",
    ".agents/skills/starting-an-app/references/bootstrap.md",
    ".claude/skills/starting-an-app/references/bootstrap.md",
    SELF,
)
# Rewritten by `uv lock` after the rename rather than edited here.
REGENERATED_FILES = frozenset({"uv.lock"})
ENV_EXAMPLE_SUFFIXES = (".example", ".sample", ".template")

FINISHING_COMMANDS = (
    ("uv", "lock"),
    ("uv", "run", "--locked", "ruff", "check", "--fix", "--quiet", "."),
    ("uv", "run", "--locked", "ruff", "format", "--quiet", "."),
)

LICENSE_LINE_PATTERN = re.compile(
    rf"Copyright \(c\) \d{{4}} {re.escape(PLACEHOLDER_AUTHOR)}"
)

# The contact slots: the template's sentence, which points at the repository's
# private vulnerability reporting and issue tracker, and the sentence that
# replaces it when --contact-url is given.
SECURITY_CONTACT_TEMPLATE = f"""If that form is unavailable, [open an issue](https://github.com/{PLACEHOLDER_REPOSITORY}/issues)
asking for a private contact, and leave every detail of the vulnerability out of it.
"""
SECURITY_CONTACT_PERSON = """If that form is unavailable, ask the maintainer for a private contact through
<{contact_url}>, and leave every detail of the vulnerability out of it.
"""
CONDUCT_CONTACT_TEMPLATE = f"""Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported privately through the repository's
[private vulnerability reporting form](https://github.com/{PLACEHOLDER_REPOSITORY}/security/advisories/new),
which only the maintainers can read. A report that needs no privacy can go to
[the issue tracker](https://github.com/{PLACEHOLDER_REPOSITORY}/issues).
"""
CONDUCT_CONTACT_PERSON = """Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported privately to the community leaders through <{contact_url}>.
"""

_SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_GITHUB_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPOSITORY_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_EMAIL_PATTERN = re.compile(r"[^\s@<>()]+@[^\s@<>()]+\.[^\s@<>()]+")
# Characters that would break a Markdown, TOML, JSON, or Python string site.
_UNSAFE_TEXT_PATTERN = re.compile(r'[\x00-\x1f\x7f"\\`<>]')
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
MAX_SLUG_LENGTH = 40
MAX_DISPLAY_NAME_LENGTH = 60
MAX_AUTHOR_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 200


class BootstrapError(Exception):
    """An input, or the repository's state, rules the run out before any write."""


class WriteError(BootstrapError):
    """Writing failed part-way; the tree holds a partial rewrite."""

    def __init__(self, error: OSError, done: list[str]) -> None:
        """Explain what was written before error, and how to undo all of it."""
        steps = "; ".join(done) or "nothing yet"
        super().__init__(
            f"writing failed: {error}. Done before the failure: {steps}. The work "
            "tree was clean before the run, so `git restore --staged --worktree :/ "
            "&& git clean -fd` discards the partial rewrite and restores the "
            "template; then fix the cause and run the bootstrap again."
        )


class _Marker(enum.Enum):
    """A line that opens or closes a template-only block."""

    OPEN = "<!-- template-only -->"
    CLOSE = "<!-- /template-only -->"


_MARKERS = {marker.value: marker for marker in _Marker}


@dataclass(frozen=True, slots=True)
class Identity:
    """The values the new application is named with, as given on the command line.

    Attributes:
        slug: Distribution, console-script, and (with underscores) module name.
        author: Copyright holder and package author; never an email address.
        description: The one-line summary in `backend/pyproject.toml` and README.
        github_user: Owner of the GitHub repository.
        github_repository: `NAME` or `OWNER/NAME`; defaults to the slug.
        display_name: Human-readable name; defaults to the slug.
        contact_url: Public profile URL for the security and conduct contact
            slots; without it they point at the repository itself.
    """

    slug: str
    author: str
    description: str
    github_user: str
    github_repository: str | None = None
    display_name: str | None = None
    contact_url: str | None = None


@dataclass(frozen=True, slots=True)
class Names:
    """Validated values, with every spelling the rename writes derived."""

    slug: str
    module: str
    env_prefix: str
    display_name: str
    repository: str
    author: str
    description: str
    contact_url: str | None


@dataclass(frozen=True, slots=True)
class Plan:
    """Everything the run will change, computed before the first write."""

    writes: dict[str, str]
    deletions: tuple[str, ...]
    origin: str


def _check_text(value: str, label: str, max_length: int) -> str:
    """Reject a value that cannot be written safely into every file it reaches."""
    if not value or value != value.strip() or len(value) > max_length:
        msg = f"invalid {label} {value!r}: 1-{max_length} characters, no surrounding spaces"
        raise BootstrapError(msg)
    if _UNSAFE_TEXT_PATTERN.search(value):
        msg = f'invalid {label} {value!r}: one line without quotes, backslashes, backticks, "<" or ">"'
        raise BootstrapError(msg)
    if _EMAIL_PATTERN.search(value):
        msg = (
            f"invalid {label} {value!r}: an email address is never written into the app"
        )
        raise BootstrapError(msg)
    return value


def _check_slug(slug: str) -> str:
    """Return the module name for a valid, unreserved slug."""
    if len(slug) > MAX_SLUG_LENGTH or not _SLUG_PATTERN.fullmatch(slug):
        msg = (
            f"invalid name {slug!r}: lower-case letters and digits in words joined "
            f"by single hyphens, starting with a letter, at most {MAX_SLUG_LENGTH} characters"
        )
        raise BootstrapError(msg)
    module = slug.replace("-", "_")
    if (
        {slug, module} & RESERVED_NAMES
        or keyword.iskeyword(module)
        or module in sys.stdlib_module_names
    ):
        msg = (
            f"reserved name {slug!r}: it collides with a layer of the app, a "
            "placeholder, a Python keyword, or a standard-library module"
        )
        raise BootstrapError(msg)
    return module


def _check_repository(identity: Identity) -> str:
    """Return the repository as `OWNER/NAME`."""
    owner = identity.github_user
    if not _GITHUB_OWNER_PATTERN.fullmatch(owner):
        msg = f"invalid GitHub user or organization {owner!r}"
        raise BootstrapError(msg)
    given = identity.github_repository or identity.slug
    given_owner, _, name = given.rpartition("/")
    if given_owner and given_owner.lower() != owner.lower():
        msg = f"--github-repository {given!r} names owner {given_owner!r}, but --github-user is {owner!r}"
        raise BootstrapError(msg)
    if (
        not _REPOSITORY_NAME_PATTERN.fullmatch(name)
        or name in {".", ".."}
        or name.endswith(".git")
    ):
        msg = f"invalid GitHub repository name {name!r}"
        raise BootstrapError(msg)
    return f"{owner}/{name}"


def _check_contact_url(url: str | None) -> str | None:
    """Accept only a public https URL: never a mailto: link or embedded credentials."""
    if url is None:
        return None
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or "@" in parts.netloc
        or _CONTROL_PATTERN.search(url)
        or any(character in url for character in ' "<>\\`')
    ):
        msg = f"invalid --contact-url {url!r}: a public https:// profile URL, without credentials"
        raise BootstrapError(msg)
    return url


def resolve_names(identity: Identity) -> Names:
    """Validate the identity and derive every spelling the rename writes.

    Args:
        identity: The values as given on the command line.

    Returns:
        The validated values, with the module name and environment prefix.

    Raises:
        BootstrapError: A value is malformed, reserved, holds an email address,
            or contains a placeholder.
    """
    module = _check_slug(identity.slug)
    display_name = identity.display_name or identity.slug
    names = Names(
        slug=identity.slug,
        module=module,
        env_prefix=f"{module.upper()}_",
        display_name=_check_text(display_name, "display name", MAX_DISPLAY_NAME_LENGTH),
        repository=_check_repository(identity),
        author=_check_text(identity.author, "author", MAX_AUTHOR_LENGTH),
        description=_check_text(
            identity.description, "description", MAX_DESCRIPTION_LENGTH
        ),
        contact_url=_check_contact_url(identity.contact_url),
    )
    for field, value in (
        ("name", names.slug),
        ("display name", names.display_name),
        ("GitHub repository", names.repository),
        ("author", names.author),
        ("description", names.description),
        ("contact URL", names.contact_url or ""),
    ):
        lowered = value.lower()
        if hit := next((t for t in FORBIDDEN_TOKENS if t in lowered), None):
            msg = f"invalid {field} {value!r}: it contains the placeholder {hit!r}"
            raise BootstrapError(msg)
        if any(
            re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", value, re.IGNORECASE)
            for phrase in PLACEHOLDER_DESCRIPTIONS
        ):
            msg = f"invalid {field} {value!r}: it contains a placeholder description"
            raise BootstrapError(msg)
        if lowered in (phrase.lower() for phrase in FORBIDDEN_PHRASES):
            msg = f"invalid {field} {value!r}: it is a placeholder"
            raise BootstrapError(msg)
    return names


def _git(root: Path, *args: str) -> str:
    """Run git in root and return its standard output."""
    try:
        result = subprocess.run(  # noqa: S603 -- a fixed git argv, no shell
            ["git", *args],  # noqa: S607 -- git resolved from PATH, as a shell would
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        msg = f"git is unavailable: {error}"
        raise BootstrapError(msg) from error
    if result.returncode != 0:
        msg = f"`git {' '.join(args)}` failed in {root}: {result.stderr.strip()}"
        raise BootstrapError(msg)
    return result.stdout


def _check_work_tree(root: Path, names: Names) -> None:
    """Refuse anything but the clean root of a template work tree."""
    top_level = Path(_git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    if top_level != root:
        msg = f"run the bootstrap from the root of the git work tree ({top_level}), not {root}"
        raise BootstrapError(msg)
    if (root / ORIGIN_FILE).exists():
        msg = (
            f"already bootstrapped: {ORIGIN_FILE} exists. The bootstrap runs once; "
            "for a clean retry, start again from a fresh clone of the template"
        )
        raise BootstrapError(msg)
    if status := _git(root, "status", "--porcelain", "--untracked-files=all"):
        listed = "\n".join(status.splitlines()[:10])
        msg = f"the working tree has uncommitted changes; commit or stash them first:\n{listed}"
        raise BootstrapError(msg)
    source = root / "backend" / "src" / PLACEHOLDER_MODULE
    if not source.is_dir():
        msg = f"expected the template's package at {source}"
        raise BootstrapError(msg)
    destination = root / "backend" / "src" / names.module
    if destination.exists() or destination.is_symlink():
        msg = f"destination package already exists: {destination}"
        raise BootstrapError(msg)


def _is_protected(relative: str) -> bool:
    """Whether a path may hold credentials rather than placeholders."""
    path = Path(relative)
    name = path.name
    if name == ".env" or (
        name.startswith(".env.") and not name.endswith(ENV_EXAMPLE_SUFFIXES)
    ):
        return True
    return "secrets" in path.parts


def _strip_template_only(text: str, relative: str) -> str:
    """Remove every template-only block, marker lines included.

    A marker is a line holding only the marker, optionally behind `#` so YAML,
    TOML, and shell files can carry one. When a removed block sat between two
    blank lines, one of them goes too.
    """
    kept: list[str] = []
    open_line: int | None = None
    just_closed = False
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        marker = _MARKERS.get(line.strip().removeprefix("#").strip())
        if marker is _Marker.OPEN:
            if open_line is not None:
                msg = f"{relative}:{number}: template-only block opened inside the one at line {open_line}"
                raise BootstrapError(msg)
            open_line = number
        elif marker is _Marker.CLOSE:
            if open_line is None:
                msg = (
                    f"{relative}:{number}: template-only block closed but never opened"
                )
                raise BootstrapError(msg)
            open_line, just_closed = None, True
        elif open_line is None:
            is_doubled_blank = not line.strip() and (not kept or not kept[-1].strip())
            if not (just_closed and is_doubled_blank):
                kept.append(line)
            just_closed = False
    if open_line is not None:
        msg = f"{relative}:{open_line}: template-only block never closed"
        raise BootstrapError(msg)
    stripped = "".join(kept)
    return stripped.rstrip("\n") + "\n" if stripped != text and stripped else stripped


@dataclass(frozen=True, slots=True)
class _Site:
    """Text a template file must hold exactly once, so the rename can edit it."""

    file: str
    text: str

    def replace(self, content: str, new: str) -> str:
        """Return content with the site replaced by new."""
        if content.count(self.text) != 1:
            first_line = self.text.splitlines()[0]
            msg = f"{self.file}: expected exactly one {first_line!r}; the template changed shape"
            raise BootstrapError(msg)
        return content.replace(self.text, new)


def _edit_pyproject(text: str, names: Names, _today: dt.date) -> str:
    """Write the metadata with TOML quoting."""
    text = _Site("backend/pyproject.toml", f'name = "{PLACEHOLDER_AUTHOR}"').replace(
        text, f"name = {json.dumps(names.author, ensure_ascii=False)}"
    )
    description = f'description = "{PLACEHOLDER_DESCRIPTIONS[0]}"'
    return _Site("backend/pyproject.toml", description).replace(
        text, f"description = {json.dumps(names.description, ensure_ascii=False)}"
    )


def _edit_readme(text: str, names: Names, _today: dt.date) -> str:
    """Fail before writing if the README description slot has drifted."""
    return _Site("README.md", PLACEHOLDER_DESCRIPTIONS[1]).replace(
        text, names.description
    )


def _edit_license(text: str, names: Names, today: dt.date) -> str:
    """Write the run's year and the author into the copyright line."""
    if len(LICENSE_LINE_PATTERN.findall(text)) != 1:
        msg = "LICENSE: expected exactly one template copyright line"
        raise BootstrapError(msg)
    return LICENSE_LINE_PATTERN.sub(
        lambda _: f"Copyright (c) {today.year} {names.author}", text
    )


def _edit_security(text: str, names: Names, _today: dt.date) -> str:
    """Name the contact URL in SECURITY.md's fallback route, when one is given."""
    new = SECURITY_CONTACT_TEMPLATE
    if names.contact_url:
        new = SECURITY_CONTACT_PERSON.format(contact_url=names.contact_url)
    return _Site("SECURITY.md", SECURITY_CONTACT_TEMPLATE).replace(text, new)


def _edit_conduct(text: str, names: Names, _today: dt.date) -> str:
    """Name the contact URL as the conduct reporting route, when one is given."""
    new = CONDUCT_CONTACT_TEMPLATE
    if names.contact_url:
        new = CONDUCT_CONTACT_PERSON.format(contact_url=names.contact_url)
    return _Site("CODE_OF_CONDUCT.md", CONDUCT_CONTACT_TEMPLATE).replace(text, new)


FILE_EDITS: dict[str, Callable[[str, Names, dt.date], str]] = {
    "backend/pyproject.toml": _edit_pyproject,
    "README.md": _edit_readme,
    "LICENSE": _edit_license,
    "SECURITY.md": _edit_security,
    "CODE_OF_CONDUCT.md": _edit_conduct,
}


def _replace_placeholders(text: str, names: Names) -> str:
    """Replace every placeholder in one pass, so no new value is rewritten again."""
    replacements = {
        PLACEHOLDER_REPOSITORY: names.repository,
        PLACEHOLDER_AUTHOR: names.author,
        PLACEHOLDER_DISPLAY_NAME: names.display_name,
        PLACEHOLDER_ENV_PREFIX: names.env_prefix,
        PLACEHOLDER_SLUG: names.slug,
        PLACEHOLDER_MODULE: names.module,
    }
    replacements.update(dict.fromkeys(PLACEHOLDER_DESCRIPTIONS, names.description))
    pattern = re.compile(
        "|".join(re.escape(old) for old in sorted(replacements, key=len, reverse=True))
    )
    return pattern.sub(lambda match: replacements[match.group(0)], text)


def _candidate_files(root: Path) -> list[str]:
    """Return the tracked text-file paths the rename may rewrite."""
    untouched = {*KEEPABLE_FILES, *REGENERATED_FILES}
    candidates = []
    for relative in _git(root, "ls-files", "-z").split("\0"):
        path = root / relative
        if (
            relative
            and relative not in untouched
            and path.is_file()
            and not path.is_symlink()
            and not _is_protected(relative)
        ):
            candidates.append(relative)
    return candidates


def _plan_writes(root: Path, names: Names, today: dt.date) -> dict[str, str]:
    """Compute the new content of every file the rename changes."""
    writes: dict[str, str] = {}
    edited: set[str] = set()
    for relative in _candidate_files(root):
        try:
            text = (root / relative).read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue  # a binary file holds no placeholder
        new_text = _strip_template_only(text, relative)
        if edit := FILE_EDITS.get(relative):
            new_text = edit(new_text, names, today)
            edited.add(relative)
        new_text = _replace_placeholders(new_text, names)
        if new_text != text:
            writes[relative] = new_text
    if missing := sorted(FILE_EDITS.keys() - edited):
        msg = f"the template is missing files the rename edits: {', '.join(missing)}"
        raise BootstrapError(msg)
    return writes


def _origin_record(root: Path) -> str:
    """Describe the template commit this app was cut from, or how to find it."""
    is_shallow = _git(root, "rev-parse", "--is-shallow-repository").strip() == "true"
    roots = set(_git(root, "rev-list", "--max-parents=0", "HEAD").split())
    is_template_history = not is_shallow and TEMPLATE_ROOT_COMMIT in roots
    commit = _git(root, "rev-parse", "HEAD").strip() if is_template_history else UNKNOWN
    tree = _git(root, "rev-parse", "HEAD^{tree}").strip()
    return (
        "# Written once by the template's bootstrap. Keep it committed: the\n"
        "# bootstrap refuses a second run while it exists, and\n"
        "# tests/test_product_section.py reads it to know this is an app, whose\n"
        "# AGENTS.md Product section must be filled in.\n"
        "# commit is the template commit this app was cut from, or\n"
        '# "unknown" when this history does not start at the template\'s first commit\n'
        '# (GitHub\'s "Use this template" starts a new one). Then find it by tree:\n'
        "#   git log --format='%H %T' <template remote>/main | grep <tree>\n"
        f"template: {TEMPLATE_REPOSITORY_URL}\n"
        f"commit: {commit}\n"
        f"tree: {tree}\n"
    )


def plan(root: Path, names: Names, *, keep_bootstrap: bool = False) -> Plan:
    """Check the repository and compute every change, writing nothing.

    Args:
        root: The template checkout's resolved git root.
        names: Validated values from `resolve_names`.
        keep_bootstrap: Keep the template's own files instead of deleting them.

    Returns:
        Every write, deletion, and the `.template-origin` record.

    Raises:
        BootstrapError: The tree is not a clean, never-bootstrapped template
            root, or a file the rename edits no longer has the expected shape.
    """
    _check_work_tree(root, names)
    today = dt.datetime.now(tz=dt.UTC).date()
    return Plan(
        writes=_plan_writes(root, names, today),
        deletions=() if keep_bootstrap else KEEPABLE_FILES,
        origin=_origin_record(root),
    )


def _moved(relative: str, module: str) -> str:
    """Return where a template path lives once the package directory is renamed."""
    old_prefix = f"backend/src/{PLACEHOLDER_MODULE}/"
    if relative.startswith(old_prefix):
        return f"backend/src/{module}/{relative.removeprefix(old_prefix)}"
    return relative


def _apply(root: Path, names: Names, change: Plan) -> None:
    """Write a computed plan, most failure-prone step first, this script last.

    Raises:
        WriteError: A write failed; the message names the steps already done
            and how to restore the template.
    """
    done: list[str] = []
    try:
        package_parent = root / "backend" / "src"
        (package_parent / PLACEHOLDER_MODULE).rename(package_parent / names.module)
        done.append(
            f"renamed backend/src/{PLACEHOLDER_MODULE} to backend/src/{names.module}"
        )
        for relative, text in change.writes.items():
            (root / _moved(relative, names.module)).write_bytes(text.encode("utf-8"))
        done.append(f"rewrote {len(change.writes)} files")
        (root / ORIGIN_FILE).write_text(change.origin, encoding="utf-8")
        done.append(f"wrote {ORIGIN_FILE}")
        for relative in change.deletions:
            (root / relative).unlink(missing_ok=True)
        done.append("deleted the template's own files")
    except OSError as error:
        raise WriteError(error, done) from error


def bootstrap(root: Path, identity: Identity, *, keep_bootstrap: bool = False) -> Names:
    """Validate, plan, then rewrite the template at root into the new app.

    Args:
        root: The template checkout's git root.
        identity: The values the app is named with.
        keep_bootstrap: Keep the template's own files instead of deleting them.

    Returns:
        The validated names the app now carries.

    Raises:
        BootstrapError: Before any file is written, when an input or the
            repository's state rules the run out.
        WriteError: When writing failed part-way; its message says what was
            done and how to restore the template.
    """
    root = root.resolve()
    names = resolve_names(identity)
    _apply(root, names, plan(root, names, keep_bootstrap=keep_bootstrap))
    return names


def finish(root: Path) -> bool:
    """Regenerate uv.lock and format the renamed tree.

    The lock still names the template's package until `uv lock` runs, and a
    longer module name can push imports past the line length, so both steps
    belong to the rename. They run after the write, so a failure here cannot be
    rolled back; it is reported with the command to run by hand.

    Returns:
        Whether every command succeeded.
    """
    for command in FINISHING_COMMANDS:
        shown = " ".join(command)
        try:
            result = subprocess.run(command, cwd=root, check=False)  # noqa: S603 -- fixed argv, no shell
        except OSError as error:
            print(f"error: could not run `{shown}`: {error}", file=sys.stderr)
            return False
        if result.returncode != 0:
            print(
                f"error: `{shown}` failed (exit {result.returncode}). The rename is "
                "written; run that command and the ones after it by hand.",
                file=sys.stderr,
            )
            return False
    return True


def _check_invoked_from(repo_root: Path) -> None:
    """Refuse a run from inside another checkout than the one holding this script.

    The script rewrites its own checkout; run from a different repository (a
    template checkout next to the new app, say), the rename would land
    somewhere other than where the user is looking.
    """
    top_level = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    if top_level.resolve() != repo_root.resolve():
        msg = (
            f"run the bootstrap from inside {repo_root}, the checkout it belongs "
            f"to; the current directory is in {top_level}"
        )
        raise BootstrapError(msg)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0], allow_abbrev=False
    )
    parser.add_argument("name", help="the app's slug, e.g. todo-api (module: todo_api)")
    parser.add_argument("--author", required=True, help="author and copyright holder")
    parser.add_argument("--description", required=True, help="one line about the app")
    parser.add_argument("--github-user", required=True, help="the repository's owner")
    parser.add_argument(
        "--github-repository",
        default=None,
        help="NAME or OWNER/NAME (default: the slug, under --github-user)",
    )
    parser.add_argument("--display-name", default=None, help="default: the slug")
    parser.add_argument(
        "--contact-url",
        default=None,
        help="public profile URL for SECURITY.md and CODE_OF_CONDUCT.md "
        "(default: the repository's private reporting form and issue tracker)",
    )
    parser.add_argument(
        "--keep-bootstrap",
        action="store_true",
        help="keep TEMPLATE.md, this script, its test, and its skill reference, "
        "untouched, for debugging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Bootstrap the template this script belongs to, then finish it with uv."""
    args = _parse_args(argv)
    identity = Identity(
        slug=args.name,
        author=args.author,
        description=args.description,
        github_user=args.github_user,
        github_repository=args.github_repository,
        display_name=args.display_name,
        contact_url=args.contact_url,
    )
    try:
        _check_invoked_from(REPO_ROOT)
        names = bootstrap(REPO_ROOT, identity, keep_bootstrap=args.keep_bootstrap)
    except BootstrapError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Renamed the template to {names.slug} (package backend/src/{names.module}).")
    if not finish(REPO_ROOT):
        return 1
    print(
        "Next: write AGENTS.md's Product section, then commit it with the rewrite "
        "as one `chore: bootstrap` commit, per the starting-an-app skill."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
