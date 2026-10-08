"""Tests for scripts/bootstrap.py, run against git clones of the working tree."""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
# A line the bootstrap treats as a template-only marker.
MARKER_LINE = re.compile(r"^\s*(?:#\s*)?<!-- /?template-only -->\s*$", re.MULTILINE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# The issue's sample values.
SAMPLE = {
    "slug": "todo-api",
    "author": "Jane Doe",
    "description": "Todo API",
    "github_user": "jdoe",
    "github_repository": "jdoe/todo-api",
    "contact_url": "https://github.com/jdoe",
}
SAMPLE_ARGV = [
    "todo-api",
    "--author",
    "Jane Doe",
    "--github-user",
    "jdoe",
    "--github-repository",
    "jdoe/todo-api",
    "--description",
    "Todo API",
    "--contact-url",
    "https://github.com/jdoe",
]
KEEPABLE = ("TEMPLATE.md", "scripts/bootstrap.py", "tests/test_bootstrap.py")
SKILL_REFERENCE = "skills/starting-an-app/references/bootstrap.md"
# Isolates every git call (the fixtures' and the script's) from the
# developer's own configuration: hooks, signing, default branch, identity.
# Auto maintenance is off too: a commit otherwise leaves a detached
# `git maintenance run --auto` behind, which can repack the session-scoped
# template's objects while a later local clone is copying them (#175).
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "maintenance.auto",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "gc.auto",
    "GIT_CONFIG_VALUE_1": "0",
    "GIT_AUTHOR_NAME": "Template Test",
    "GIT_AUTHOR_EMAIL": "template-test@localhost",
    "GIT_COMMITTER_NAME": "Template Test",
    "GIT_COMMITTER_EMAIL": "template-test@localhost",
}


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 -- a fixed git argv, no shell
        ["git", *args],  # noqa: S607 -- git resolved from PATH, as a shell would
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    )
    return result.stdout


def _load_bootstrap_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "bootstrap", REPO_ROOT / "scripts" / "bootstrap.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bootstrap = _load_bootstrap_module()
# Both test and CI smoke scans are checked against the bootstrap vocabulary.
LEFTOVER_TOKENS = re.compile(
    "|".join(re.escape(value) for value in bootstrap.FORBIDDEN_TOKENS), re.IGNORECASE
)
LEFTOVER_PHRASES = re.compile(
    r"(?<!\w)(?:"
    + "|".join(
        re.escape(value)
        for value in (*bootstrap.FORBIDDEN_PHRASES, *bootstrap.PLACEHOLDER_DESCRIPTIONS)
    )
    + r")(?!\w)",
    re.IGNORECASE,
)


