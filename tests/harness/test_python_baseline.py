"""Keep local tools, the devcontainer and project CI on one Python baseline."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from tests.harness._workflows import jobs, read_workflow, steps, workflow_files
from tests.harness._yaml import as_mapping, block_text, scalar

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_PYPROJECT = "pyproject.toml"
BACKEND_PYPROJECT = "backend/pyproject.toml"
# The fixtures' two configuration files, on the 3.14 baseline.
ROOT_FIXTURE = '[tool.mypy]\npython_version = "3.14"\n'
BACKEND_FIXTURE = '[project]\nrequires-python = ">=3.14"\nclassifiers = ["Programming Language :: Python :: 3.14"]\n[tool.mypy]\npython_version = "3.14"\n'


def python_baseline_findings(root: Path) -> list[str]:
    """Report conflicting baseline versions while allowing inferred tool targets.

    The floor is the app's: ``requires-python`` and the classifiers live in
    ``backend/pyproject.toml``, the workspace member. Both that file and the
    root workspace configuration state a mypy ``python_version``, and either
    may pin a Ruff ``target-version``.
    """
    configs = {
        relative: tomllib.loads((root / relative).read_text(encoding="utf-8"))
        for relative in (ROOT_PYPROJECT, BACKEND_PYPROJECT)
    }
    project = configs[BACKEND_PYPROJECT]["project"]
    floor = re.fullmatch(r">=(\d+\.\d+)(?:\.0)?", project["requires-python"])
    assert floor is not None, "requires-python must state a readable minimum version"
    expected = floor[1]
    versions = {
        ".python-version": (root / ".python-version")
        .read_text(encoding="utf-8")
        .strip(),
    }
    for relative, config in configs.items():
        versions[f"{relative} mypy"] = config["tool"]["mypy"]["python_version"]
    classifiers = [
        value.rsplit(" :: ", 1)[1]
        for value in project.get("classifiers", [])
        if re.fullmatch(r"Programming Language :: Python :: \d+\.\d+", value)
    ]
    assert classifiers, "project must declare a Python minor-version classifier"
    versions.update(
        {f"classifier {index}": value for index, value in enumerate(classifiers)}
    )
    for relative, config in configs.items():
        target = config.get("tool", {}).get("ruff", {}).get("target-version")
        if target is not None:
            match = re.fullmatch(r"py(\d)(\d+)", target)
            assert match is not None, f"{relative}: Ruff target version is unreadable"
            versions[f"{relative} ruff"] = f"{match[1]}.{match[2]}"
    container = root / ".devcontainer/devcontainer.json"
    if container.is_file():
        image = json.loads(container.read_text(encoding="utf-8"))["image"]
        match = re.search(r"python:(\d+\.\d+)(?:[.-]|$)", image)
        assert match is not None, "devcontainer Python image has no readable version"
        versions["devcontainer"] = match[1]
    versions.update(ci_python_versions(root))
    return [
        f"{site}: Python {value} disagrees with requires-python {expected}"
        for site, value in versions.items()
        if value != expected
    ]


def ci_python_versions(root: Path) -> dict[str, str]:
    """Read project interpreter overrides, excluding standalone compatibility runs."""
    versions: dict[str, str] = {}
    for path in workflow_files(root):
        workflow = read_workflow(path)
        scopes = [(f"{path.name}/env", workflow)]
        for job_id, job in jobs(workflow, path).items():
            scopes.append((f"{path.name}/{job_id}/env", job))
            for index, step in enumerate(steps(job, path)):
                site = f"{path.name}/{job_id}/{index}"
                scopes.append((f"{site}/env", step))
                uses = scalar(step.get("uses", ""))
                if uses.startswith(("astral-sh/setup-uv@", "actions/setup-python@")):
                    inputs = as_mapping(step.get("with", {}), f"{path}: steps.with")
                    if "python-version" in inputs:
                        versions[site] = scalar(inputs["python-version"])
                if "run" in step:
                    for line_index, line in enumerate(
                        block_text(step["run"]).splitlines()
                    ):
                        if "--no-project" in line:
                            continue
                        if re.search(r"\buv\s+(?:run|sync|venv|python)\b", line):
                            match = re.search(
                                r"--python(?:=|\s+)([\"']?)([^\s\"']+)\1", line
                            )
                            if match:
                                versions[f"{site}/run/{line_index}"] = match[2]
        for site, scope in scopes:
            env = as_mapping(scope.get("env", {}), f"{path}: env")
            if "UV_PYTHON" in env:
                versions[site] = scalar(env["UV_PYTHON"])
    return versions


def test_python_baseline_repository_versions_agree() -> None:
    assert python_baseline_findings(REPO_ROOT) == []


def test_python_baseline_matching_fixture_passes(tmp_path: Path) -> None:
    files = {
        ".python-version": "3.14\n",
        ROOT_PYPROJECT: ROOT_FIXTURE + '[tool.ruff]\ntarget-version = "py314"\n',
        BACKEND_PYPROJECT: BACKEND_FIXTURE,
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert python_baseline_findings(tmp_path) == []


@pytest.mark.parametrize(
    "site",
    [
        "interpreter",
        "floor",
        "classifier",
        "mypy",
        "root-mypy",
        "container",
        "ruff",
        "backend-ruff",
        "ci",
    ],
)
def test_python_baseline_mismatched_version_is_rejected(
    tmp_path: Path, site: str
) -> None:
    files = {
        ".python-version": "3.14\n",
        ROOT_PYPROJECT: ROOT_FIXTURE,
        BACKEND_PYPROJECT: BACKEND_FIXTURE,
        ".devcontainer/devcontainer.json": '{"image":"mcr.microsoft.com/devcontainers/python:3.14"}',
        ".github/workflows/ci.yml": "jobs:\n  lint:\n    steps:\n      - uses: astral-sh/setup-uv@pin\n",
    }
    if site == "interpreter":
        files[".python-version"] = "3.13\n"
    elif site in {"floor", "classifier", "mypy"}:
        old = {
            "floor": ">=3.14",
            "classifier": "Python :: 3.14",
            "mypy": 'python_version = "3.14"',
        }[site]
        files[BACKEND_PYPROJECT] = files[BACKEND_PYPROJECT].replace(
            old, old.replace("3.14", "3.13")
        )
    elif site == "root-mypy":
        files[ROOT_PYPROJECT] = files[ROOT_PYPROJECT].replace("3.14", "3.13")
    elif site == "container":
        files[".devcontainer/devcontainer.json"] = files[
            ".devcontainer/devcontainer.json"
        ].replace("3.14", "3.13")
    elif site == "ruff":
        files[ROOT_PYPROJECT] += '[tool.ruff]\ntarget-version = "py313"\n'
    elif site == "backend-ruff":
        files[BACKEND_PYPROJECT] += '[tool.ruff]\ntarget-version = "py313"\n'
    else:
        files[".github/workflows/ci.yml"] += (
            '        with:\n          python-version: "3.13"\n'
        )
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert python_baseline_findings(tmp_path)


@pytest.mark.parametrize(
    "override",
    [
        "env:\n  UV_PYTHON: '3.13'\n",
        "jobs:\n  lint:\n    env:\n      UV_PYTHON: '3.13'\n    steps:\n      - run: echo fixture\n",
        "jobs:\n  lint:\n    steps:\n      - run: uv sync --python 3.13\n",
        "jobs:\n  lint:\n    steps:\n      - run: uv run --python=3.13 pytest\n",
        "jobs:\n  lint:\n    steps:\n      - run: uv sync\n        env:\n          UV_PYTHON: '3.13'\n",
    ],
)
def test_python_baseline_project_interpreter_override_is_rejected(
    tmp_path: Path, override: str
) -> None:
    files = {
        ".python-version": "3.14\n",
        ROOT_PYPROJECT: ROOT_FIXTURE,
        BACKEND_PYPROJECT: BACKEND_FIXTURE,
        ".github/workflows/ci.yml": override
        if override.startswith("jobs:")
        else override + "jobs: {}\n",
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert python_baseline_findings(tmp_path)
