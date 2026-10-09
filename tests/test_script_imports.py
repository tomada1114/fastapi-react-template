"""Keep repository and skill scripts runnable without third-party packages."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def script_import_findings(root: Path) -> list[str]:
    """Report imports outside the stdlib or a script's own sibling modules."""
    paths = sorted(root.glob("scripts/*.py")) + sorted(
        path
        for path in root.glob(".agents/skills/*/scripts/**/*.py")
        if "tests" not in path.relative_to(root / ".agents/skills").parts[2:]
    )
    findings: list[str] = []
    for path in paths:
        siblings = {sibling.stem for sibling in path.parent.glob("*.py")}
        allowed = sys.stdlib_module_names | {"__future__"} | siblings
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    modules = (
                        [node.module.split(".")[0]]
                        if node.module
                        else [alias.name for alias in node.names]
                    )
                    allowed_roots = siblings if node.level == 1 else set()
                    findings.extend(
                        f"{path.relative_to(root)}:{node.lineno}: {module}"
                        for module in modules
                        if module not in allowed_roots
                    )
                    continue
                modules = [node.module.split(".")[0]] if node.module else []
            else:
                continue
            findings.extend(
                f"{path.relative_to(root)}:{node.lineno}: {module}"
                for module in modules
                if module not in allowed
            )
    return findings


def test_script_imports_repository_uses_only_stdlib_and_siblings() -> None:
    assert script_import_findings(REPO_ROOT) == []


@pytest.mark.parametrize("directory", ["scripts", ".agents/skills/sample/scripts"])
@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import yaml", id="import"),
        pytest.param("from yaml import safe_load", id="from-import"),
        pytest.param("def main():\n    import yaml", id="function-import"),
        pytest.param("if False:\n    import yaml", id="conditional-import"),
        pytest.param("from ..sibling import run", id="relative-escape"),
    ],
)
def test_script_imports_third_party_or_relative_escape_is_rejected(
    tmp_path: Path, directory: str, source: str
) -> None:
    scripts = tmp_path / directory
    scripts.mkdir(parents=True)
    (scripts / "sibling.py").write_text("", encoding="utf-8")
    (scripts / "probe.py").write_text(source, encoding="utf-8")
    assert len(script_import_findings(tmp_path)) == 1


@pytest.mark.parametrize("directory", ["scripts", ".agents/skills/sample/scripts"])
def test_script_imports_stdlib_and_siblings_are_allowed(
    tmp_path: Path, directory: str
) -> None:
    scripts = tmp_path / directory
    scripts.mkdir(parents=True)
    (scripts / "sibling.py").write_text("", encoding="utf-8")
    (scripts / "probe.py").write_text(
        "from __future__ import annotations\nimport json\n"
        "from pathlib import Path\nimport sibling\nfrom sibling import run\n"
        "from .sibling import run\nfrom . import sibling\n",
        encoding="utf-8",
    )
    assert script_import_findings(tmp_path) == []


def test_script_imports_skill_test_dependencies_are_excluded(tmp_path: Path) -> None:
    tests = tmp_path / ".agents/skills/sample/scripts/tests"
    tests.mkdir(parents=True)
    (tests / "test_probe.py").write_text("import yaml", encoding="utf-8")
    assert script_import_findings(tmp_path) == []