@pytest.fixture(scope="session")
def template_repository(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A one-commit git repository holding the working tree's files.

    Tracked and new untracked files are both copied, so a change to the
    template is tested before it is committed.
    """
    root = tmp_path_factory.mktemp("template")
    listed = _git(
        REPO_ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
    )
    for relative in filter(None, listed.split("\0")):
        source = REPO_ROOT / relative
        if source.is_file() and not source.is_symlink():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "add", "--all")
    _git(root, "commit", "--quiet", "--message", "template")
    return root


@pytest.fixture
def clone(
    template_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """A fresh clone of the template; REPO_ROOT points at it for main()."""
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    root = tmp_path / "app"
    _git(tmp_path, "clone", "--quiet", str(template_repository), str(root))
    monkeypatch.setattr(bootstrap, "REPO_ROOT", root)
    monkeypatch.chdir(root)
    return root


@pytest.fixture(scope="session")
def sample_app(
    template_repository: Path, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """One clone bootstrapped with the issue's sample values, for read-only tests."""
    root = tmp_path_factory.mktemp("sample") / "app"
    with pytest.MonkeyPatch.context() as patch:
        for name, value in GIT_ENV.items():
            patch.setenv(name, value)
        _git(root.parent, "clone", "--quiet", str(template_repository), str(root))
        bootstrap.bootstrap(root, bootstrap.Identity(**SAMPLE))
    return root


@pytest.fixture
def fake_uv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a `uv` on PATH that logs its arguments; returns the log file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "uv.log"
    script = bin_dir / "uv"
    script.write_text(
        f'#!/bin/sh\necho "$(pwd -P) $*" >> "{log}"\nexit "${{FAKE_UV_EXIT:-0}}"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def _run(root: Path, **overrides: str | None) -> None:
    bootstrap.bootstrap(root, bootstrap.Identity(**{**SAMPLE, **overrides}))


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def _text_files(root: Path) -> dict[str, str]:
    texts = {}
    for relative, data in _snapshot(root).items():
        try:
            texts[relative] = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return texts


# --- REQ-001: every placeholder is replaced --------------------------------


def deleted_template_references(texts: dict[str, str]) -> list[str]:
    allowed_lines: dict[str, tuple[str, ...]] = {
        ".agents/skills/starting-an-app/SKILL.md": (
            "also covers scripts/bootstrap.py, .template-origin, and its CI smoke job.",
            "2. **Rename.** `scripts/bootstrap.py` renames the template into the app, writes",
        ),
        ".claude/skills/starting-an-app/SKILL.md": (
            "also covers scripts/bootstrap.py, .template-origin, and its CI smoke job.",
            "2. **Rename.** `scripts/bootstrap.py` renames the template into the app, writes",
        ),
    }
    # Duration keys are historical timing metadata, and harness fixtures exercise
    # optional template documents even when those documents are absent.
    allowed_lines[".test_durations"] = ('"tests/test_bootstrap.py::',)
    allowed_lines["tests/harness/test_just_recipes.py"] = (
        'pytest.param("TEMPLATE.md", "Run `just docs`.',
    )
    patterns = {
        deleted: re.compile(rf"(?<![\w.-]){re.escape(Path(deleted).name)}(?![\w.-])")
        for deleted in bootstrap.KEEPABLE_FILES
    }
    return [
        f"{relative}:{number}: {deleted}"
        for relative, text in texts.items()
        for number, line in enumerate(text.splitlines(), 1)
        for deleted in bootstrap.KEEPABLE_FILES
        if patterns[deleted].search(line)
        and not any(allowed in line for allowed in allowed_lines.get(relative, ()))
    ]


@pytest.mark.parametrize(
    ("reference", "deleted"),
    [
        pytest.param("bootstrap.py", "scripts/bootstrap.py", id="basename"),
        pytest.param("./scripts/bootstrap.py", "scripts/bootstrap.py", id="relative"),
        pytest.param(
            "../tests/test_bootstrap.py", "tests/test_bootstrap.py", id="parent"
        ),
    ],
)
def test_deleted_template_reference_variants_are_detected(reference, deleted):
    assert deleted_template_references({"docs/guide.md": reference}) == [
        f"docs/guide.md:1: {deleted}"
    ]


def test_bootstrap_leaves_no_reference_to_a_deleted_template_file(sample_app):
    assert deleted_template_references(_text_files(sample_app)) == []


def test_bootstrap_sample_values_leave_no_placeholder_anywhere(sample_app):
    hits = [
        f"{relative}: {match.group(0)}"
        for relative, text in _text_files(sample_app).items()
        if relative not in {"uv.lock", bootstrap.ORIGIN_FILE}
        for pattern in (LEFTOVER_TOKENS, LEFTOVER_PHRASES)
        for match in pattern.finditer(text)
    ]
    assert hits == []


def test_bootstrap_sample_values_rename_package_and_env_prefix(sample_app):
    assert not (sample_app / "src" / "my_app").exists()
    settings = (sample_app / "src" / "todo_api" / "settings.py").read_text(
        encoding="utf-8"
    )
    assert 'ENV_PREFIX = "TODO_API_"' in settings
    pyproject = (sample_app / "pyproject.toml").read_text(encoding="utf-8")
    project = tomllib.loads(pyproject)
    assert project["project"]["name"] == "todo-api"
    assert project["project"]["scripts"] == {"todo-api": "todo_api.cli.main:app"}
    assert (
        project["project"]["urls"]["Issues"]
        == "https://github.com/jdoe/todo-api/issues"
    )
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/todo_api"
    ]


def test_bootstrap_display_name_reaches_its_sites(clone):
    _run(clone, display_name="Todo Service")

    assert (
        (clone / "README.md").read_text(encoding="utf-8").startswith("# Todo Service\n")
    )
    app = (clone / "src/todo_api/api/app.py").read_text(encoding="utf-8")
    assert 'APP_TITLE = "Todo Service"' in app
    devcontainer = (clone / ".devcontainer/devcontainer.json").read_text(
        encoding="utf-8"
    )
    assert '"name": "Todo Service"' in devcontainer


def test_bootstrap_without_display_name_uses_the_slug(sample_app):
    assert (
        (sample_app / "README.md")
        .read_text(encoding="utf-8")
        .startswith("# todo-api\n")
    )


def test_bootstrap_repository_name_alone_takes_the_github_user_as_owner(clone):
    _run(clone, github_repository="todo-service")

    readme = (clone / "README.md").read_text(encoding="utf-8")
    assert "github.com/jdoe/todo-service/actions" in readme


def test_bootstrap_quoted_metadata_stays_valid_toml(clone):
    _run(clone, author="Jane O'Doe", description="Todo API — for teams")

    project = tomllib.loads((clone / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["authors"] == [{"name": "Jane O'Doe"}]
    assert project["project"]["description"] == "Todo API — for teams"


def test_bootstrap_writes_the_year_and_author_into_the_license(sample_app):
    year = dt.datetime.now(tz=dt.UTC).year
    license_text = (sample_app / "LICENSE").read_text(encoding="utf-8")
    assert f"Copyright (c) {year} Jane Doe\n" in license_text


def test_bootstrap_keeps_the_relative_exclude_newer_window(sample_app):
    pyproject = (sample_app / "pyproject.toml").read_text(encoding="utf-8")
    assert tomllib.loads(pyproject)["tool"]["uv"]["exclude-newer"] == "14 days"


# --- REQ-002: no email address ---------------------------------------------


def test_main_rejects_the_email_flag_without_writing(clone, capsys):
    before = _snapshot(clone)

    with pytest.raises(SystemExit) as raised:
        bootstrap.main([*SAMPLE_ARGV, "--email", "jane@example.com"])

    assert raised.value.code == 2
    assert "unrecognized arguments: --email" in capsys.readouterr().err
    assert _snapshot(clone) == before


def test_bootstrap_writes_no_email_address(sample_app):
    texts = _text_files(sample_app)
    metadata = (
        "pyproject.toml",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        bootstrap.ORIGIN_FILE,
    )
    found = {path: EMAIL.findall(texts[path]) for path in metadata}
    assert found == {path: [] for path in metadata}


@pytest.mark.parametrize("field", ["author", "description", "display_name"], ids=str)
def test_resolve_names_rejects_an_email_shaped_value(field):
    identity = bootstrap.Identity(**{**SAMPLE, field: "Jane jane@example.com"})

    with pytest.raises(
        bootstrap.BootstrapError, match=r"email address is never written"
    ):
        bootstrap.resolve_names(identity)


# --- REQ-003: the contact slots --------------------------------------------


def test_bootstrap_contact_url_fills_both_contact_slots(sample_app):
    security = (sample_app / "SECURITY.md").read_text(encoding="utf-8")
    conduct = (sample_app / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
    assert "private contact through\n<https://github.com/jdoe>" in security
    assert "community leaders through <https://github.com/jdoe>." in conduct
    assert "jdoe/todo-api/security/advisories/new" in security


def test_bootstrap_without_contact_url_points_at_the_repository(clone):
    _run(clone, contact_url=None)

    security = (clone / "SECURITY.md").read_text(encoding="utf-8")
    conduct = (clone / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
    assert "[open an issue](https://github.com/jdoe/todo-api/issues)" in security
    assert "(https://github.com/jdoe/todo-api/security/advisories/new)" in conduct
    assert "https://github.com/jdoe>" not in security + conduct


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://example.com/jdoe", id="not-https"),
        pytest.param("mailto:jane@example.com", id="mailto"),
        pytest.param("https://jane:pw@example.com", id="credentials"),
        pytest.param("https://", id="no-host"),
        pytest.param("https://example.com/a b", id="space"),
    ],
)
def test_resolve_names_rejects_an_unusable_contact_url(url):
    identity = bootstrap.Identity(**{**SAMPLE, "contact_url": url})

    with pytest.raises(bootstrap.BootstrapError, match=r"invalid --contact-url"):
        bootstrap.resolve_names(identity)


# --- REQ-004: validate and compute everything before writing ---------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param({"slug": "Todo"}, r"invalid name", id="upper-case-slug"),
        pytest.param({"slug": "todo--api"}, r"invalid name", id="double-hyphen"),
        pytest.param({"slug": "a" * 41}, r"invalid name", id="too-long"),
        pytest.param({"author": ""}, r"invalid author", id="empty-author"),
        pytest.param(
            {"description": "first\nsecond"}, r"invalid description", id="multiline"
        ),
        pytest.param({"author": 'Jane "J" Doe'}, r"invalid author", id="quote"),
        pytest.param({"github_user": "-jdoe"}, r"invalid GitHub user", id="user"),
        pytest.param(
            {"github_repository": "someone/todo-api"},
            r"names owner 'someone'",
            id="owner-mismatch",
        ),
        pytest.param(
            {"github_repository": "jdoe/todo.git"},
            r"invalid GitHub repository",
            id="dot-git",
        ),
        pytest.param(
            {"description": "Like uv-template"}, r"placeholder 'uv-template'", id="ph"
        ),
        pytest.param(
            {"author": "you@example.com"}, r"email address", id="placeholder-email"
        ),
        pytest.param(
            {"display_name": "MY APP"}, r"is a placeholder", id="my-app-phrase"
        ),
        pytest.param(
            {"author": "your name"}, r"is a placeholder", id="your-name-phrase"
        ),
    ],
)
def test_resolve_names_rejects_invalid_input(overrides, message):
    identity = bootstrap.Identity(**{**SAMPLE, **overrides})

    with pytest.raises(bootstrap.BootstrapError, match=message):
        bootstrap.resolve_names(identity)


@pytest.mark.parametrize(
    "argv_tail",
    [
        pytest.param(["--github-repository", "someone/todo-api"], id="owner-mismatch"),
        pytest.param(["--contact-url", "mailto:jane@example.com"], id="mailto"),
    ],
)
def test_main_invalid_input_leaves_the_tree_byte_identical(clone, capsys, argv_tail):
    before = _snapshot(clone)

    assert bootstrap.main([*SAMPLE_ARGV, *argv_tail]) == 1

    assert capsys.readouterr().err.startswith("error: ")
    assert _snapshot(clone) == before


@pytest.mark.parametrize(
    ("relative", "old", "new", "message"),
    [
        pytest.param(
            "README.md",
            "A short description of what this application does.",
            "An unrecognized application description.",
            r"README\.md: expected exactly one",
            id="readme-description-drifted",
        ),
        pytest.param(
            "SECURITY.md",
            "If that form is unavailable",
            "If the form is unavailable",
            r"SECURITY\.md: expected exactly one",
            id="contact-slot-drifted",
        ),
        pytest.param(
            "SECURITY.md",
            "# Security Policy\n",
            "# Security Policy\n\n<!-- template-only -->\n",
            r"SECURITY\.md:3: template-only block never closed",
            id="unclosed-block",
        ),
        pytest.param(
            "CONTRIBUTING.md",
            "\n",
            "\n<!-- /template-only -->\n",
            r"CONTRIBUTING\.md:2: template-only block closed but never opened",
            id="stray-close",
        ),
    ],
)
def test_bootstrap_drifted_template_site_writes_nothing(
    clone, relative, old, new, message
):
    path = clone / relative
    path.write_text(
        path.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8"
    )
    _git(clone, "commit", "--quiet", "--all", "--message", "drift")
    before = _snapshot(clone)

    with pytest.raises(bootstrap.BootstrapError, match=message):
        _run(clone)

    assert _snapshot(clone) == before


# --- REQ-005: dirty tree, reserved names, a second run ---------------------


@pytest.mark.parametrize(
    "make_dirty",
    [
        pytest.param(
            lambda root: (root / "README.md").write_text("changed\n", encoding="utf-8"),
            id="modified",
        ),
        pytest.param(
            lambda root: (root / "notes.txt").write_text("new\n", encoding="utf-8"),
            id="untracked",
        ),
    ],
)
def test_bootstrap_dirty_tree_is_refused_and_left_as_is(clone, make_dirty):
    make_dirty(clone)
    before = _snapshot(clone)

    with pytest.raises(bootstrap.BootstrapError, match=r"uncommitted changes"):
        _run(clone)

    assert _snapshot(clone) == before


def test_main_dirty_tree_exits_one_with_an_error_line(clone, capsys):
    (clone / "README.md").write_text("changed\n", encoding="utf-8")

    assert bootstrap.main(SAMPLE_ARGV) == 1
    assert capsys.readouterr().err.startswith("error: the working tree has uncommitted")


@pytest.mark.parametrize(
    "slug",
    [
        "app",
        "src",
        "test",
        "tests",
        "core",
        "api",
        "cli",
        "adapters",
        "settings",
        "my-app",
        "class",
        "json",
        "email",
        "pydoc-data",  # its module name, pydoc_data, is a stdlib package
        "fastapi",
        "pydantic-settings",
        "starlette",
        "httpx2",
        "mypy",
        "sync-labels",  # a scripts/*.py stem
        "bootstrap",
    ],
)
def test_resolve_names_refuses_a_reserved_name(slug):
    identity = bootstrap.Identity(**{**SAMPLE, "slug": slug, "github_repository": None})

    with pytest.raises(bootstrap.BootstrapError, match=r"reserved name"):
        bootstrap.resolve_names(identity)


def test_main_reserved_name_leaves_the_tree_byte_identical(clone, capsys):
    before = _snapshot(clone)

    assert bootstrap.main(["core", *SAMPLE_ARGV[1:5], *SAMPLE_ARGV[7:]]) == 1

    assert "reserved name 'core'" in capsys.readouterr().err
    assert _snapshot(clone) == before


def test_bootstrap_second_run_is_refused(clone):
    bootstrap.bootstrap(clone, bootstrap.Identity(**SAMPLE), keep_bootstrap=True)
    _git(clone, "add", "--all")
    _git(clone, "commit", "--quiet", "--message", "bootstrap")
    before = _snapshot(clone)

    with pytest.raises(bootstrap.BootstrapError, match=r"already bootstrapped"):
        _run(clone, slug="other-app", github_repository=None)

    assert _snapshot(clone) == before


def test_bootstrap_outside_the_git_root_is_refused(clone):
    with pytest.raises(
        bootstrap.BootstrapError, match=r"from the root of the git work tree"
    ):
        _run(clone / "src")


def test_bootstrap_outside_any_git_repository_is_refused(tmp_path):
    with pytest.raises(
        bootstrap.BootstrapError, match=r"git rev-parse --show-toplevel"
    ):
        _run(tmp_path)


def test_bootstrap_existing_destination_package_is_refused(clone):
    (clone / "src" / "todo_api").mkdir()
    (clone / "src" / "todo_api" / "__init__.py").write_text("", encoding="utf-8")
    _git(clone, "add", "--all")
    _git(clone, "commit", "--quiet", "--message", "collide")

    with pytest.raises(bootstrap.BootstrapError, match=r"already exists"):
        _run(clone)


# --- REQ-006: what a successful run removes and records --------------------


def test_bootstrap_removes_every_template_only_block_and_the_smoke_job(sample_app):
    texts = _text_files(sample_app)
    markers = [path for path, text in texts.items() if MARKER_LINE.search(text)]
    assert markers == []
    ci = texts[".github/workflows/ci.yml"]
    assert "Template Bootstrap Smoke" not in ci
    assert "name: Workflow Security Lint" in ci
    assert ci.endswith(
        "run: uv run --locked pre-commit run zizmor --all-files --verbose\n"
    )
    assert "This is the" not in texts["README.md"]
    assert "\n\n\n" not in texts["README.md"]


def test_bootstrap_deletes_template_only_files_and_keeps_the_mirror_in_sync(sample_app):
    for relative in (
        *KEEPABLE,
        f".agents/{SKILL_REFERENCE}",
        f".claude/{SKILL_REFERENCE}",
    ):
        assert not (sample_app / relative).exists(), relative
    agents = _snapshot(sample_app / ".agents" / "skills")
    assert agents == _snapshot(sample_app / ".claude" / "skills")
    assert "starting-an-app/references/private-repository.md" in agents


def test_bootstrap_keep_bootstrap_keeps_its_files_untouched(clone):
    before = _snapshot(clone)

    bootstrap.bootstrap(clone, bootstrap.Identity(**SAMPLE), keep_bootstrap=True)

    after = _snapshot(clone)
    kept = (*KEEPABLE, f".agents/{SKILL_REFERENCE}", f".claude/{SKILL_REFERENCE}")
    for relative in kept:
        assert after[relative] == before[relative], relative


def test_bootstrap_new_history_records_an_unknown_commit_and_the_tree(
    sample_app, template_repository
):
    tree = _git(template_repository, "rev-parse", "HEAD^{tree}").strip()

    origin = (sample_app / bootstrap.ORIGIN_FILE).read_text(encoding="utf-8")
    assert f"template: {bootstrap.TEMPLATE_REPOSITORY_URL}\n" in origin
    assert "commit: unknown\n" in origin
    assert f"tree: {tree}\n" in origin


def test_bootstrap_template_history_records_the_commit(clone, monkeypatch):
    head = _git(clone, "rev-parse", "HEAD").strip()
    monkeypatch.setattr(bootstrap, "TEMPLATE_ROOT_COMMIT", head)

    _run(clone)

    origin = (clone / bootstrap.ORIGIN_FILE).read_text(encoding="utf-8")
    assert f"commit: {head}\n" in origin


def test_main_runs_uv_lock_then_formats_in_the_app(clone, fake_uv, capsys):
    assert bootstrap.main(SAMPLE_ARGV) == 0

    root = clone.resolve()
    calls = fake_uv.read_text(encoding="utf-8").splitlines()
    assert calls == [
        f"{root} lock",
        f"{root} run --locked ruff check --fix --quiet .",
        f"{root} run --locked ruff format --quiet .",
    ]
    assert "Next: write AGENTS.md's Product section" in capsys.readouterr().out


def test_main_failed_uv_lock_exits_one_after_writing(
    clone, fake_uv, monkeypatch, capsys
):
    monkeypatch.setenv("FAKE_UV_EXIT", "1")

    assert bootstrap.main(SAMPLE_ARGV) == 1

    assert len(fake_uv.read_text(encoding="utf-8").splitlines()) == 1
    assert "`uv lock` failed (exit 1)" in capsys.readouterr().err
    assert (clone / bootstrap.ORIGIN_FILE).is_file()


def test_finish_missing_command_reports_and_returns_false(clone, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "FINISHING_COMMANDS", (("uv-is-not-here",),))

    assert bootstrap.finish(clone) is False
    assert "could not run `uv-is-not-here`" in capsys.readouterr().err


# --- review round: prose, invocation, failed writes, files left alone ------


@pytest.mark.parametrize(
    "description",
    ["Book my appointments", "Sync my apps", "Store your names and dates"],
)
def test_resolve_names_accepts_prose_around_a_placeholder_phrase(description):
    identity = bootstrap.Identity(**{**SAMPLE, "description": description})

    assert bootstrap.resolve_names(identity).description == description


def test_main_from_another_checkout_is_refused_without_writing(
    clone, template_repository, monkeypatch, capsys
):
    before = _snapshot(clone)
    monkeypatch.chdir(template_repository)

    assert bootstrap.main(SAMPLE_ARGV) == 1

    assert "run the bootstrap from inside" in capsys.readouterr().err
    assert _snapshot(clone) == before


def _fail_after(calls: int, original: Callable[..., object]) -> Callable[..., object]:
    """Wrap a Path method so every call after the first ``calls`` raises OSError."""
    count = 0

    def method(self: Path, *args: object, **kwargs: object) -> object:
        nonlocal count
        count += 1
        if count > calls:
            msg = "disk full"
            raise OSError(msg)
        return original(self, *args, **kwargs)

    return method


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(("rename", 0, "nothing yet"), id="rename-fails"),
        pytest.param(
            ("write_bytes", 5, "renamed src/my_app to src/todo_api"), id="write-fails"
        ),
    ],
)
def test_main_failed_write_names_progress_and_recovery_restores_template(
    clone, monkeypatch, capsys, failure
):
    method, calls, done = failure
    before = _snapshot(clone)
    monkeypatch.setattr(Path, method, _fail_after(calls, getattr(Path, method)))

    assert bootstrap.main(SAMPLE_ARGV) == 1

    monkeypatch.undo()
    error = capsys.readouterr().err
    assert error.startswith("error: writing failed: disk full.")
    assert f"Done before the failure: {done}" in error
    assert "git restore --staged --worktree :/ && git clean -fd" in error
    _git(clone, "restore", "--staged", "--worktree", ":/")
    _git(clone, "clean", "-fd")
    assert _snapshot(clone) == before


