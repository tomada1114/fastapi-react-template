"""Both pytest configurations turn warnings into failures.

The root ``pyproject.toml`` runs the repository's own tests and
``backend/pyproject.toml`` the app's; each is its own pytest invocation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "pyproject",
    [
        pytest.param(REPO_ROOT / "pyproject.toml", id="root"),
        pytest.param(REPO_ROOT / "backend" / "pyproject.toml", id="backend"),
    ],
)
def test_pytest_config_deprecation_warning_fails_the_run(tmp_path, pyproject):
    test_file = tmp_path / "test_warns.py"
    test_file.write_text(
        "import warnings\n"
        "\n"
        "def test_warns():\n"
        "    warnings.warn('old path', DeprecationWarning, stacklevel=1)\n",
        encoding="utf-8",
    )

    # A fresh interpreter: this run's own filters are already installed.
    result = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter and pytest
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(pyproject),
            "--rootdir",
            str(tmp_path),
            "-p",
            "no:cacheprovider",
            str(test_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "DeprecationWarning: old path" in result.stdout
