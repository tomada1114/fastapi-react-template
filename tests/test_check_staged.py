"""Tests for scripts/check_staged.py, the pre-commit layer's secret gate.

Every repository here is a real one under `tmp_path`, driven by the `git`
binary, with the user's and the system's git configuration switched off.
Secret-shaped fixtures are assembled at runtime by `_secret`, so this file
never matches a pattern itself -- and the gate does not refuse its own tests.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.harness._yaml import as_mapping, load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_staged.py"
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
HOOK_ID = "check-staged"
BLOCKED = 1
GIT_FAILED = 2
ALLOWLIST_INVALID = 3
ALLOWLIST = ".check-staged-allow"
OID40 = "3b18e512dba79e4c8300dd08aeb37f8e728b8dad"
OID64 = "0123456789abcdef" * 4


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_staged", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules while the class body runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_staged = _load_module()


def _secret(*parts: str) -> str:
    """Join fragments into a secret-shaped string no source line contains."""
    return "".join(parts)


def _aws_key() -> str:
    return _secret("AK", "IA", "Q" * 16)


SECRET_SAMPLES = {
    "AWS access key": _aws_key(),
    "GitHub token": _secret("gh", "p_", "a" * 36),
    "GitHub fine-grained token": _secret("github", "_pat_", "A" * 22, "_", "b" * 59),
    "Anthropic API key": _secret("sk-", "ant-", "api03-", "x" * 40),
    "OpenAI project key": _secret("sk-", "proj-", "y" * 40),
    "OpenRouter API key": _secret("sk-", "or-", "v1-", "0" * 64),
    "Slack token": _secret("xo", "xb-", "1234567890-abcdefghij"),
    "Stripe live secret key": _secret("sk_", "live_", "Z" * 24),
    "private key": _secret("-----BEGIN ", "OPENSSH PRIVATE", " KEY-----"),
}


@dataclass(frozen=True, slots=True)
class GitRepo:
    """A throwaway repository and the environment every command runs with."""

    root: Path
    env: dict[str, str]

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 -- fixed argv, no shell
            ["git", *args],  # noqa: S607 -- git from PATH, as the hook runs it
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=check,
        )

    def write(self, relative: str, content: str | bytes) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")

    def stage(self, relative: str, content: str | bytes) -> None:
        self.write(relative, content)
        self.git("add", "--", relative)

    def commit_all(self, message: str) -> None:
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", message)

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def run_check(
        self, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 -- fixed argv, no shell
            [sys.executable, str(SCRIPT)],
            cwd=self.root,
            env=env or self.env,
            capture_output=True,
            text=True,
            check=False,
        )


def _isolated_env(tmp_path: Path) -> dict[str, str]:
    """Return an environment free of the caller's git state and configuration."""
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.com",
        GIT_COMMITTER_NAME="Test",
        GIT_COMMITTER_EMAIL="test@example.com",
        GIT_EDITOR="true",
        PRE_COMMIT_HOME=str(tmp_path / "pre-commit-home"),
    )
    env.pop("PRE_COMMIT", None)
    return env


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., GitRepo]:
    """Return a factory for repositories, with or without a first commit."""

    def factory(*, with_commit: bool = True) -> GitRepo:
        root = tmp_path / "repo"
        root.mkdir()
        repo = GitRepo(root, _isolated_env(tmp_path))
        repo.git("init", "--quiet", "--initial-branch=main")
        if with_commit:
            repo.write("README.md", "hello\n")
            repo.commit_all("initial")
        return repo

    return factory


def _allow(repo: GitRepo, *lines: str) -> None:
    """Write `.check-staged-allow` from `lines` and stage it."""
    repo.stage(ALLOWLIST, "".join(f"{line}\n" for line in lines))


def _blob_id(repo: GitRepo, relative: str) -> str:
    """Return the blob id staged at `relative`, as `git rev-parse :<path>` prints it."""
    return repo.git("rev-parse", f":{relative}").stdout.strip()


def _logging_git(tmp_path: Path) -> tuple[Path, Path]:
    """Return a directory holding a `git` that logs its argv, and the log file."""
    real_git = shutil.which("git")
    assert real_git is not None
    log = tmp_path / "git-calls.log"
    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "git"
    wrapper.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> {shlex.quote(str(log))}\n'
        f'exec {shlex.quote(real_git)} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper_dir, log


def _load_pre_commit_config() -> dict[str, object]:
    return as_mapping(load_yaml(PRE_COMMIT_CONFIG), str(PRE_COMMIT_CONFIG))


def _all_hooks(config: dict[str, object]) -> list[dict[str, object]]:
    repos = config["repos"]
    assert isinstance(repos, list)
    return [hook for repo in repos for hook in repo["hooks"]]


def _check_staged_hook(config: dict[str, object]) -> dict[str, object]:
    (hook,) = [hook for hook in _all_hooks(config) if hook["id"] == HOOK_ID]
    return hook


def _install_pre_commit(repo: GitRepo) -> None:
    """Install the real check-staged hook definition into `repo` via pre-commit.

    Only how it is launched changes: `language: python` would build a
    virtualenv per test (and download its build backend), so the script runs
    under the test's own interpreter instead.
    `test_pre_commit_config_runs_the_gate_on_every_commit_kind` pins the real
    language and entry.
    """
    config = _load_pre_commit_config()
    hook = {
        **_check_staged_hook(config),
        "language": "system",
        "entry": f"{shlex.quote(sys.executable)} {shlex.quote(str(SCRIPT))}",
    }
    test_config = {
        "default_install_hook_types": config["default_install_hook_types"],
        "repos": [{"repo": "local", "hooks": [hook]}],
    }
    # JSON is valid YAML, so no YAML writer is needed.
    repo.write(".pre-commit-config.yaml", json.dumps(test_config, indent=2))
    repo.commit_all("add pre-commit config")
    subprocess.run(
        [sys.executable, "-m", "pre_commit", "install"],
        cwd=repo.root,
        env=repo.env,
        capture_output=True,
        check=True,
    )


