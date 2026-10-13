"""The client drift gate preserves bytes, Git state and temporary-directory cleanup."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "check_generated_client", REPO_ROOT / "scripts" / "check_generated_client.py"
)
assert spec is not None
assert spec.loader is not None
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
spec.loader.exec_module(checker)


@pytest.fixture
def make_root(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    tree = root / "frontend/src/api/generated"
    tree.mkdir(parents=True)
    (tree / "types.gen.ts").write_text("export const value = 1;\n")
    (tree / "client").mkdir()
    (tree / "client/runtime.ts").write_text("// @ts-nocheck\nexport {};\n")
    baseline = tmp_path / "baseline.ts"
    baseline.write_text("export const value = 1;\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pnpm = bin_dir / "pnpm"
    pnpm.write_text(
        '#!/bin/sh\n[ "${FAIL_GENERATOR:-}" != 1 ] || exit 7\n'
        'mkdir -p "$OPENAPI_TS_OUTPUT/client"\n'
        'cp "$GENERATOR_BASELINE" "$OPENAPI_TS_OUTPUT/types.gen.ts"\n'
        'printf "// @ts-nocheck\\nexport {};\\n" > "$OPENAPI_TS_OUTPUT/client/runtime.ts"\n'
    )
    pnpm.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GENERATOR_BASELINE", str(baseline))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Fixture Author")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Fixture Author")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "fixture@example.test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "fixture@example.test")
    _git(root, "init", "-b", "fixture")
    _git(root, "add", "frontend")
    _git(root, "commit", "-m", "fixture")
    return root


def _git(root, *args):
    git = shutil.which("git")
    assert git is not None
    return subprocess.run(  # noqa: S603 -- only controlled Git fixture arguments.
        [git, *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _snapshot(root):
    files = {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "frontend").rglob("*")
        if path.is_file()
    }
    return files, _git(root, "status", "--porcelain")


def test_generated_client_current_output_passes_without_mutation(make_root):
    before = _snapshot(make_root)

    assert checker.main([], root=make_root) == 0

    assert _snapshot(make_root) == before


@pytest.mark.parametrize("variant", ["stale", "missing", "extra", "generator-failure"])
def test_generated_client_failure_preserves_starting_bytes_and_git_state(
    make_root, monkeypatch, variant, capsys
):
    tree = make_root / "frontend/src/api/generated"
    if variant == "stale":
        (tree / "types.gen.ts").write_text("export const value = 2;\n")
    elif variant == "missing":
        (tree / "types.gen.ts").unlink()
    elif variant == "extra":
        (tree / "extra.ts").write_text("export {};\n")
    else:
        monkeypatch.setenv("FAIL_GENERATOR", "1")
    before = _snapshot(make_root)

    assert checker.main([], root=make_root) == 1

    assert _snapshot(make_root) == before
    assert "just contract" in capsys.readouterr().err


@pytest.mark.parametrize(
    "path",
    [
        "src/routeTree.gen.ts",
        "src/api/generated/types.gen.ts",
        "src/api/generated/@tanstack/react-query.gen.ts",
        "src/page.tsx",
        "tests/page.test.ts",
    ],
)
@pytest.mark.parametrize(
    "comment",
    [
        "// @ts-nocheck",
        "/* @ts-nocheck */",
        "// @TS-NOCHECK",
        "//\u00a0@ts-nocheck",
        "// @ts-ignore",
        "/* @ts-ignore */",
        "// @ts-expect-error",
        "// @TS-EXPECT-ERROR",
    ],
)
def test_typecheck_policy_forbidden_directive_fails_naming_file(
    make_root, path, comment, capsys
):
    target = make_root / "frontend" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{comment}\nexport {{}};\n")

    assert checker.main(["--scope-only"], root=make_root) == 1

    assert path in capsys.readouterr().err


def test_typecheck_policy_approved_runtime_passes_without_generator(
    make_root, monkeypatch
):
    monkeypatch.setenv("FAIL_GENERATOR", "1")
    target = make_root / "frontend/src/api/generated/core/runtime.ts"
    target.parent.mkdir()
    target.write_text("// @ts-nocheck\nexport {};\n")

    assert checker.main(["--scope-only"], root=make_root) == 0


@pytest.mark.parametrize("directive", ["@ts-ignore", "@ts-expect-error"])
def test_typecheck_policy_runtime_unapproved_suppression_fails(make_root, directive):
    target = make_root / "frontend/src/api/generated/client/runtime.ts"
    target.write_text(f"// {directive}\nexport {{}};\n")

    assert checker.main(["--scope-only"], root=make_root) == 1


@pytest.mark.parametrize("fail", [False, True])
def test_generated_client_temporary_output_removed_on_every_exit(
    make_root, monkeypatch, fail
):
    created = []

    def temporary_directory(**kwargs):
        instance = tempfile.TemporaryDirectory(**kwargs)
        created.append(Path(instance.name))
        return instance

    monkeypatch.setattr(
        checker, "TemporaryDirectory", temporary_directory, raising=False
    )
    monkeypatch.setenv("FAIL_GENERATOR", "1" if fail else "0")

    assert checker.main([], root=make_root) == int(fail)

    assert len(created) == 1
    assert not created[0].exists()


def test_typecheck_policy_validates_fresh_generator_output(
    make_root, monkeypatch, capsys
):
    Path(os.environ["GENERATOR_BASELINE"]).write_text("// @ts-nocheck\nexport {};\n")
    before = _snapshot(make_root)

    assert checker.main([], root=make_root) == 1

    assert "types.gen.ts" in capsys.readouterr().err
    assert _snapshot(make_root) == before


def test_contract_recipe_stale_json_stops_before_generation_without_mutation(make_root):
    match = re.search(
        r"\ncontract-check:\n((?:    [^\n]+\n)+)",
        (REPO_ROOT / "justfile").read_text(),
    )
    assert match is not None
    (make_root / "justfile").write_text("contract-check:\n" + match[1])
    (make_root / "frontend/openapi.json").write_text('{"stale": true}\n')
    uv = Path(os.environ["PATH"].split(os.pathsep)[0]) / "uv"
    marker = make_root.parent / "checker-invoked"
    uv.write_text(
        '#!/bin/sh\nif [ "$3" = --directory ]; then\n'
        '  echo "stale JSON; run just contract" >&2\n  exit 1\nfi\n'
        f'touch "{marker}"\nexit 99\n'
    )
    uv.chmod(0o755)
    just = shutil.which("just")
    assert just is not None
    before = _snapshot(make_root)

    result = subprocess.run(  # noqa: S603 -- fixed local recipe in an isolated fixture.
        [just, "contract-check"],
        cwd=make_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "stale JSON" in result.stderr
    assert not marker.exists()
    assert _snapshot(make_root) == before
