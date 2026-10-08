"""The pytest configuration in pyproject.toml turns warnings into failures."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_pytest_config_deprecation_warning_fails_the_run(tmp_path):
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
            str(PYPROJECT),
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