# --------------------------------------------------------------------------- #
#  Path and content rules
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(".env", "ENV_FILE", id="env"),
        pytest.param(".env.local", "ENV_FILE", id="env-local"),
        pytest.param("app/.env.production", "ENV_FILE", id="nested-env"),
        pytest.param(".ENV", "ENV_FILE", id="env-upper-case"),
        pytest.param(".envrc", "DIRENV_FILE", id="envrc"),
        pytest.param(".envrc.private", "DIRENV_FILE", id="envrc-variant"),
        pytest.param(".envrc.local", "DIRENV_FILE", id="envrc-local"),
        pytest.param(".env.example.local", "ENV_FILE", id="env-example-not-last"),
        pytest.param(".env.sampler", "ENV_FILE", id="env-sample-prefix-only"),
        pytest.param("secrets/token.txt", "SECRETS_DIRECTORY", id="secrets-root"),
        pytest.param("deploy/secrets/db.yml", "SECRETS_DIRECTORY", id="secrets-nested"),
        pytest.param("server.pem", "KEY_FILE", id="pem"),
        pytest.param("tls/server.KEY", "KEY_FILE", id="key-upper-case"),
        pytest.param("id_rsa", "SSH_KEY", id="id-rsa"),
        pytest.param("keys/id_rsa.pub", "SSH_KEY", id="id-rsa-pub"),
        pytest.param(
            ".claude/settings.local.json", "PERSONAL_SETTINGS", id="claude-local"
        ),
        pytest.param(
            "apps/web/.claude/settings.local.json",
            "PERSONAL_SETTINGS",
            id="nested-claude-local",
        ),
        pytest.param(".codex/rules/local.rules", "PERSONAL_SETTINGS", id="codex-local"),
    ],
)
def test_blocked_path_reason_secret_shaped_path_is_refused(
    path: str, expected: str
) -> None:
    assert check_staged.blocked_path_reason(path) is check_staged.BlockedPath[expected]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(".env.example", id="env-example"),
        pytest.param("config/.env.example", id="nested-env-example"),
        pytest.param(".env.sample", id="env-sample"),
        pytest.param(".env.template", id="env-template"),
        pytest.param(".env.test.example", id="env-variant-example"),
        pytest.param("config/.ENV.SAMPLE", id="env-sample-upper-case"),
        pytest.param(".envrc.example", id="envrc-example"),
        pytest.param(".environment", id="env-prefix-only"),
        pytest.param("src/env.py", id="env-module"),
        pytest.param("docs/secrets.md", id="secrets-file-not-directory"),
        pytest.param("src/secretsmanager.py", id="secrets-prefix"),
        pytest.param("monkey.py", id="key-substring"),
        pytest.param("docs/rotating-id_rsa.md", id="id-rsa-not-prefix"),
        pytest.param(".claude/settings.json", id="claude-shared-settings"),
        pytest.param(
            "nested/.claude/settings.local.json.example", id="settings-example"
        ),
    ],
)
def test_blocked_path_reason_ordinary_path_is_allowed(path: str) -> None:
    assert check_staged.blocked_path_reason(path) is None


@pytest.mark.parametrize(
    ("label", "sample"), SECRET_SAMPLES.items(), ids=SECRET_SAMPLES.keys()
)
def test_secret_kind_credential_shape_is_named(label: str, sample: str) -> None:
    content = f"token = {sample}\n".encode()

    assert check_staged.secret_kind(content) == label


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="empty"),
        pytest.param(
            b"ghp_ github_pat_ sk-ant- sk-proj- sk-or- sk_live_ xoxb-\n",
            id="bare-prefixes",
        ),
        pytest.param(b"-----BEGIN PUBLIC KEY-----\n", id="public-key"),
        pytest.param(
            b"weigh the risk-or-reward-tradeoff-analysis\n", id="risk-or-prose"
        ),
        pytest.param(b"xoxo-gossip-girl-season-finale\n", id="xoxo-prose"),
        pytest.param(b"see desk-proj-overview-for-the-quarter\n", id="desk-proj-prose"),
        pytest.param(SCRIPT.read_bytes(), id="the-gate-itself"),
    ],
)
def test_secret_kind_text_without_credentials_is_none(content: bytes) -> None:
    assert check_staged.secret_kind(content) is None


def test_secret_kind_non_utf8_blob_is_skipped() -> None:
    content = b"\xff\xfe" + _aws_key().encode()

    assert check_staged.secret_kind(content) is None


# --------------------------------------------------------------------------- #
#  The script against a real index
# --------------------------------------------------------------------------- #


def test_check_nothing_staged_exits_zero(make_repo: Callable[..., GitRepo]) -> None:
    repo = make_repo()

    result = repo.run_check()

    assert (result.returncode, result.stderr) == (0, "")


def test_check_clean_change_exits_zero(make_repo: Callable[..., GitRepo]) -> None:
    repo = make_repo()
    repo.stage("src/app.py", "print('hello')\n")

    assert repo.run_check().returncode == 0


def test_check_env_file_is_refused_by_name(make_repo: Callable[..., GitRepo]) -> None:
    repo = make_repo()
    repo.stage(".env.local", "harmless\n")

    result = repo.run_check()

    assert result.returncode == BLOCKED
    assert "refused .env.local: an environment file" in result.stderr


def test_check_env_example_passes(make_repo: Callable[..., GitRepo]) -> None:
    repo = make_repo()
    repo.stage(".env.example", "API_KEY=\n")

    assert repo.run_check().returncode == 0


def test_check_env_sample_passes(make_repo: Callable[..., GitRepo]) -> None:
    repo = make_repo()
    repo.stage(".env.sample", "API_KEY=\n")

    assert repo.run_check().returncode == 0


