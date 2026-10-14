"""Tests for the pre-commit hooks that run Biome and ``tsc`` on frontend and e2e files.

Each test copies the four real hook definitions from ``.pre-commit-config.yaml``
into a throwaway repository and runs them through pre-commit itself, so file
selection (``files``, ``types_or``, ``pass_filenames``) and the ``entry`` are
the real ones. A fake ``pnpm`` on ``PATH`` stands in for ``pnpm exec``: it
appends its working directory and argv to ``FAKE_RECORD`` as one JSON line
and exits ``FAKE_PNPM_EXIT``, so CI needs no Node.js. That the real Biome and
``tsc`` refuse a bad file is the pull request's manual check.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.harness._yaml import as_mapping, load_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
HOOK_IDS = ("biome", "tsc")
E2E_HOOK_IDS = ("biome-e2e", "tsc-e2e")

FAKE_PNPM = f"""\
#!{sys.executable}
import json, os, sys
with open(os.environ["FAKE_RECORD"], "a", encoding="utf-8") as record:
    record.write(json.dumps({{"cwd": os.getcwd(), "argv": sys.argv[1:]}}) + "\\n")
sys.exit(int(os.environ.get("FAKE_PNPM_EXIT", "0")))
"""

# Files the throwaway repository tracks, and which of them each hook selects.
TRACKED = (
    "README.md",
    "backend/app.ts",
    "frontend/index.html",
    "frontend/AGENTS.md",
    "frontend/package.json",
    "frontend/src/App.tsx",
    "frontend/src/main.ts",
    "frontend/src/my file.ts",
    "frontend/src/legacy.js",
    "frontend/src/Legacy.jsx",
    "frontend/src/index.css",
    "e2e/package.json",
    "e2e/playwright.config.ts",
    "e2e/tests/my spec.spec.ts",
    "e2e/verify_persistence.py",
)
BIOME_FILES = {
    "package.json",
    "src/App.tsx",
    "src/main.ts",
    "src/my file.ts",
    "src/legacy.js",
    "src/Legacy.jsx",
    "src/index.css",
}


def _hooks() -> dict[str, dict[str, object]]:
    config = as_mapping(load_yaml(CONFIG), str(CONFIG))
    repos = config["repos"]
    assert isinstance(repos, list)
    return {
        str(hook["id"]): hook
        for repo in repos
        if repo["repo"] == "local"
        for hook in repo["hooks"]
        if hook["id"] in HOOK_IDS + E2E_HOOK_IDS
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Return a repository tracking `TRACKED`, configured with the four hooks."""
    root = tmp_path / "repo"
    root.mkdir()
    for relative in TRACKED:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    hooks = _hooks()
    # JSON is valid YAML, so no YAML writer is needed.
    (root / ".pre-commit-config.yaml").write_text(
        json.dumps({"repos": [{"repo": "local", "hooks": list(hooks.values())}]}),
        encoding="utf-8",
    )
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "add", "--all")
    return root


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- a fixed git argv, no shell
        ["git", *args],  # noqa: S607 -- git resolved from PATH, as a shell would
        cwd=root,
        env=_base_env(root.parent),
        check=True,
        capture_output=True,
    )


def _base_env(tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        PRE_COMMIT_HOME=str(tmp_path / "pre-commit-home"),
        FAKE_RECORD=str(tmp_path / "pnpm-calls.jsonl"),
    )
    env.pop("PRE_COMMIT", None)
    return env


def _fake_pnpm_dir(tmp_path: Path) -> Path:
    bindir = tmp_path / "pnpm-bin"
    bindir.mkdir(exist_ok=True)
    pnpm = bindir / "pnpm"
    pnpm.write_text(FAKE_PNPM, encoding="utf-8")
    pnpm.chmod(0o755)
    return bindir


