"""(h) The Dependabot ``uv`` cooldown equals the ``exclude-newer`` window.

``.github/dependabot.yml``'s ``uv`` update sets ``cooldown.default-days`` and
``pyproject.toml``'s ``[tool.uv] exclude-newer`` is a relative window
(``"14 days"`` or ``"P14D"``). uv's Dependabot guide recommends the two be
equal: a shorter cooldown proposes versions ``uv lock`` refuses, a longer one
leaves the lock behind the window. With no ``uv`` update there is nothing to
pair; with one, a window this check cannot read as a day count fails closed.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.harness._yaml import as_mapping, as_sequence, load_yaml, scalar

if TYPE_CHECKING:
    from collections.abc import Callable

    type MakeRoot = Callable[[dict[str, str]], Path]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT = ".github/dependabot.yml"
PYPROJECT = "pyproject.toml"

_DAYS = re.compile(r"^\s*(?P<days>\d+)\s*days?\s*$|^P(?P<iso>\d+)D$")


def _uv_cooldown_days(root: Path) -> str | None:
    path = root / DEPENDABOT
    if not path.is_file():
        return None
    top = as_mapping(load_yaml(path), str(path))
    for index, item in enumerate(
        as_sequence(top.get("updates", []), f"{path}: updates")
    ):
        update = as_mapping(item, f"{path}: updates[{index}]")
        if scalar(update.get("package-ecosystem", "")) == "uv":
            cooldown = as_mapping(
                update.get("cooldown", {}), f"{path}: updates[{index}].cooldown"
            )
            return scalar(cooldown.get("default-days", ""))
    return None


def cooldown_findings(root: Path) -> list[str]:
    """Return a finding when the uv cooldown and the exclude-newer window differ."""
    cooldown = _uv_cooldown_days(root)
    if cooldown is None:
        return []
    window = (
        tomllib.loads((root / PYPROJECT).read_text(encoding="utf-8"))
        .get("tool", {})
        .get("uv", {})
        .get("exclude-newer")
    )
    match = _DAYS.match(window) if isinstance(window, str) else None
    if match is None:
        return [
            (
                f"{PYPROJECT}: [tool.uv] exclude-newer is {window!r}, not a day count "
                f"({DEPENDABOT}'s uv cooldown must equal it)"
            )
        ]
    days = match["days"] or match["iso"]
    if not cooldown.isdigit() or int(cooldown) != int(days):
        return [
            (
                f"{DEPENDABOT}: the uv cooldown.default-days is {cooldown!r}, but "
                f"{PYPROJECT}'s exclude-newer is {days} days; change both together"
            )
        ]
    return []


def test_uv_cooldown_on_repository_equals_exclude_newer() -> None:
    assert cooldown_findings(REPO_ROOT) == []


DEPENDABOT_TEXT = """\
version: 2
updates:
  - package-ecosystem: "uv"
    cooldown:
      default-days: {days}
"""


@pytest.fixture
def make_root(tmp_path: Path) -> MakeRoot:
    def make(files: dict[str, str]) -> Path:
        for relative, text in files.items():
            (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / relative).write_text(text, encoding="utf-8")
        return tmp_path

    return make


@pytest.mark.parametrize(
    "window",
    [pytest.param("14 days", id="days"), pytest.param("P14D", id="iso")],
)
def test_cooldown_findings_equal_window_passes(
    make_root: MakeRoot, window: str
) -> None:
    root = make_root(
        {
            DEPENDABOT: DEPENDABOT_TEXT.format(days=14),
            PYPROJECT: f'[tool.uv]\nexclude-newer = "{window}"\n',
        }
    )

    assert cooldown_findings(root) == []


def test_cooldown_findings_without_uv_update_passes(make_root: MakeRoot) -> None:
    root = make_root({DEPENDABOT: "version: 2\nupdates:\n  - package-ecosystem: pip\n"})

    assert cooldown_findings(root) == []


def test_cooldown_findings_different_days_fails(make_root: MakeRoot) -> None:
    root = make_root(
        {
            DEPENDABOT: DEPENDABOT_TEXT.format(days=7),
            PYPROJECT: '[tool.uv]\nexclude-newer = "14 days"\n',
        }
    )

    assert cooldown_findings(root) == [
        (
            f"{DEPENDABOT}: the uv cooldown.default-days is '7', but {PYPROJECT}'s "
            "exclude-newer is 14 days; change both together"
        )
    ]


def test_cooldown_findings_absolute_window_fails_closed(make_root: MakeRoot) -> None:
    root = make_root(
        {
            DEPENDABOT: DEPENDABOT_TEXT.format(days=14),
            PYPROJECT: '[tool.uv]\nexclude-newer = "2026-07-21T00:00:00Z"\n',
        }
    )

    assert cooldown_findings(root) == [
        (
            f"{PYPROJECT}: [tool.uv] exclude-newer is '2026-07-21T00:00:00Z', not a day "
            f"count ({DEPENDABOT}'s uv cooldown must equal it)"
        )
    ]