def test_check_secret_content_names_file_and_kind_but_not_value(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage("src/x.py", f"KEY = '{_aws_key()}'\n")

    result = repo.run_check()

    assert result.returncode == BLOCKED
    assert (
        "refused src/x.py: content matches the AWS access key pattern" in result.stderr
    )
    assert _aws_key() not in result.stderr + result.stdout


def test_check_reports_every_finding_in_index_order(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage(".env", "x\n")
    repo.stage("a.txt", SECRET_SAMPLES["GitHub token"])
    repo.stage("b.txt", "clean\n")

    result = repo.run_check()

    refused = [line for line in result.stderr.splitlines() if "refused" in line]
    assert result.returncode == BLOCKED
    assert [line.split(":")[1].strip() for line in refused] == [
        "refused .env",
        "refused a.txt",
    ]


@pytest.mark.parametrize(
    ("staged", "worktree", "expected"),
    [
        pytest.param("clean\n", _aws_key(), 0, id="unstaged-secret-ignored"),
        pytest.param(_aws_key(), "clean\n", BLOCKED, id="staged-secret-refused"),
    ],
)
def test_check_judges_the_index_not_the_worktree(
    make_repo: Callable[..., GitRepo],
    staged: str,
    worktree: str,
    expected: int,
) -> None:
    repo = make_repo()
    repo.stage("notes.txt", staged)
    repo.write("notes.txt", worktree)

    assert repo.run_check().returncode == expected


def test_check_deleting_a_secret_file_passes(make_repo: Callable[..., GitRepo]) -> None:
    repo = make_repo()
    repo.write(".env", "TOKEN=1\n")
    repo.commit_all("committed before the gate existed")
    repo.git("rm", "--quiet", "--cached", ".env")

    assert repo.run_check().returncode == 0


def test_check_binary_blob_does_not_crash(make_repo: Callable[..., GitRepo]) -> None:
    repo = make_repo()
    repo.stage("image.bin", b"\x89PNG\r\n\x1a\n\xff" + _aws_key().encode())

    result = repo.run_check()

    assert (result.returncode, result.stderr) == (0, "")


def test_check_submodule_entry_is_not_read(make_repo: Callable[..., GitRepo]) -> None:
    repo = make_repo()
    commit = repo.head()
    repo.git("update-index", "--add", "--cacheinfo", f"160000,{commit},vendor/lib")

    assert repo.run_check().returncode == 0


@pytest.mark.parametrize(
    ("relative", "content", "expected"),
    [
        pytest.param("a.txt", "clean\n", 0, id="clean"),
        pytest.param("a.txt", _aws_key(), BLOCKED, id="secret"),
    ],
)
def test_check_first_commit_on_unborn_branch_is_judged(
    make_repo: Callable[..., GitRepo],
    relative: str,
    content: str,
    expected: int,
) -> None:
    repo = make_repo(with_commit=False)
    repo.stage(relative, content)

    assert repo.run_check().returncode == expected


def test_check_outside_a_repository_fails_closed(tmp_path: Path) -> None:
    outside = tmp_path / "plain"
    outside.mkdir()

    result = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(SCRIPT)],
        cwd=outside,
        env=_isolated_env(tmp_path) | {"GIT_CEILING_DIRECTORIES": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == GIT_FAILED
    assert result.stderr.startswith("check_staged: `git ")


def test_check_reads_all_blobs_with_one_cat_file_batch(
    make_repo: Callable[..., GitRepo],
    tmp_path: Path,
) -> None:
    real_git = shutil.which("git")
    assert real_git is not None
    log = tmp_path / "git-calls.log"
    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "git"
    wrapper.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> {shlex.quote(str(log))}\n'
        f'exec {shlex.quote(real_git)} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    repo = make_repo()
    for name in ("a.txt", "b.txt", "c.txt"):
        repo.stage(name, f"{name}\n")
    repo.stage("d.txt", _aws_key())
    env = repo.env | {"PATH": f"{wrapper_dir}{os.pathsep}{repo.env['PATH']}"}

    result = repo.run_check(env)

    calls = log.read_text(encoding="utf-8").splitlines()
    assert result.returncode == BLOCKED
    assert [call for call in calls if call.startswith("cat-file")] == [
        "cat-file --batch"
    ]


# --------------------------------------------------------------------------- #
#  The allowlist, parsed on its own
# --------------------------------------------------------------------------- #


def _problems(text: str) -> list[tuple[str, int | None]]:
    _, problems = check_staged.parse_allowlist(text)
    return [(problem.kind.name, problem.line) for problem in problems]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty"),
        pytest.param("# a reason\n# and another\n", id="comments-only"),
        pytest.param("\n   \n\t\n", id="blank-only"),
    ],
)
def test_parse_allowlist_without_entries_is_empty(text: str) -> None:
    allowlist, problems = check_staged.parse_allowlist(text)

    assert (allowlist.entries, problems) == ((), [])


def test_parse_allowlist_valid_entries_keep_their_line_numbers() -> None:
    text = (
        "# Public root CA; holds no private key.\n"
        "path deploy/certs/ca.pem\n"
        "\n"
        "# Fake key and token the parser tests feed in.\n"
        "path tests/fixtures/secrets/aws.txt\n"
        f"content tests/fixtures/secrets/aws.txt {OID40}\n"
        f"content tests/data/a b.txt {OID64}\n"
    )

    allowlist, problems = check_staged.parse_allowlist(text)

    entry = check_staged.AllowEntry
    assert problems == []
    assert allowlist.entries == (
        entry(kind="path", path="deploy/certs/ca.pem", blob_id=None, line=2),
        entry(kind="path", path="tests/fixtures/secrets/aws.txt", blob_id=None, line=5),
        entry(
            kind="content",
            path="tests/fixtures/secrets/aws.txt",
            blob_id=OID40,
            line=6,
        ),
        entry(kind="content", path="tests/data/a b.txt", blob_id=OID64, line=7),
    )


@pytest.mark.parametrize(
    ("text", "line"),
    [
        pytest.param("# r\nallow a.pem\n", 2, id="unknown-keyword"),
        pytest.param("# r\n  path a.pem\n", 2, id="leading-whitespace"),
        pytest.param("# r\npath\n", 2, id="path-without-path"),
        pytest.param("# r\npath \n", 2, id="path-with-empty-path"),
        pytest.param("# r\ncontent a.txt\n", 2, id="content-without-id"),
        pytest.param(f"# r\ncontent a.txt {OID40.upper()}\n", 2, id="upper-case-id"),
        pytest.param(f"# r\ncontent a.txt {OID40[:39]}\n", 2, id="39-hex-id"),
        pytest.param("# r\npath /abs/file.pem\n", 2, id="absolute"),
        pytest.param("# r\npath C:/file.pem\n", 2, id="drive-letter"),
        pytest.param("# r\npath docs\\id_rsa-rotation.md\n", 2, id="backslash"),
        pytest.param("# r\npath a//b.pem\n", 2, id="empty-segment"),
        pytest.param("# r\npath ./a.pem\n", 2, id="dot-segment"),
        pytest.param("# r\npath a/../b.pem\n", 2, id="dot-dot-segment"),
        pytest.param("# r\npath a.pem \n", 2, id="trailing-space"),
        pytest.param("# r\npath a\0b.pem\n", 2, id="nul-character"),
        pytest.param("path a.pem\n", 1, id="no-reason-at-start"),
        pytest.param("# r\n\npath a.pem\n", 3, id="blank-after-reason"),
        pytest.param("# r\npath a.pem\npath a.pem\n", 3, id="duplicate"),
    ],
)
def test_parse_allowlist_malformed_line_is_a_syntax_problem(
    text: str, line: int
) -> None:
    assert _problems(text) == [("SYNTAX", line)]


def test_parse_allowlist_duplicate_names_the_first_line() -> None:
    _, problems = check_staged.parse_allowlist(
        "# r\npath a.pem\n\n# again\npath a.pem\n"
    )

    (problem,) = problems
    assert (problem.line, problem.detail) == (5, "duplicates line 2")