def _tools_without_pnpm(tmp_path: Path) -> Path:
    """Link what pre-commit and the entries need into a PATH holding no pnpm."""
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    for name in ("bash", "git"):
        found = shutil.which(name)
        assert found is not None, f"{name} is not on PATH"
        (tools / name).symlink_to(found)
    return tools


def _run(
    root: Path, *args: str, pnpm_exit: int = 0, with_pnpm: bool = True
) -> subprocess.CompletedProcess[str]:
    tmp_path = root.parent
    env = _base_env(tmp_path)
    env["PATH"] = (
        f"{_fake_pnpm_dir(tmp_path)}{os.pathsep}{env['PATH']}"
        if with_pnpm
        else str(_tools_without_pnpm(tmp_path))
    )
    env["FAKE_PNPM_EXIT"] = str(pnpm_exit)
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, "-m", "pre_commit", "run", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _calls(root: Path) -> list[dict[str, object]]:
    record = root.parent / "pnpm-calls.jsonl"
    if not record.exists():
        return []
    lines = record.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_frontend_hooks_config_pins_selection_and_entry() -> None:
    hooks = _hooks()

    assert hooks == {
        "biome": {
            "id": "biome",
            "name": "biome (frontend)",
            "entry": (
                "bash -c 'cd frontend && exec pnpm exec biome check"
                " --no-errors-on-unmatched --files-ignore-unknown=true"
                ' "${@#frontend/}"\' --'
            ),
            "language": "system",
            "files": "^frontend/",
            "types_or": ["ts", "tsx", "javascript", "jsx", "json", "css"],
            "require_serial": True,
            "stages": ["pre-commit"],
        },
        "tsc": {
            "id": "tsc",
            "name": "tsc --noEmit (frontend)",
            "entry": "bash -c 'cd frontend && exec pnpm exec tsc --noEmit' --",
            "language": "system",
            "files": "^frontend/",
            "types_or": ["ts", "tsx"],
            "pass_filenames": False,
            "stages": ["pre-commit"],
        },
        "biome-e2e": {
            "id": "biome-e2e",
            "name": "biome (e2e)",
            "entry": (
                "bash -c 'cd e2e && exec pnpm exec biome check"
                " --no-errors-on-unmatched --files-ignore-unknown=true"
                ' "${@#e2e/}"\' --'
            ),
            "language": "system",
            "files": "^e2e/",
            "types_or": ["ts", "tsx", "javascript", "jsx", "json", "css"],
            "require_serial": True,
            "stages": ["pre-commit"],
        },
        "tsc-e2e": {
            "id": "tsc-e2e",
            "name": "tsc --noEmit (e2e)",
            "entry": "bash -c 'cd e2e && exec pnpm exec tsc --noEmit' --",
            "language": "system",
            "files": "^e2e/",
            "types_or": ["ts", "tsx"],
            "pass_filenames": False,
            "stages": ["pre-commit"],
        },
    }


def test_biome_hook_all_files_checks_frontend_files_from_frontend(
    repo: Path,
) -> None:
    result = _run(repo, "biome", "--all-files")

    assert result.returncode == 0, result.stdout + result.stderr
    (call,) = _calls(repo)
    argv = call["argv"]
    assert isinstance(argv, list)
    assert Path(str(call["cwd"])).resolve() == (repo / "frontend").resolve()
    assert argv[:5] == [
        "exec",
        "biome",
        "check",
        "--no-errors-on-unmatched",
        "--files-ignore-unknown=true",
    ]
    assert set(argv[5:]) == BIOME_FILES
    assert len(argv[5:]) == len(BIOME_FILES)


def test_biome_hook_path_with_space_is_one_argument(repo: Path) -> None:
    result = _run(repo, "biome", "--files", "frontend/src/my file.ts")

    assert result.returncode == 0, result.stdout + result.stderr
    (call,) = _calls(repo)
    assert call["argv"] == [
        "exec",
        "biome",
        "check",
        "--no-errors-on-unmatched",
        "--files-ignore-unknown=true",
        "src/my file.ts",
    ]