def test_bootstrap_leaves_secret_binary_and_symlinked_files_alone(clone, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("my-app\n", encoding="utf-8")
    untouched = {
        ".env.local": b"my-app\n",
        "secrets/token.txt": b"my-app\n",
        "data.bin": b"\xff\xfe my-app\n",
    }
    for relative, data in untouched.items():
        (clone / relative).parent.mkdir(parents=True, exist_ok=True)
        (clone / relative).write_bytes(data)
    (clone / "docs" / "outside.md").symlink_to(outside)
    _git(clone, "add", "--all", "--force", *untouched, "docs/outside.md")
    _git(clone, "commit", "--quiet", "--message", "edge cases")

    _run(clone)

    for relative, data in untouched.items():
        assert (clone / relative).read_bytes() == data, relative
    assert (clone / "docs" / "outside.md").is_symlink()
    assert outside.read_text(encoding="utf-8") == "my-app\n"


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        pytest.param("maintenance.auto", "false", id="maintenance"),
        pytest.param("gc.auto", "0", id="gc"),
    ],
)
def test_git_env_disables_background_maintenance(
    tmp_path: Path, key: str, expected: str
) -> None:
    _git(tmp_path, "init", "--quiet")

    assert _git(tmp_path, "config", "--get", key).strip() == expected