def test_parse_allowlist_reports_every_problem_in_line_order() -> None:
    text = "path a.pem\n# r\npath *\npath ok.pem\nwhat\n"

    assert _problems(text) == [("SYNTAX", 1), ("TOO_BROAD", 3), ("SYNTAX", 5)]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("*", id="star"),
        pytest.param("**", id="double-star"),
        pytest.param("*.pem", id="extension-glob"),
        pytest.param("secrets/*", id="directory-glob"),
        pytest.param("id_rsa?", id="question-mark"),
        pytest.param("tests/fixtures/secrets/", id="trailing-slash"),
        pytest.param(".", id="dot"),
    ],
)
@pytest.mark.parametrize(
    "template",
    [
        pytest.param("path {}", id="path"),
        pytest.param(f"content {{}} {OID40}", id="content"),
    ],
)
def test_parse_allowlist_broad_path_is_too_broad(path: str, template: str) -> None:
    text = f"# Everything, please.\n{template.format(path)}\n"

    assert _problems(text) == [("TOO_BROAD", 2)]


VALID_ALLOWLIST = f"# r\npath a.pem\ncontent b.txt {OID40}\n"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(VALID_ALLOWLIST.replace("\n", "\r\n"), id="crlf"),
        pytest.param(f"\ufeff{VALID_ALLOWLIST}", id="bom"),
    ],
)
def test_parse_allowlist_crlf_and_bom_parse_like_lf(text: str) -> None:
    expected = check_staged.parse_allowlist(VALID_ALLOWLIST)

    assert check_staged.parse_allowlist(text) == expected
    assert (len(expected[0].entries), expected[1]) == (2, [])


def test_parse_allowlist_problem_detail_never_echoes_the_line() -> None:
    token = SECRET_SAMPLES["GitHub token"]
    text = "\n".join(
        [
            f"path {token}",
            "# r",
            f"what {token}",
            f" path {token}",
            f"path {token}/",
            f"path {token}*",
            f"path /{token}",
            f"content {token}",
            f"content {token} {token}",
            f"path {token} ",
            f"path {token}",
            f"path {token}",
        ],
    )

    _, problems = check_staged.parse_allowlist(text)

    assert len(problems) == 10
    assert [problem for problem in problems if token in problem.detail] == []


@pytest.mark.parametrize(
    "comment",
    [
        pytest.param("#", id="bare-hash"),
        pytest.param("#   \t", id="hash-and-whitespace"),
        pytest.param("# a real reason\n#", id="bare-hash-below-a-reason"),
    ],
)
def test_parse_allowlist_reason_without_text_is_a_syntax_problem(
    comment: str,
) -> None:
    text = f"{comment}\npath a.pem\n"
    line = text.count("\n")

    _, problems = check_staged.parse_allowlist(text)

    assert [
        (problem.kind.name, problem.line, problem.detail) for problem in problems
    ] == [("SYNTAX", line, "an entry needs a reason comment with text")]


# Characters some line splitter (Python's str.splitlines among them) breaks a
# line on, though git, GitHub, and editors show one line.
HIDDEN_SEPARATORS = {
    "vertical-tab": "\x0b",
    "form-feed": "\x0c",
    "file-separator": "\x1c",
    "group-separator": "\x1d",
    "record-separator": "\x1e",
    "next-line": "\x85",
    "line-separator": "\u2028",
    "paragraph-separator": "\u2029",
    "lone-carriage-return": "\r",
}
OTHER_CONTROLS = {"nul": "\x00", "bell": "\x07", "escape": "\x1b", "delete": "\x7f"}


@pytest.mark.parametrize(
    "character",
    [
        pytest.param(character, id=name)
        for name, character in {**HIDDEN_SEPARATORS, **OTHER_CONTROLS}.items()
    ],
)
@pytest.mark.parametrize(
    "template",
    [
        pytest.param("# looks like a comment{}path .env\n", id="in-a-comment"),
        pytest.param("# r\npath a{}.pem\n", id="in-an-entry"),
    ],
)
def test_parse_allowlist_control_character_is_a_syntax_problem(
    character: str, template: str
) -> None:
    token = SECRET_SAMPLES["GitHub token"]
    text = template.format(character) + f"# {token}\n"

    allowlist, problems = check_staged.parse_allowlist(text)

    line = template.count("\n")
    assert allowlist.entries == ()
    assert [(problem.kind.name, problem.line) for problem in problems] == [
        ("SYNTAX", line)
    ]
    assert token not in problems[0].detail
    assert character not in problems[0].detail


def test_parse_allowlist_tab_inside_a_comment_is_accepted() -> None:
    allowlist, problems = check_staged.parse_allowlist("#\treason\npath a.pem\n")

    assert (len(allowlist.entries), problems) == (1, [])


# --------------------------------------------------------------------------- #
#  The allowlist against a real index
# --------------------------------------------------------------------------- #

ROTATION_DOC = "docs/id_rsa-rotation.md"
CA_CERT = "deploy/certs/ca.pem"
GITHUB_FIXTURE = "tests/data/fake_token.txt"
PUBLIC_CERT = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def _stale(line: int) -> str:
    return f"ERR_STAGED_ALLOWLIST_STALE: .check-staged-allow:{line}:"