def test_tsc_hook_typescript_file_staged_checks_whole_project(repo: Path) -> None:
    result = _run(repo, "tsc", "--files", "frontend/src/App.tsx", "README.md")

    assert result.returncode == 0, result.stdout + result.stderr
    (call,) = _calls(repo)
    assert Path(str(call["cwd"])).resolve() == (repo / "frontend").resolve()
    assert call["argv"] == ["exec", "tsc", "--noEmit"]


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(("README.md", "backend/app.ts"), id="outside-frontend"),
        pytest.param(
            ("frontend/index.html", "frontend/AGENTS.md"), id="frontend-other-types"
        ),
    ],
)
def test_frontend_hooks_no_matching_file_skip_both(
    repo: Path, files: tuple[str, ...]
) -> None:
    result = _run(repo, "--files", *files)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _calls(repo) == []
    assert result.stdout.count("(no files to check)Skipped") == len(
        HOOK_IDS + E2E_HOOK_IDS
    )


def test_tsc_hook_only_non_typescript_frontend_file_skips(repo: Path) -> None:
    result = _run(repo, "tsc", "--files", "frontend/package.json")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _calls(repo) == []
    assert "(no files to check)Skipped" in result.stdout


@pytest.mark.parametrize("hook_id", HOOK_IDS)
def test_frontend_hook_tool_fails_fails_the_hook(repo: Path, hook_id: str) -> None:
    result = _run(repo, hook_id, "--files", "frontend/src/App.tsx", pnpm_exit=1)

    assert result.returncode == 1
    assert "Failed" in result.stdout


@pytest.mark.parametrize("hook_id", HOOK_IDS)
def test_frontend_hook_without_pnpm_fails_with_exit_127(
    repo: Path, hook_id: str
) -> None:
    result = _run(repo, hook_id, "--files", "frontend/src/App.tsx", with_pnpm=False)

    assert result.returncode == 1
    assert "exit code: 127" in result.stdout


def test_biome_e2e_hook_all_files_checks_e2e_files_from_e2e(repo: Path) -> None:
    result = _run(repo, "biome-e2e", "--all-files")

    assert result.returncode == 0, result.stdout + result.stderr
    (call,) = _calls(repo)
    argv = call["argv"]
    assert isinstance(argv, list)
    assert Path(str(call["cwd"])).resolve() == (repo / "e2e").resolve()
    assert argv[:5] == [
        "exec",
        "biome",
        "check",
        "--no-errors-on-unmatched",
        "--files-ignore-unknown=true",
    ]
    assert sorted(argv[5:]) == [
        "package.json",
        "playwright.config.ts",
        "tests/my spec.spec.ts",
    ]


def test_tsc_e2e_hook_typescript_file_staged_checks_e2e_project(repo: Path) -> None:
    result = _run(repo, "tsc-e2e", "--files", "e2e/playwright.config.ts")

    assert result.returncode == 0, result.stdout + result.stderr
    (call,) = _calls(repo)
    assert Path(str(call["cwd"])).resolve() == (repo / "e2e").resolve()
    assert call["argv"] == ["exec", "tsc", "--noEmit"]


def test_e2e_hooks_frontend_file_staged_skip(repo: Path) -> None:
    result = _run(repo, "--files", "frontend/src/App.tsx", pnpm_exit=0)

    assert result.returncode == 0, result.stdout + result.stderr
    assert {Path(str(call["cwd"])).name for call in _calls(repo)} == {"frontend"}


@pytest.mark.parametrize("hook_id", E2E_HOOK_IDS)
def test_e2e_hook_tool_fails_fails_the_hook(repo: Path, hook_id: str) -> None:
    result = _run(repo, hook_id, "--files", "e2e/playwright.config.ts", pnpm_exit=1)

    assert result.returncode == 1
    assert "Failed" in result.stdout