def test_bootstrap_readme_description_is_the_supplied_value(sample_app):
    text = (sample_app / "README.md").read_text(encoding="utf-8")
    assert "Todo API" in text
    assert bootstrap.PLACEHOLDER_DESCRIPTIONS[1] not in text


def assert_smoke_contract(workflow: str) -> None:
    smoke = workflow.split("- name: Assert no placeholder survived", 1)[1].split(
        "- name:", 1
    )[0]
    patterns = re.findall(r"git grep[^\n]+ -E '([^']+)'", smoke)
    assert patterns == [
        "|".join(re.escape(value) for value in bootstrap.FORBIDDEN_TOKENS),
        "|".join(
            re.escape(value)
            for value in (
                *bootstrap.FORBIDDEN_PHRASES,
                *bootstrap.PLACEHOLDER_DESCRIPTIONS,
            )
        ),
    ], "smoke placeholder patterns drifted"
    deletion_loop = re.search(r"for path in (.*?); do", smoke, re.DOTALL)
    assert deletion_loop is not None
    paths = deletion_loop.group(1).replace("\\\n", " ").split()
    assert set(paths) == {*bootstrap.KEEPABLE_FILES, "src/my_app"}, (
        "smoke deletion list drifted"
    )


def test_bootstrap_smoke_contract_matches_script_constants():
    assert_smoke_contract(
        (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    "old",
    [
        pytest.param("you@example", id="token"),
        pytest.param("TEMPLATE.md scripts/bootstrap.py", id="deleted-file"),
    ],
)
def test_bootstrap_smoke_contract_drift_is_rejected(old):
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    changed = workflow.replace(old, "unexpected|", 1)
    with pytest.raises(AssertionError, match=r"smoke .* drifted"):
        assert_smoke_contract(changed)


@pytest.mark.parametrize("description", bootstrap.PLACEHOLDER_DESCRIPTIONS)
def test_bootstrap_leftover_scan_detects_description_placeholders(description):
    assert any(
        pattern.search(description) for pattern in (LEFTOVER_TOKENS, LEFTOVER_PHRASES)
    )


@pytest.mark.parametrize("description", bootstrap.PLACEHOLDER_DESCRIPTIONS)
@pytest.mark.parametrize("variant", ["exact", "case", "embedded"])
def test_bootstrap_placeholder_description_is_rejected_before_writing(
    clone, description, variant
):
    value = (
        description
        if variant == "exact"
        else description.upper()
        if variant == "case"
        else f"About: {description} More."
    )
    before = _snapshot(clone)
    with pytest.raises(
        bootstrap.BootstrapError, match=r"invalid description .*placeholder"
    ):
        _run(clone, description=value)
    assert _snapshot(clone) == before