def test_check_path_entry_lets_a_blocked_path_through(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage(ROTATION_DOC, "How we rotate SSH keys.\n")
    _allow(repo, "# A runbook about keys, not a key.", f"path {ROTATION_DOC}")

    result = repo.run_check()

    assert (result.returncode, result.stderr) == (0, "")


@pytest.mark.parametrize(
    "character",
    [pytest.param(character, id=name) for name, character in HIDDEN_SEPARATORS.items()],
)
def test_check_entry_hidden_behind_a_line_separator_exempts_nothing(
    make_repo: Callable[..., GitRepo], character: str
) -> None:
    repo = make_repo()
    repo.stage(".env", "TOKEN=1\n")
    repo.stage(ALLOWLIST, f"# looks like a comment{character}path .env\n")

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert "ERR_STAGED_ALLOWLIST_SYNTAX: .check-staged-allow:1:" in result.stderr
    assert "path .env" not in result.stderr


@pytest.mark.parametrize(
    "variant",
    [
        pytest.param("ca.pem.key", id="longer-name"),
        pytest.param("sub/ca.pem", id="same-name-in-a-directory"),
        pytest.param("CA.pem", id="other-case"),
    ],
)
def test_check_path_entry_exempts_only_its_exact_path(
    make_repo: Callable[..., GitRepo], variant: str
) -> None:
    repo = make_repo()
    repo.stage("ca.pem", PUBLIC_CERT)
    # Through the index directly: a case-insensitive file system cannot hold
    # ca.pem and CA.pem side by side.
    blob = _blob_id(repo, "ca.pem")
    repo.git("update-index", "--add", "--cacheinfo", f"100644,{blob},{variant}")
    _allow(repo, "# A public root CA.", "path ca.pem")

    result = repo.run_check()

    assert result.returncode == BLOCKED
    assert f"refused {variant}: a .pem or .key file" in result.stderr
    assert "refused ca.pem:" not in result.stderr


def test_check_blocked_path_without_an_entry_is_refused(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage(ROTATION_DOC, "How we rotate SSH keys.\n")
    _allow(repo, "# Nothing exempt yet.")

    result = repo.run_check()

    assert result.returncode == BLOCKED
    assert f"refused {ROTATION_DOC}: an id_rsa* file is an SSH key" in result.stderr


def test_check_path_entry_does_not_skip_the_content_scan(
    make_repo: Callable[..., GitRepo],
) -> None:
    fixture = "tests/fixtures/secrets/aws.txt"
    repo = make_repo()
    repo.stage(fixture, f"{_aws_key()}\n")
    _allow(repo, "# Fake AWS key the parser tests feed in.", f"path {fixture}")

    result = repo.run_check()

    assert result.returncode == BLOCKED
    assert (
        f"refused {fixture}: content matches the AWS access key pattern"
        in result.stderr
    )


def test_check_path_and_content_entries_together_pass(
    make_repo: Callable[..., GitRepo],
) -> None:
    fixture = "tests/fixtures/secrets/aws.txt"
    repo = make_repo()
    repo.stage(fixture, f"{_aws_key()}\n")
    _allow(
        repo,
        "# Fake AWS key the parser tests feed in.",
        f"path {fixture}",
        f"content {fixture} {_blob_id(repo, fixture)}",
    )

    result = repo.run_check()

    assert (result.returncode, result.stderr) == (0, "")


def test_check_content_entry_lets_that_exact_content_through(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage(GITHUB_FIXTURE, f"{SECRET_SAMPLES['GitHub token']}\n")
    _allow(
        repo,
        "# A fake token the client tests send.",
        f"content {GITHUB_FIXTURE} {_blob_id(repo, GITHUB_FIXTURE)}",
    )

    result = repo.run_check()

    assert (result.returncode, result.stderr) == (0, "")


def test_check_edited_content_is_judged_again(
    make_repo: Callable[..., GitRepo],
) -> None:
    token = SECRET_SAMPLES["GitHub token"]
    repo = make_repo()
    repo.stage(GITHUB_FIXTURE, f"{token}\n")
    _allow(
        repo,
        "# A fake token the client tests send.",
        f"content {GITHUB_FIXTURE} {_blob_id(repo, GITHUB_FIXTURE)}",
    )
    repo.stage(GITHUB_FIXTURE, f"{token}\nand a second line\n")

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert _stale(2) in result.stderr
    assert (
        f"refused {GITHUB_FIXTURE}: content matches the GitHub token pattern"
        in result.stderr
    )
    assert token not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("path *", id="path-star"),
        pytest.param(f"content * {OID40}", id="content-star"),
    ],
)
def test_check_star_entry_exempts_nothing(
    make_repo: Callable[..., GitRepo], entry: str
) -> None:
    repo = make_repo()
    repo.stage(".env", "TOKEN=1\n")
    repo.stage("secrets/db.yml", "password: hunter2\n")
    _allow(repo, "# Everything, please.", entry)

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert "ERR_STAGED_ALLOWLIST_TOO_BROAD: .check-staged-allow:2:" in result.stderr
    assert "refused" not in result.stderr


def test_check_entry_naming_a_directory_is_too_broad(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage("secrets/a.txt", "a\n")
    repo.stage("secrets/b.txt", "b\n")
    _allow(repo, "# Every fixture in there.", "path secrets")

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert (
        "ERR_STAGED_ALLOWLIST_TOO_BROAD: .check-staged-allow:2: "
        "names a directory in the index" in result.stderr
    )
    assert "refused" not in result.stderr


def test_check_path_entry_for_a_file_not_in_the_index_is_stale(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    _allow(repo, "# A certificate that never arrived.", f"path {CA_CERT}")

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert _stale(2) in result.stderr


def test_check_path_entry_no_rule_refuses_is_stale(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage("src/app.py", "print('hello')\n")
    _allow(repo, "# Not needed at all.", "path src/app.py")

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert _stale(2) in result.stderr
    assert "refused" not in result.stderr


def _commit_allowlisted_cert(repo: GitRepo) -> None:
    repo.write(CA_CERT, PUBLIC_CERT)
    repo.write(ALLOWLIST, f"# Public root CA; holds no private key.\npath {CA_CERT}\n")
    repo.commit_all("add the CA certificate")


def test_check_deleting_an_allowlisted_file_keeping_its_entry_is_stale(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    _commit_allowlisted_cert(repo)
    repo.git("rm", "--quiet", CA_CERT)

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert _stale(2) in result.stderr


def test_check_deleting_an_allowlisted_file_with_its_entry_passes(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    _commit_allowlisted_cert(repo)
    repo.git("rm", "--quiet", CA_CERT)
    _allow(repo, "# Nothing exempt any more.")

    result = repo.run_check()

    assert (result.returncode, result.stderr) == (0, "")


def test_check_renaming_an_allowlisted_file_is_stale_and_refused(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    _commit_allowlisted_cert(repo)
    repo.git("mv", CA_CERT, "deploy/certs/root-ca.pem")

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert _stale(2) in result.stderr
    assert "refused deploy/certs/root-ca.pem: a .pem or .key file" in result.stderr


def test_check_content_entry_on_a_submodule_is_stale(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    commit = repo.head()
    repo.git("update-index", "--add", "--cacheinfo", f"160000,{commit},vendor/lib")
    _allow(repo, "# A vendored library.", f"content vendor/lib {commit}")

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert _stale(2) in result.stderr


def test_check_content_entry_exempts_only_its_own_path(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage("a.txt", f"{_aws_key()}\n")
    repo.stage("b.txt", f"{_aws_key()}\n")
    _allow(repo, "# A fake key fixture.", f"content a.txt {_blob_id(repo, 'a.txt')}")

    result = repo.run_check()

    assert _blob_id(repo, "a.txt") == _blob_id(repo, "b.txt")
    assert result.returncode == BLOCKED
    assert "refused b.txt: content matches the AWS access key pattern" in result.stderr
    assert "refused a.txt" not in result.stderr


def test_check_path_entry_on_a_submodule_lets_it_through(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    commit = repo.head()
    repo.git(
        "update-index", "--add", "--cacheinfo", f"160000,{commit},vendor/secrets/lib"
    )
    _allow(
        repo, "# A vendored library in a secrets/ folder.", "path vendor/secrets/lib"
    )

    result = repo.run_check()

    assert (result.returncode, result.stderr) == (0, "")


def test_check_entry_in_another_case_is_stale_with_an_icase_hint(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage(CA_CERT, PUBLIC_CERT)
    _allow(repo, "# A public root CA.", "path deploy/certs/CA.pem")

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert (
        f"{_stale(2)} names no file in the index "
        "(`git ls-files -- ':(icase)<path>'` finds its exact spelling)"
    ) in result.stderr


def test_check_unmerged_entry_path_fails_closed(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage(CA_CERT, PUBLIC_CERT)
    blob = _blob_id(repo, CA_CERT)
    _allow(repo, "# A public root CA.", f"path {CA_CERT}")
    subprocess.run(
        ["git", "update-index", "--index-info"],  # noqa: S607 -- git from PATH
        cwd=repo.root,
        env=repo.env,
        input=f"0 {'0' * 40}\t{CA_CERT}\n"
        f"100644 {blob} 2\t{CA_CERT}\n100644 {blob} 3\t{CA_CERT}\n",
        text=True,
        check=True,
    )

    result = repo.run_check()

    assert result.returncode == GIT_FAILED
    assert "unmerged" in result.stderr
    assert CA_CERT not in result.stderr


def _git_with_ls_files_output(tmp_path: Path, output: str) -> Path:
    """Return a directory holding a `git` whose full index listing prints `output`."""
    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "git"
    wrapper.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        f"  'ls-files --stage -z --full-name -- :(top)') printf {shlex.quote(output)};"
        " exit 0;;\nesac\n"
        f'exec {shlex.quote(real_git)} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper_dir


@pytest.mark.parametrize(
    "output",
    [
        pytest.param("garbage\\0", id="no-tab"),
        pytest.param("100644 nothex 0\\tdeploy/certs/ca.pem\\0", id="bad-object-id"),
        pytest.param(f"100644 {OID40}\\tdeploy/certs/ca.pem\\0", id="missing-stage"),
    ],
)
def test_check_malformed_index_listing_fails_closed(
    make_repo: Callable[..., GitRepo], tmp_path: Path, output: str
) -> None:
    repo = make_repo()
    repo.stage(CA_CERT, PUBLIC_CERT)
    _allow(repo, "# A public root CA.", f"path {CA_CERT}")
    wrapper_dir = _git_with_ls_files_output(tmp_path, output)
    env = repo.env | {"PATH": f"{wrapper_dir}{os.pathsep}{repo.env['PATH']}"}

    result = repo.run_check(env)

    assert result.returncode == GIT_FAILED
    assert "unexpected `git ls-files --stage` record" in result.stderr
    assert CA_CERT not in result.stderr


def test_check_entry_paths_never_reach_git_argv(
    make_repo: Callable[..., GitRepo], tmp_path: Path
) -> None:
    wrapper_dir, log = _logging_git(tmp_path)
    repo = make_repo()
    repo.stage(CA_CERT, PUBLIC_CERT)
    _allow(repo, "# A public root CA.", f"path {CA_CERT}")
    env = repo.env | {"PATH": f"{wrapper_dir}{os.pathsep}{repo.env['PATH']}"}

    result = repo.run_check(env)

    calls = log.read_text(encoding="utf-8").splitlines()
    assert result.returncode == 0
    assert [call for call in calls if CA_CERT in call] == []


def test_check_content_entry_for_content_with_no_secret_is_stale(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage("notes.txt", "nothing secret here\n")
    _allow(
        repo,
        "# Once held a fake token.",
        f"content notes.txt {_blob_id(repo, 'notes.txt')}",
    )

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert _stale(2) in result.stderr


def test_check_unstaged_allowlist_exempts_nothing(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage(ROTATION_DOC, "How we rotate SSH keys.\n")
    repo.write(ALLOWLIST, f"# A runbook, not a key.\npath {ROTATION_DOC}\n")

    assert repo.run_check().returncode == BLOCKED


def test_check_staged_allowlist_applies_after_the_worktree_copy_changes(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage(ROTATION_DOC, "How we rotate SSH keys.\n")
    _allow(repo, "# A runbook, not a key.", f"path {ROTATION_DOC}")
    repo.write(ALLOWLIST, "# reverted in the working tree only\n")

    assert repo.run_check().returncode == 0


def test_check_allowlist_content_is_scanned_like_any_file(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    repo.stage(ROTATION_DOC, "How we rotate SSH keys.\n")
    _allow(
        repo,
        f"# The runbook mentions {SECRET_SAMPLES['GitHub token']}",
        f"path {ROTATION_DOC}",
    )

    result = repo.run_check()

    assert result.returncode == BLOCKED
    assert (
        "refused .check-staged-allow: content matches the GitHub token pattern"
        in result.stderr
    )


def _stage_allowlist_symlink(repo: GitRepo) -> None:
    repo.write("link-target.txt", "elsewhere")
    target = repo.git("hash-object", "-w", "link-target.txt").stdout.strip()
    repo.git("update-index", "--add", "--cacheinfo", f"120000,{target},{ALLOWLIST}")


def _stage_non_utf8_allowlist(repo: GitRepo) -> None:
    repo.stage(ALLOWLIST, b"# Latin-1 \xe9\npath a.pem\n")


def _stage_allowlist_directory(repo: GitRepo) -> None:
    repo.stage(f"{ALLOWLIST}/x", "# r\n")


@pytest.mark.parametrize(
    "stage_allowlist",
    [
        pytest.param(_stage_allowlist_symlink, id="symlink"),
        pytest.param(_stage_non_utf8_allowlist, id="not-utf8"),
        pytest.param(_stage_allowlist_directory, id="directory"),
    ],
)
def test_check_allowlist_that_is_not_a_text_file_fails_closed(
    make_repo: Callable[..., GitRepo],
    stage_allowlist: Callable[[GitRepo], None],
) -> None:
    repo = make_repo()
    repo.stage(".env", "TOKEN=1\n")
    stage_allowlist(repo)

    result = repo.run_check()

    assert result.returncode == ALLOWLIST_INVALID
    assert result.stderr.startswith("ERR_STAGED_ALLOWLIST_FILE: .check-staged-allow:")
    assert "refused" not in result.stderr


def test_check_reports_expected_and_next_for_each_allowlist_problem(
    make_repo: Callable[..., GitRepo],
) -> None:
    repo = make_repo()
    _allow(repo, "# r", "path *")

    result = repo.run_check()

    assert result.stderr.splitlines() == [
        (
            "ERR_STAGED_ALLOWLIST_TOO_BROAD: .check-staged-allow:2: "
            "the path is a glob (* or ?)"
        ),
        (
            "Expected: one exact file per entry; globs, directories, and "
            '"." are not accepted'
        ),
        (
            "Next: list each file on its own line (`git ls-files -- <directory>` "
            "prints them), git add .check-staged-allow, and commit again"
        ),
    ]


def test_check_with_an_allowlist_reads_blobs_with_two_cat_file_batches(
    make_repo: Callable[..., GitRepo],
    tmp_path: Path,
) -> None:
    wrapper_dir, log = _logging_git(tmp_path)
    repo = make_repo()
    repo.stage(ROTATION_DOC, "How we rotate SSH keys.\n")
    for name in ("a.txt", "b.txt"):
        repo.stage(name, f"{name}\n")
    repo.stage("d.txt", _aws_key())
    _allow(repo, "# A runbook, not a key.", f"path {ROTATION_DOC}")
    env = repo.env | {"PATH": f"{wrapper_dir}{os.pathsep}{repo.env['PATH']}"}

    result = repo.run_check(env)

    calls = log.read_text(encoding="utf-8").splitlines()
    assert result.returncode == BLOCKED
    assert [call for call in calls if call.startswith("cat-file")] == [
        "cat-file --batch",
        "cat-file --batch",
    ]


# --------------------------------------------------------------------------- #
#  The hook as installed by pre-commit, on every kind of commit
# --------------------------------------------------------------------------- #


def test_pre_commit_config_runs_the_gate_on_every_commit_kind() -> None:
    config = _load_pre_commit_config()
    hook = _check_staged_hook(config)
    hook_types, stages = config["default_install_hook_types"], hook["stages"]

    assert isinstance(hook_types, list)
    assert isinstance(stages, list)
    assert {"pre-commit", "pre-merge-commit"} <= set(hook_types)
    assert {"pre-commit", "pre-merge-commit"} <= set(stages)
    assert (hook["always_run"], hook["pass_filenames"]) == (True, False)
    assert not {"files", "exclude", "types", "types_or"} & hook.keys()


def test_pre_commit_config_runs_the_gate_without_uv() -> None:
    hook = _check_staged_hook(_load_pre_commit_config())

    assert (hook["language"], hook["entry"]) == (
        "python",
        "python scripts/check_staged.py",
    )
    assert "additional_dependencies" not in hook


def test_pre_commit_config_only_the_gate_runs_at_pre_merge_commit() -> None:
    # A hook's manifest may declare stages of its own (typos lists
    # pre-merge-commit), which `default_stages` would not override, so every
    # other hook must name its stages explicitly.
    others = [
        hook for hook in _all_hooks(_load_pre_commit_config()) if hook["id"] != HOOK_ID
    ]

    assert others
    assert {str(hook["id"]): hook.get("stages") for hook in others} == {
        str(hook["id"]): ["pre-commit"] for hook in others
    }


@pytest.fixture
def hooked_repo(make_repo: Callable[..., GitRepo]) -> GitRepo:
    """Return a committed repository with the check-staged hook installed."""
    repo = make_repo()
    repo.write("shared.txt", "base\n")
    repo.commit_all("base")
    _install_pre_commit(repo)
    return repo


def test_ordinary_commit_with_secret_is_refused(hooked_repo: GitRepo) -> None:
    before = hooked_repo.head()
    hooked_repo.stage(".env.local", "TOKEN=1\n")

    result = hooked_repo.git("commit", "-m", "leak", check=False)

    assert result.returncode != 0
    assert "refused .env.local" in result.stdout + result.stderr
    assert hooked_repo.head() == before


def test_ordinary_commit_of_env_example_passes(hooked_repo: GitRepo) -> None:
    before = hooked_repo.head()
    hooked_repo.stage(".env.example", "TOKEN=\n")

    hooked_repo.git("commit", "--quiet", "-m", "example")

    assert hooked_repo.head() != before


def test_commit_with_pathspec_judges_the_temporary_index(hooked_repo: GitRepo) -> None:
    before = hooked_repo.head()
    hooked_repo.write("shared.txt", f"{_aws_key()}\n")

    result = hooked_repo.git("commit", "-m", "leak", "--", "shared.txt", check=False)

    assert result.returncode != 0
    assert (
        "refused shared.txt: content matches the AWS access key pattern"
        in result.stdout + result.stderr
    )
    assert hooked_repo.head() == before


def _commit_on_side_branch(repo: GitRepo, relative: str, content: str) -> None:
    """Commit `content` on a new `side` branch, past the hook, then return to main."""
    repo.git("switch", "--quiet", "-c", "side")
    repo.write(relative, content)
    repo.git("add", "--", relative)
    repo.git("commit", "--quiet", "--no-verify", "-m", "side")
    repo.git("switch", "--quiet", "main")


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        pytest.param("config.txt", f"{_aws_key()}\n", id="secret-content"),
        pytest.param(".env", "TOKEN=1\n", id="secret-path"),
    ],
)
def test_clean_merge_of_content_already_in_the_other_history_passes(
    hooked_repo: GitRepo,
    relative: str,
    content: str,
) -> None:
    _commit_on_side_branch(hooked_repo, relative, content)
    before = hooked_repo.head()

    hooked_repo.git("merge", "--quiet", "--no-ff", "--no-edit", "side")

    assert hooked_repo.head() != before
    assert (
        hooked_repo.git("rev-parse", "HEAD^2").stdout
        == hooked_repo.git("rev-parse", "side").stdout
    )


def test_clean_merge_producing_new_secret_content_is_refused(
    hooked_repo: GitRepo,
) -> None:
    # Both sides edit shared.txt in different places, so the merged blob is
    # new to both histories and is judged at pre-merge-commit.
    hooked_repo.write("shared.txt", "top\nmiddle\nbottom\n")
    hooked_repo.commit_all("three lines")
    _commit_on_side_branch(hooked_repo, "shared.txt", f"{_aws_key()}\nmiddle\nbottom\n")
    hooked_repo.write("shared.txt", "top\nmiddle\nmain\n")
    hooked_repo.commit_all("main edits the bottom")
    before = hooked_repo.head()

    result = hooked_repo.git("merge", "--no-ff", "--no-edit", "side", check=False)

    assert result.returncode != 0
    assert "refused shared.txt" in result.stdout + result.stderr
    assert hooked_repo.head() == before


def test_merge_adding_new_secret_content_is_refused_with_merge_hint(
    hooked_repo: GitRepo,
) -> None:
    _commit_on_side_branch(hooked_repo, "side.txt", "harmless\n")
    hooked_repo.git("merge", "--quiet", "--no-ff", "--no-commit", "side")
    hooked_repo.stage("added-during-merge.txt", f"{_aws_key()}\n")
    before = hooked_repo.head()

    result = hooked_repo.git("commit", "--no-edit", check=False)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "refused added-during-merge.txt" in output
    assert "refused side.txt" not in output
    assert "A merge is in progress" in output
    assert hooked_repo.head() == before


def _diverge_on_shared_file(repo: GitRepo) -> None:
    """Commit conflicting edits to shared.txt on `side` and on `main`."""
    repo.git("switch", "--quiet", "-c", "side")
    repo.write("shared.txt", "side\n")
    repo.git("commit", "--quiet", "-am", "side")
    repo.git("switch", "--quiet", "main")
    repo.write("shared.txt", "main\n")
    repo.git("commit", "--quiet", "-am", "main")


def test_conflicted_merge_resolution_with_secret_is_refused(
    hooked_repo: GitRepo,
) -> None:
    _diverge_on_shared_file(hooked_repo)
    before = hooked_repo.head()
    assert hooked_repo.git("merge", "side", check=False).returncode != 0
    hooked_repo.stage("shared.txt", f"resolved\n{_aws_key()}\n")

    result = hooked_repo.git("commit", "--no-edit", check=False)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "refused shared.txt" in output
    assert "A merge is in progress" in output
    assert hooked_repo.head() == before


def test_conflicted_merge_keeps_content_already_in_the_other_history(
    hooked_repo: GitRepo,
) -> None:
    _commit_on_side_branch(hooked_repo, "config.txt", f"{_aws_key()}\n")
    hooked_repo.git("switch", "--quiet", "side")
    hooked_repo.write("shared.txt", "side\n")
    hooked_repo.git("commit", "--quiet", "--no-verify", "-am", "side edit")
    hooked_repo.git("switch", "--quiet", "main")
    hooked_repo.write("shared.txt", "main\n")
    hooked_repo.git("commit", "--quiet", "-am", "main edit")
    assert hooked_repo.git("merge", "side", check=False).returncode != 0
    hooked_repo.stage("shared.txt", "resolved\n")
    before = hooked_repo.head()

    hooked_repo.git("commit", "--quiet", "--no-edit")

    assert hooked_repo.head() != before


def test_commit_at_a_rebase_stop_with_secret_is_refused(hooked_repo: GitRepo) -> None:
    _diverge_on_shared_file(hooked_repo)
    hooked_repo.git("switch", "--quiet", "side")
    assert hooked_repo.git("rebase", "main", check=False).returncode != 0
    before = hooked_repo.head()
    hooked_repo.stage("shared.txt", f"resolved\n{_aws_key()}\n")

    result = hooked_repo.git("commit", "--no-edit", check=False)

    assert result.returncode != 0
    assert "refused shared.txt" in result.stdout + result.stderr
    assert hooked_repo.head() == before


def test_ordinary_commit_with_its_path_entry_passes(hooked_repo: GitRepo) -> None:
    before = hooked_repo.head()
    hooked_repo.stage(CA_CERT, PUBLIC_CERT)
    _allow(hooked_repo, "# Public root CA; holds no private key.", f"path {CA_CERT}")

    hooked_repo.git("commit", "--quiet", "-m", "add the CA certificate")

    assert hooked_repo.head() != before


def test_commit_with_pathspec_ignores_an_entry_left_out_of_it(
    hooked_repo: GitRepo,
) -> None:
    before = hooked_repo.head()
    hooked_repo.stage(CA_CERT, PUBLIC_CERT)
    _allow(hooked_repo, "# Public root CA; holds no private key.", f"path {CA_CERT}")

    result = hooked_repo.git("commit", "-m", "cert", "--", CA_CERT, check=False)

    assert result.returncode != 0
    assert f"refused {CA_CERT}: a .pem or .key file" in result.stdout + result.stderr
    assert hooked_repo.head() == before


def test_clean_merge_of_an_allowlisted_file_and_its_entry_passes(
    hooked_repo: GitRepo,
) -> None:
    hooked_repo.git("switch", "--quiet", "-c", "side")
    hooked_repo.write(CA_CERT, PUBLIC_CERT)
    hooked_repo.write(ALLOWLIST, f"# Public root CA.\npath {CA_CERT}\n")
    hooked_repo.git("add", "--", CA_CERT, ALLOWLIST)
    hooked_repo.git("commit", "--quiet", "--no-verify", "-m", "side")
    hooked_repo.git("switch", "--quiet", "main")
    before = hooked_repo.head()

    hooked_repo.git("merge", "--quiet", "--no-ff", "--no-edit", "side")

    assert hooked_repo.head() != before


def _token_file_with_entry(repo: GitRepo, line: str) -> None:
    """Write the fake token file ending in `line`, and an entry for that content."""
    repo.stage(GITHUB_FIXTURE, f"{SECRET_SAMPLES['GitHub token']}\n{line}\n")
    repo.write(
        ALLOWLIST,
        "# A fake token the client tests send.\n"
        f"content {GITHUB_FIXTURE} {_blob_id(repo, GITHUB_FIXTURE)}\n",
    )
    repo.git("add", "--", ALLOWLIST)


def test_conflicted_merge_changing_allowlisted_content_is_refused(
    hooked_repo: GitRepo,
) -> None:
    _token_file_with_entry(hooked_repo, "base")
    hooked_repo.git("commit", "--quiet", "-m", "base token")
    hooked_repo.git("switch", "--quiet", "-c", "side")
    _token_file_with_entry(hooked_repo, "side")
    hooked_repo.git("commit", "--quiet", "--no-verify", "-m", "side token")
    hooked_repo.git("switch", "--quiet", "main")
    _token_file_with_entry(hooked_repo, "main")
    hooked_repo.git("commit", "--quiet", "--no-verify", "-m", "main token")
    before = hooked_repo.head()
    assert hooked_repo.git("merge", "side", check=False).returncode != 0
    hooked_repo.stage(GITHUB_FIXTURE, f"{SECRET_SAMPLES['GitHub token']}\nresolved\n")
    hooked_repo.git("checkout", "--ours", "--", ALLOWLIST)
    hooked_repo.git("add", "--", ALLOWLIST)

    result = hooked_repo.git("commit", "--no-edit", check=False)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert _stale(2) in output
    assert (
        f"refused {GITHUB_FIXTURE}: content matches the GitHub token pattern" in output
    )
    assert hooked_repo.head() == before
