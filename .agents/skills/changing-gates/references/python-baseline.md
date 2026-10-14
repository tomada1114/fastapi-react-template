# Changing the Python baseline

Read when changing the supported Python version of the app or the repository's own
code.

When changing the supported Python floor, update `backend/pyproject.toml`'s
`requires-python` and minor-version classifier, mypy's `python_version` in both
`pyproject.toml` files, the root's Ruff `target-version`, `.python-version`, and the
Python tag in `.devcontainer/devcontainer.json` together. Any other explicit Ruff target
or project CI Python pin must agree too. `tests/harness/test_python_baseline.py`
rejects mismatches; run `just check-harness` after changing the baseline.

The root `pyproject.toml` states Ruff's `target-version` because the virtual workspace
root has no `requires-python` for Ruff to infer it from. CI leaves `setup-uv`'s
`python-version` unset so `uv sync` follows `.python-version`, rather than overriding
it with `UV_PYTHON`. The separate stdlib skill compatibility job still explicitly runs
Python 3.9 with `--no-project`.
