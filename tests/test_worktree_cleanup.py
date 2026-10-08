"""Tests for the explicit, preview-first worktree cleanup command."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import ModuleType

    import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "worktree_cleanup.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("worktree_cleanup", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_preview_is_default_and_forwards_only_named_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    root = tmp_path / "worktrees"
    root.mkdir()
    helper = tmp_path / "cleanup_run.sh"
    helper.write_text("#!/bin/bash\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return subprocess.CompletedProcess(list(command), 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        ["--root", str(root), "--branch", "codex/123-example"],
        cleanup_script=helper,
    )

    assert result == 0
    assert Path(calls[0][0]).name == "git"
    assert calls[0][1:] == ["check-ref-format", "--branch", "codex/123-example"]
    assert Path(calls[1][0]).name == "bash"
    assert calls[1][1:] == [
        str(helper),
        "--worktree-root",
        str(root.resolve()),
        "--merged-only",
        "--branch",
        "codex/123-example",
        "--dry-run",
    ]
    assert "Dry run only" in capsys.readouterr().out


def test_apply_requires_an_explicit_scope_and_omits_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    root = tmp_path / "worktrees"
    root.mkdir()
    helper = tmp_path / "cleanup_run.sh"
    helper.write_text("#!/bin/bash\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return subprocess.CompletedProcess(list(command), 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        ["--root", str(root), "--branch", "codex/123-example", "--apply"],
        cleanup_script=helper,
    )

    assert result == 0
    assert Path(calls[-1][0]).name == "bash"
    assert "--branch" in calls[-1][1:]
    assert "codex/123-example" in calls[-1][1:]
    assert "--dry-run" not in calls[-1][1:]
    assert "Ignored files" in capsys.readouterr().out


def test_missing_root_fails_before_running_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    helper = tmp_path / "cleanup_run.sh"
    helper.write_text("#!/bin/bash\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return subprocess.CompletedProcess(list(command), 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        ["--root", str(tmp_path / "missing"), "--branch", "codex/123-example"],
        cleanup_script=helper,
    )

    assert result == 2
    assert calls == []
    assert "ERR_WORKTREE_ROOT" in capsys.readouterr().err


def test_invalid_branch_fails_before_running_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    root = tmp_path / "worktrees"
    root.mkdir()
    helper = tmp_path / "cleanup_run.sh"
    helper.write_text("#!/bin/bash\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return subprocess.CompletedProcess(list(command), 1, "", "invalid ref")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        ["--root", str(root), "--branch", "bad..branch"],
        cleanup_script=helper,
    )

    assert result == 2
    assert len(calls) == 1
    assert Path(calls[0][0]).name == "git"
    assert calls[0][1:] == ["check-ref-format", "--branch", "bad..branch"]
    assert "ERR_WORKTREE_BRANCH" in capsys.readouterr().err


_FAKE_GH = """#!/bin/sh
case "$*" in
  *"--state merged"*) cat "$FAKE_GH_DIR/merged" ;;
  *"--state open"*) cat "$FAKE_GH_DIR/open" ;;
esac
exit "$(cat "$FAKE_GH_DIR/exit")"
"""


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git argv in a temporary repository
        ["git", *args],  # noqa: S607 - git is resolved from PATH like the script does
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class _Repo:
    """A clone of a local bare origin, a worktree root, and a fake gh."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }.items():
            monkeypatch.setenv(key, value)
        origin = tmp_path / "origin.git"
        _git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(origin))
        self.clone = tmp_path / "clone"
        _git(tmp_path, "clone", "--quiet", str(origin), str(self.clone))
        _git(self.clone, "commit", "--quiet", "--allow-empty", "-m", "init")
        _git(self.clone, "push", "--quiet", "origin", "main")
        self.root = tmp_path / "worktrees"
        self.root.mkdir()
        self.gh_dir = tmp_path / "gh"
        self.gh_dir.mkdir()
        gh = self.gh_dir / "gh"
        gh.write_text(_FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        self.set_gh(merged="", open_="", exit_code=0)
        monkeypatch.setenv("FAKE_GH_DIR", str(self.gh_dir))
        monkeypatch.setenv("PATH", f"{self.gh_dir}{os.pathsep}{os.environ['PATH']}")

    def set_gh(self, *, merged: str, open_: str, exit_code: int) -> None:
        (self.gh_dir / "merged").write_text(merged, encoding="utf-8")
        (self.gh_dir / "open").write_text(open_, encoding="utf-8")
        (self.gh_dir / "exit").write_text(str(exit_code), encoding="utf-8")

    def add_worktree(self, branch: str) -> Path:
        path = self.root / branch.replace("/", "-")
        _git(self.clone, "worktree", "add", "--quiet", "-b", branch, str(path), "main")
        return path

    def clean(self, branch: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixed interpreter and script path
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(self.root),
                "--branch",
                branch,
                "--apply",
            ],
            cwd=self.clone,
            check=False,
            capture_output=True,
            text=True,
        )

    def has_branch(self, branch: str) -> bool:
        return bool(_git(self.clone, "branch", "--list", branch))


def test_apply_fresh_worktree_without_pr_keeps_worktree_and_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _Repo(tmp_path, monkeypatch)
    path = repo.add_worktree("feat/fresh")

    result = repo.clean("feat/fresh")

    assert result.returncode == 0, result.stderr
    assert path.is_dir()
    assert repo.has_branch("feat/fresh")


def test_apply_reused_merged_name_with_new_commit_keeps_worktree_and_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _Repo(tmp_path, monkeypatch)
    path = repo.add_worktree("feat/reused")
    merged_head = _git(path, "rev-parse", "HEAD")
    _git(path, "commit", "--quiet", "--allow-empty", "-m", "new work")
    new_tip = _git(path, "rev-parse", "HEAD")
    repo.set_gh(merged=f"feat/reused\t{merged_head}\n", open_="", exit_code=0)

    result = repo.clean("feat/reused")

    assert result.returncode == 0, result.stderr
    assert path.is_dir()
    assert _git(repo.clone, "rev-parse", "refs/heads/feat/reused") == new_tip
    assert "is not the merged PR's head" in result.stdout


def test_apply_dirty_merged_worktree_keeps_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _Repo(tmp_path, monkeypatch)
    path = repo.add_worktree("feat/dirty")
    head = _git(path, "rev-parse", "HEAD")
    (path / "wip.txt").write_text("unsaved", encoding="utf-8")
    repo.set_gh(merged=f"feat/dirty\t{head}\n", open_="", exit_code=0)

    result = repo.clean("feat/dirty")

    assert result.returncode == 0, result.stderr
    assert (path / "wip.txt").is_file()
    assert repo.has_branch("feat/dirty")


def test_apply_merged_head_removes_worktree_and_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _Repo(tmp_path, monkeypatch)
    path = repo.add_worktree("feat/done")
    head = _git(path, "rev-parse", "HEAD")
    repo.set_gh(merged=f"feat/done\t{head}\n", open_="", exit_code=0)

    result = repo.clean("feat/done")

    assert result.returncode == 0, result.stderr
    assert not path.exists()
    assert not repo.has_branch("feat/done")


def test_apply_failing_gh_fails_without_removing_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _Repo(tmp_path, monkeypatch)
    path = repo.add_worktree("feat/offline")
    head = _git(path, "rev-parse", "HEAD")
    repo.set_gh(merged=f"feat/offline\t{head}\n", open_="", exit_code=1)

    result = repo.clean("feat/offline")

    assert result.returncode != 0
    assert path.is_dir()
    assert repo.has_branch("feat/offline")
