#!/usr/bin/env python3
"""Tests for worktree_setup.sh. Stdlib-only (unittest).

Run: python3 -m unittest discover -s scripts/tests -p 'test_*.py'
     (from the shipping-issues skill directory)

worktree_setup.sh never calls `gh` (it only touches git and the local
filesystem), so these tests don't use FakeGh — they drive real, disposable
git repos under tempfile.TemporaryDirectory() instead.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


SCRIPT = Path(__file__).resolve().parent.parent / "worktree_setup.sh"


def git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )


def make_repo(path):
    git(path, "init", "-q")
    git(path, "config", "user.email", "tests@example.invalid")
    git(path, "config", "user.name", "shipping-issues tests")
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-qm", "fixture")
    git(path, "branch", "-M", "main")


def write_stub(
    bin_dir: Path,
    name: str,
    record_path: Path,
    *,
    exit_code: int = 0,
    append: bool = False,
) -> None:
    """Install a fake executable on `bin_dir` that records its argv and cwd
    (one per line) to `record_path`, then exits with `exit_code`. With
    `append`, the stub records `<name> <argv>` and adds to the file, so stubs
    sharing one record show the order they ran in."""
    stub = bin_dir / name
    argv = f"{name} $*" if append else "$*"
    redirect = ">>" if append else ">"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf \'%s\\n\' "{argv}" {redirect} "{record_path}"\n'
        f'pwd >> "{record_path}"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def commit_files(repo: Path, *names: str) -> None:
    """Commit a fixture file for each name, so a new worktree checks it out."""
    for name in names:
        (repo / name).write_text("fixture\n", encoding="utf-8")
    git(repo, "add", *names)
    git(repo, "commit", "-qm", "add " + " ".join(names))


def issue_args(issue: str, root: Path) -> list:
    return [
        "--issue",
        issue,
        "--branch",
        "feat/" + issue,
        "--base",
        "main",
        "--root",
        str(root),
    ]


def deps_lines(stdout: str) -> list:
    return [ln for ln in stdout.splitlines() if ln.startswith("deps: ")]


# Every external command worktree_setup.sh runs on its create-and-install path
# (git, the coreutils its helpers call, and the shells), linked by name.
SCRIPT_TOOLS = (
    "bash",
    "sh",
    "env",
    "git",
    "dirname",
    "basename",
    "mktemp",
    "mkdir",
    "rm",
    "tail",
    "sed",
    "grep",
)


def tools_only_path(bin_dir: Path) -> Path:
    """Fill `bin_dir` with a symlink to each of SCRIPT_TOOLS, resolved on the
    real PATH, and return it: a PATH holding no other command."""
    for name in SCRIPT_TOOLS:
        target = shutil.which(name)
        if target is None:
            raise AssertionError("the test host has no " + name + " on PATH")
        (bin_dir / name).symlink_to(target)
    return bin_dir


def run_script(args, cwd, *, extra_path: str | None = None):
    env = dict(os.environ)
    if extra_path:
        env["PATH"] = f"{extra_path}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )


class WorktreeSetupTest(unittest.TestCase):
    def test_help_flag_prints_own_usage(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            make_repo(repo)
            for flag in ("-h", "--help"):
                with self.subTest(flag=flag):
                    proc = run_script([flag], repo)

                    self.assertEqual(proc.returncode, 0)
                    self.assertIn(
                        "worktree_setup.sh — Turn a bare `git worktree`",
                        proc.stdout,
                    )
                    self.assertIn("Exit codes:", proc.stdout)

    def test_creates_worktree_on_requested_branch_from_base(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"

            proc = run_script(
                [
                    "--issue",
                    "42",
                    "--branch",
                    "feat/42",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
            )

            wt = root / "42"
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(wt.is_dir())
            branch = git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            wt_head = git(wt, "rev-parse", "HEAD").stdout.strip()
            main_head = git(repo, "rev-parse", "main").stdout.strip()

        self.assertEqual(branch, "feat/42")
        self.assertEqual(wt_head, main_head)
        self.assertIn(f"worktree: {wt}\n", proc.stdout)
        self.assertIn("result: CREATED\n", proc.stdout)
        self.assertIn("verdict: READY\n", proc.stdout)

    def test_main_checkout_stays_clean(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"

            before = git(repo, "status", "--porcelain").stdout
            proc = run_script(
                [
                    "--issue",
                    "1",
                    "--branch",
                    "feat/1",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
            )
            after = git(repo, "status", "--porcelain").stdout

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(before, "")
        self.assertEqual(
            after, "", "worktree_setup.sh must never dirty the main checkout"
        )

    def test_copies_no_secret_or_permission_file(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            secret_shaped = [
                ".env",
                ".env.local",
                ".envrc",
                "app.local",
                ".dev.vars",
                "local.settings.json",
                ".claude/settings.local.json",
            ]
            for rel in secret_shaped:
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text("X=1\n", encoding="utf-8")
            root = td / "worktrees"

            proc = run_script(
                [
                    "--issue",
                    "9",
                    "--branch",
                    "feat/9",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
            )
            wt = root / "9"
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for rel in secret_shaped:
                self.assertFalse((wt / rel).exists(), f"{rel} must not be copied")

        self.assertNotIn("copied:", proc.stdout)

    def test_reentry_against_existing_worktree_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"
            args = [
                "--issue",
                "5",
                "--branch",
                "feat/5",
                "--base",
                "main",
                "--root",
                str(root),
            ]

            first = run_script(args, repo)
            second = run_script(args, repo)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("result: EXISTS\n", second.stdout)
        self.assertIn("verdict: READY\n", second.stdout)

    def test_path_exists_but_is_not_a_registered_worktree_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"
            (root / "6").mkdir(parents=True)

            proc = run_script(
                [
                    "--issue",
                    "6",
                    "--branch",
                    "feat/6",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
            )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("verdict: BLOCKED\n", proc.stdout)

    def test_dependency_install_runs_uv_sync_locked_in_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
            git(repo, "add", "uv.lock")
            git(repo, "commit", "-qm", "add uv lockfile")
            # An untracked virtualenv in the main checkout: absolute paths in
            # pyvenv.cfg make a copy of it a broken one.
            (repo / ".venv").mkdir()
            (repo / ".venv" / "pyvenv.cfg").write_text("home = /x\n", encoding="utf-8")
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            record = td / "uv-call.txt"
            write_stub(bin_dir, "uv", record, exit_code=0)

            proc = run_script(
                [
                    "--issue",
                    "3",
                    "--branch",
                    "feat/3",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
                extra_path=str(bin_dir),
            )
            wt = root / "3"
            recorded = record.read_text(encoding="utf-8").splitlines()
            venv_copied = (wt / ".venv").exists()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(recorded[0], "sync --all-groups --locked")
        self.assertEqual(recorded[1], str(wt))
        self.assertIn("deps: uv sync --all-groups --locked\n", proc.stdout)
        self.assertFalse(venv_copied, ".venv must be re-created, never copied")

    def test_install_command_failure_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
            git(repo, "add", "uv.lock")
            git(repo, "commit", "-qm", "add uv lockfile")
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            record = td / "uv-call.txt"
            write_stub(bin_dir, "uv", record, exit_code=7)

            proc = run_script(
                [
                    "--issue",
                    "4",
                    "--branch",
                    "feat/4",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
                extra_path=str(bin_dir),
            )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("verdict: BLOCKED\n", proc.stdout)
        self.assertIn("exit=7", proc.stdout)

    # --- JavaScript dependencies (pnpm-lock.yaml) ---------------------------

    def test_pnpm_lockfile_installs_after_uv_in_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            commit_files(repo, "uv.lock", "pnpm-lock.yaml")
            # An untracked node_modules in the main checkout: pnpm links it into
            # its store and node_modules/.pnpm, so a copy points at the wrong tree.
            (repo / "node_modules" / ".pnpm").mkdir(parents=True)
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            record = td / "calls.txt"
            write_stub(bin_dir, "uv", record, append=True)
            write_stub(bin_dir, "pnpm", record, append=True)

            proc = run_script(issue_args("7", root), repo, extra_path=str(bin_dir))
            wt = root / "7"
            recorded = record.read_text(encoding="utf-8").splitlines()
            node_modules_copied = (wt / "node_modules").exists()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            recorded,
            [
                "uv sync --all-groups --locked",
                str(wt),
                "pnpm install --frozen-lockfile",
                str(wt),
            ],
        )
        self.assertEqual(
            deps_lines(proc.stdout),
            [
                "deps: uv sync --all-groups --locked",
                "deps: pnpm install --frozen-lockfile",
            ],
        )
        self.assertIn("verdict: READY\n", proc.stdout)
        self.assertFalse(
            node_modules_copied, "node_modules must be re-created, never copied"
        )

    def test_pnpm_install_failure_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            commit_files(repo, "uv.lock", "pnpm-lock.yaml")
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            write_stub(bin_dir, "uv", td / "uv-call.txt")
            write_stub(bin_dir, "pnpm", td / "pnpm-call.txt", exit_code=7)

            proc = run_script(issue_args("8", root), repo, extra_path=str(bin_dir))

        self.assertEqual(proc.returncode, 1)
        self.assertEqual(
            deps_lines(proc.stdout),
            [
                "deps: uv sync --all-groups --locked",
                "deps: FAILED: pnpm install --frozen-lockfile (exit=7)",
            ],
        )
        self.assertIn("verdict: BLOCKED\n", proc.stdout)

    def test_uv_failure_blocks_before_the_pnpm_install(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            commit_files(repo, "uv.lock", "pnpm-lock.yaml")
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            pnpm_record = td / "pnpm-call.txt"
            write_stub(bin_dir, "uv", td / "uv-call.txt", exit_code=5)
            write_stub(bin_dir, "pnpm", pnpm_record)

            proc = run_script(issue_args("9", root), repo, extra_path=str(bin_dir))
            pnpm_ran = pnpm_record.exists()

        self.assertEqual(proc.returncode, 1)
        self.assertEqual(
            deps_lines(proc.stdout),
            ["deps: FAILED: uv sync --all-groups --locked (exit=5)"],
        )
        self.assertIn("verdict: BLOCKED\n", proc.stdout)
        self.assertFalse(pnpm_ran)

    def test_missing_pnpm_blocks_with_exit_127(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            commit_files(repo, "pnpm-lock.yaml")
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            env = dict(os.environ)
            # PATH is one directory of links to the tools the script calls and
            # nothing else, so no pnpm the host has (a version manager's, a
            # corepack shim in /usr/bin) is reachable.
            env["PATH"] = str(tools_only_path(bin_dir))

            proc = subprocess.run(
                [shutil.which("bash") or "/bin/bash", str(SCRIPT)]
                + issue_args("10", root),
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
            )

        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("result: CREATED\n", proc.stdout)
        self.assertEqual(
            deps_lines(proc.stdout),
            ["deps: FAILED: pnpm install --frozen-lockfile (exit=127)"],
        )
        self.assertIn("verdict: BLOCKED\n", proc.stdout)

    def test_no_pnpm_lockfile_runs_no_pnpm_command(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            commit_files(repo, "uv.lock")
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            pnpm_record = td / "pnpm-call.txt"
            write_stub(bin_dir, "uv", td / "uv-call.txt")
            write_stub(bin_dir, "pnpm", pnpm_record)

            proc = run_script(issue_args("11", root), repo, extra_path=str(bin_dir))
            pnpm_ran = pnpm_record.exists()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            deps_lines(proc.stdout), ["deps: uv sync --all-groups --locked"]
        )
        self.assertNotIn("pnpm", proc.stdout)
        self.assertFalse(pnpm_ran)

    def test_pnpm_lockfile_without_uv_lockfile_runs_only_pnpm(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            commit_files(repo, "pnpm-lock.yaml")
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            record = td / "calls.txt"
            write_stub(bin_dir, "uv", record, append=True)
            write_stub(bin_dir, "pnpm", record, append=True)

            proc = run_script(issue_args("12", root), repo, extra_path=str(bin_dir))
            wt = root / "12"
            recorded = record.read_text(encoding="utf-8").splitlines()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(recorded, ["pnpm install --frozen-lockfile", str(wt)])
        self.assertEqual(
            deps_lines(proc.stdout), ["deps: pnpm install --frozen-lockfile"]
        )

    def test_other_javascript_lockfiles_select_nothing(self):
        for lockfile in ("package-lock.json", "yarn.lock", "bun.lock"):
            with self.subTest(lockfile=lockfile), tempfile.TemporaryDirectory() as td:
                td = Path(td)
                repo = td / "repo"
                repo.mkdir()
                make_repo(repo)
                commit_files(repo, lockfile)
                root = td / "worktrees"
                bin_dir = td / "bin"
                bin_dir.mkdir()
                record = td / "calls.txt"
                write_stub(bin_dir, "uv", record, append=True)
                write_stub(bin_dir, "pnpm", record, append=True)

                proc = run_script(issue_args("13", root), repo, extra_path=str(bin_dir))
                anything_ran = record.exists()

                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(deps_lines(proc.stdout), ["deps: none"])
                self.assertFalse(anything_ran)

    def test_dry_run_prints_the_pnpm_install_and_runs_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            commit_files(repo, "uv.lock", "pnpm-lock.yaml")
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            record = td / "calls.txt"
            write_stub(bin_dir, "uv", record, append=True)
            write_stub(bin_dir, "pnpm", record, append=True)

            proc = run_script(
                [*issue_args("14", root), "--dry-run"],
                repo,
                extra_path=str(bin_dir),
            )
            wt = root / "14"
            anything_ran = record.exists()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        dry = [ln for ln in proc.stdout.splitlines() if ln.startswith("DRY: (cd ")]
        self.assertEqual(
            dry,
            [
                f"DRY: (cd {wt} && uv sync --all-groups --locked)",
                f"DRY: (cd {wt} && pnpm install --frozen-lockfile)",
            ],
        )
        self.assertFalse(anything_ran)

    # --- lockfiles come from the target tree, not the main checkout ---------

    def _repo_with_lockfiles_only_on_branch(self, repo: Path) -> None:
        """main lacks both lockfiles; branch `next` adds them. The main checkout
        stays on main, so its working tree has neither file."""
        make_repo(repo)
        git(repo, "checkout", "-qb", "next")
        commit_files(repo, "uv.lock", "pnpm-lock.yaml")
        git(repo, "checkout", "-q", "main")

    def _repo_with_lockfiles_only_in_main_checkout(self, repo: Path) -> None:
        """main's tip (checked out) has both lockfiles; main~1 has neither."""
        make_repo(repo)
        commit_files(repo, "uv.lock", "pnpm-lock.yaml")

    def test_lockfiles_on_base_but_not_in_main_checkout_are_installed(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            self._repo_with_lockfiles_only_on_branch(repo)
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            record = td / "calls.txt"
            write_stub(bin_dir, "uv", record, append=True)
            write_stub(bin_dir, "pnpm", record, append=True)
            args = issue_args("15", root)
            args[args.index("--base") + 1] = "next"

            proc = run_script(args, repo, extra_path=str(bin_dir))
            main_checkout_has_lockfile = (repo / "pnpm-lock.yaml").exists()

        self.assertFalse(main_checkout_has_lockfile)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            deps_lines(proc.stdout),
            [
                "deps: uv sync --all-groups --locked",
                "deps: pnpm install --frozen-lockfile",
            ],
        )

    def test_lockfiles_in_main_checkout_but_not_on_base_are_not_installed(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            self._repo_with_lockfiles_only_in_main_checkout(repo)
            root = td / "worktrees"
            bin_dir = td / "bin"
            bin_dir.mkdir()
            record = td / "calls.txt"
            write_stub(bin_dir, "uv", record, append=True)
            write_stub(bin_dir, "pnpm", record, append=True)
            args = issue_args("16", root)
            args[args.index("--base") + 1] = "main~1"

            proc = run_script(args, repo, extra_path=str(bin_dir))
            anything_ran = record.exists()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(deps_lines(proc.stdout), ["deps: none"])
        self.assertFalse(anything_ran)

    def test_dry_run_reads_lockfiles_from_the_base_ref(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            self._repo_with_lockfiles_only_on_branch(repo)
            root = td / "worktrees"
            args = issue_args("17", root)
            args[args.index("--base") + 1] = "next"

            proc = run_script([*args, "--dry-run"], repo)
            wt = root / "17"

        self.assertEqual(proc.returncode, 0, proc.stderr)
        dry = [ln for ln in proc.stdout.splitlines() if ln.startswith("DRY: (cd ")]
        self.assertEqual(
            dry,
            [
                f"DRY: (cd {wt} && uv sync --all-groups --locked)",
                f"DRY: (cd {wt} && pnpm install --frozen-lockfile)",
            ],
        )

    def test_dry_run_ignores_lockfiles_the_base_ref_lacks(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            self._repo_with_lockfiles_only_in_main_checkout(repo)
            root = td / "worktrees"
            args = issue_args("18", root)
            args[args.index("--base") + 1] = "main~1"

            proc = run_script([*args, "--dry-run"], repo)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("DRY: (cd ", proc.stdout)
        self.assertIn("DRY: deps: none\n", proc.stdout)

    def test_dry_run_on_an_existing_branch_reads_that_branch(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            self._repo_with_lockfiles_only_on_branch(repo)
            root = td / "worktrees"
            # `--branch next` exists, so the worktree checks it out and --base
            # (main, which has no lockfile) is not what it would contain.
            args = issue_args("19", root)
            args[args.index("--branch") + 1] = "next"

            proc = run_script([*args, "--dry-run"], repo)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("pnpm install --frozen-lockfile)\n", proc.stdout)

    def test_missing_shared_pre_commit_hook_warns_and_installs_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            (repo / ".pre-commit-config.yaml").write_text(
                "repos: []\n", encoding="utf-8"
            )
            git(repo, "add", ".pre-commit-config.yaml")
            git(repo, "commit", "-qm", "add pre-commit config")
            root = td / "worktrees"

            proc = run_script(
                [
                    "--issue",
                    "5",
                    "--branch",
                    "feat/5",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
            )
            hook_written = (repo / ".git" / "hooks" / "pre-commit").exists()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("hooks: MISSING", proc.stdout)
        self.assertIn("just install", proc.stdout)
        self.assertIn("verdict: READY_WITH_WARNINGS\n", proc.stdout)
        self.assertFalse(
            hook_written, "the shared hook is never installed from a worktree"
        )

    def test_installed_shared_pre_commit_hook_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            (repo / ".pre-commit-config.yaml").write_text(
                "repos: []\n", encoding="utf-8"
            )
            git(repo, "add", ".pre-commit-config.yaml")
            git(repo, "commit", "-qm", "add pre-commit config")
            hook = repo / ".git" / "hooks" / "pre-commit"
            hook.write_text(
                "#!/usr/bin/env bash\n# installed by pre-commit\n", encoding="utf-8"
            )
            root = td / "worktrees"

            proc = run_script(
                [
                    "--issue",
                    "6",
                    "--branch",
                    "feat/6",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("hooks: shared pre-commit hook installed\n", proc.stdout)
        self.assertIn("verdict: READY\n", proc.stdout)

    def _repo_expecting_merge_hook(self, td):
        repo = td / "repo"
        repo.mkdir()
        make_repo(repo)
        (repo / ".pre-commit-config.yaml").write_text(
            "default_install_hook_types: [pre-commit, pre-merge-commit]\nrepos: []\n",
            encoding="utf-8",
        )
        git(repo, "add", ".pre-commit-config.yaml")
        git(repo, "commit", "-qm", "add pre-commit config")
        return repo

    def test_missing_pre_merge_commit_hook_the_config_asks_for_warns(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = self._repo_expecting_merge_hook(td)
            hook = repo / ".git" / "hooks" / "pre-commit"
            hook.write_text(
                "#!/usr/bin/env bash\n# installed by pre-commit\n", encoding="utf-8"
            )

            proc = run_script(
                [
                    "--issue",
                    "7",
                    "--branch",
                    "feat/7",
                    "--base",
                    "main",
                    "--root",
                    str(td / "worktrees"),
                ],
                repo,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("hooks: MISSING pre-merge-commit (", proc.stdout)
        self.assertIn("verdict: READY_WITH_WARNINGS\n", proc.stdout)

    def test_both_hooks_the_config_asks_for_installed_is_ready(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = self._repo_expecting_merge_hook(td)
            for name in ("pre-commit", "pre-merge-commit"):
                hook = repo / ".git" / "hooks" / name
                hook.write_text(
                    "#!/usr/bin/env bash\n# installed by pre-commit\n", encoding="utf-8"
                )

            proc = run_script(
                [
                    "--issue",
                    "8",
                    "--branch",
                    "feat/8",
                    "--base",
                    "main",
                    "--root",
                    str(td / "worktrees"),
                ],
                repo,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("hooks: shared pre-commit hook installed\n", proc.stdout)
        self.assertIn("verdict: READY\n", proc.stdout)

    def test_verify_failure_is_a_warning_not_a_blocker(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"
            log = td / "verify-logs" / "10.log"

            proc = run_script(
                [
                    "--issue",
                    "10",
                    "--branch",
                    "feat/10",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                    "--verify",
                    "echo failing-output && exit 1",
                    "--log",
                    str(log),
                ],
                repo,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(log.exists())
            self.assertIn("failing-output", log.read_text(encoding="utf-8"))

        self.assertIn("baseline: FAIL(exit=1)\n", proc.stdout)
        self.assertIn(f"baseline_log: {log}\n", proc.stdout)
        self.assertIn("verdict: READY_WITH_WARNINGS\n", proc.stdout)
        self.assertNotIn(str(repo), str(log))

    def test_dry_run_creates_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"

            proc = run_script(
                [
                    "--issue",
                    "11",
                    "--branch",
                    "feat/11",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                    "--dry-run",
                ],
                repo,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse((root / "11").exists())
            worktree_list = git(repo, "worktree", "list").stdout.strip().splitlines()
            self.assertEqual(len(worktree_list), 1)

        self.assertTrue(
            any(line.startswith("DRY:") for line in proc.stdout.splitlines()),
            proc.stdout,
        )

    def test_resolves_main_checkout_from_inside_another_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            other = td / "other-worktree"
            git(repo, "worktree", "add", str(other), "-b", "other-branch", "main")
            root = td / "worktrees"

            proc = run_script(
                [
                    "--issue",
                    "12",
                    "--branch",
                    "feat/12",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                other,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((root / "12").is_dir())
            # git canonicalizes --git-common-dir (e.g. resolving macOS's
            # /var -> /private/var symlink), so compare against the
            # resolved repo path rather than the literal one this test
            # constructed it from.
            resolved_repo = repo.resolve()

        self.assertIn(f"repo_root: {resolved_repo}\n", proc.stdout)

    # --- batch mode (--spec) -------------------------------------------------

    def test_batch_provisions_two_worktrees_with_per_issue_blocks_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"

            proc = run_script(
                [
                    "--spec",
                    "201:feat/201",
                    "--spec",
                    "202:feat/202",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("=== issue 201 ===\n", proc.stdout)
        self.assertIn("=== issue 202 ===\n", proc.stdout)
        self.assertIn("batch: 2/2 ready\n", proc.stdout)
        self.assertNotIn("blocked:", proc.stdout)
        # per-issue verdict lines appear before the final batch verdict line
        self.assertEqual(
            proc.stdout.count("verdict: READY\n"), 3
        )  # 2 per-issue + 1 summary
        self.assertTrue(proc.stdout.rstrip("\n").endswith("verdict: READY"))

    def test_batch_reports_blocked_spec_in_summary(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"
            # Pre-create an unregistered path at the target location so the
            # second spec's worktree creation is blocked, same as the
            # single-issue "not a registered worktree" test above.
            (root / "302").mkdir(parents=True)

            proc = run_script(
                [
                    "--spec",
                    "301:feat/301",
                    "--spec",
                    "302:feat/302",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
            )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("batch: 1/2 ready\n", proc.stdout)
        self.assertIn("blocked: 302\n", proc.stdout)
        self.assertIn("verdict: BLOCKED\n", proc.stdout)

    def test_spec_and_issue_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"

            proc = run_script(
                [
                    "--spec",
                    "1:feat/1",
                    "--issue",
                    "2",
                    "--branch",
                    "feat/2",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                ],
                repo,
            )

        self.assertEqual(proc.returncode, 2)

    def test_log_with_spec_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"

            proc = run_script(
                [
                    "--spec",
                    "1:feat/1",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                    "--log",
                    str(td / "x.log"),
                ],
                repo,
            )

        self.assertEqual(proc.returncode, 2)

    def test_spec_with_no_colon_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"

            proc = run_script(
                ["--spec", "not-a-spec", "--base", "main", "--root", str(root)],
                repo,
            )

        self.assertEqual(proc.returncode, 2)

    def test_spec_with_non_digit_issue_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"

            proc = run_script(
                ["--spec", "abc:feat/abc", "--base", "main", "--root", str(root)],
                repo,
            )

        self.assertEqual(proc.returncode, 2)

    def test_log_dir_places_per_issue_baseline_logs(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"
            log_dir = td / "logs"

            proc = run_script(
                [
                    "--spec",
                    "401:feat/401",
                    "--spec",
                    "402:feat/402",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                    "--verify",
                    "exit 0",
                    "--log-dir",
                    str(log_dir),
                ],
                repo,
            )

            self.assertTrue((log_dir / "401-baseline.log").exists())
            self.assertTrue((log_dir / "402-baseline.log").exists())

        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_a_red_baseline_is_reported_not_acted_on(self):
        # The script deliberately does NOT decide what a red baseline means or
        # tear anything down: it reports, the caller decides. Every spec is
        # still provisioned, and the worktrees are all still there afterwards.
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"

            proc = run_script(
                [
                    "--spec",
                    "501:feat/501",
                    "--spec",
                    "502:feat/502",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                    "--verify",
                    "exit 1",
                    "--log-dir",
                    str(td / "verify"),
                ],
                repo,
            )
            both_present = (root / "501").exists() and (root / "502").exists()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("=== issue 501 ===\n", proc.stdout)
        self.assertIn("=== issue 502 ===\n", proc.stdout)
        self.assertIn("baseline: FAIL(exit=1)\n", proc.stdout)
        self.assertIn("verdict: READY_WITH_WARNINGS\n", proc.stdout)
        self.assertNotIn("viability:", proc.stdout)
        self.assertTrue(both_present)

    def test_a_hanging_verify_command_is_bounded(self):
        # Nothing about a timeout is a judgement call, so it lives here: a repo
        # whose gate starts a watcher would otherwise hang the script forever
        # with no output at all, since verify output is redirected to the log.
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            root = td / "worktrees"

            proc = run_script(
                [
                    "--issue",
                    "601",
                    "--branch",
                    "feat/601",
                    "--base",
                    "main",
                    "--root",
                    str(root),
                    "--verify",
                    "sleep 30",
                    "--verify-timeout",
                    "1",
                    "--log",
                    str(td / "verify" / "601.log"),
                ],
                repo,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("baseline: TIMEOUT(1s)\n", proc.stdout)
        self.assertIn("verdict: READY_WITH_WARNINGS\n", proc.stdout)

    def test_the_timeout_kills_the_whole_process_tree(self):
        # A gate that forks workers must not leave them running: killing only
        # the `bash -c` wrapper would strand whatever they hold open.
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            marker = td / "still-alive"

            proc = run_script(
                [
                    "--issue",
                    "602",
                    "--branch",
                    "feat/602",
                    "--base",
                    "main",
                    "--root",
                    str(td / "worktrees"),
                    "--verify",
                    f"( sleep 4; touch {marker} ) & wait",
                    "--verify-timeout",
                    "1",
                    "--log",
                    str(td / "verify" / "602.log"),
                ],
                repo,
            )
            time.sleep(6)
            child_survived = marker.exists()

        self.assertIn("baseline: TIMEOUT(1s)\n", proc.stdout)
        self.assertFalse(child_survived, "the forked child outlived the timeout")

    def test_bad_verify_timeout_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = td / "repo"
            repo.mkdir()
            make_repo(repo)
            proc = run_script(
                [
                    "--issue",
                    "1",
                    "--branch",
                    "b",
                    "--base",
                    "main",
                    "--root",
                    str(td / "wt"),
                    "--verify-timeout",
                    "0",
                ],
                repo,
            )
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
