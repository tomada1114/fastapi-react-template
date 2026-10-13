"""(h) The Dependabot cooldowns equal the supply-chain window.

One window holds for the repository (7 days). ``pyproject.toml``'s
``[tool.uv] exclude-newer`` is a relative window (``"7 days"`` or ``"P7D"``),
and ``pnpm-workspace.yaml``'s ``minimumReleaseAge`` an integer count of
minutes (``10080``). ``.github/dependabot.yml``'s ``uv`` update sets
``cooldown.default-days`` equal to the first, as uv's Dependabot guide
recommends, and its ``npm`` update (pnpm's ecosystem) sets it equal to the
second and to the ``uv`` cooldown: a shorter cooldown proposes versions
``uv lock`` or ``pnpm install`` refuses, a longer one leaves the lock behind
the window. With no ``uv`` or ``npm`` update there is nothing to pair for it;
with one, a window this check cannot read fails closed.
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
PNPM_WORKSPACE = "pnpm-workspace.yaml"
MINUTES_PER_DAY = 1440

_DAYS = re.compile(r"^\s*(?P<days>\d+)\s*days?\s*$|^P(?P<iso>\d+)D$")


def _cooldown_days(root: Path, ecosystem: str) -> list[str]:
    """Return the ``cooldown.default-days`` of every update for ``ecosystem``."""
    path = root / DEPENDABOT
    if not path.is_file():
        return []
    top = as_mapping(load_yaml(path), str(path))
    days: list[str] = []
    for index, item in enumerate(
        as_sequence(top.get("updates", []), f"{path}: updates")
    ):
        update = as_mapping(item, f"{path}: updates[{index}]")
        if scalar(update.get("package-ecosystem", "")) == ecosystem:
            cooldown = as_mapping(
                update.get("cooldown", {}), f"{path}: updates[{index}].cooldown"
            )
            days.append(scalar(cooldown.get("default-days", "")))
    return days


def _uv_findings(root: Path, cooldowns: list[str]) -> list[str]:
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
    return [
        (
            f"{DEPENDABOT}: the uv cooldown.default-days is {cooldown!r}, but "
            f"{PYPROJECT}'s exclude-newer is {days} days; change both together"
        )
        for cooldown in cooldowns
        if not cooldown.isdigit() or int(cooldown) != int(days)
    ]


def _minimum_release_age(root: Path) -> int | str:
    """Return pnpm's window in minutes, or a finding when it cannot be read."""
    path = root / PNPM_WORKSPACE
    if not path.is_file():
        return (
            f"{PNPM_WORKSPACE} is missing: {DEPENDABOT}'s npm cooldown must equal "
            "its minimumReleaseAge"
        )
    top = as_mapping(load_yaml(path), str(path))
    if "minimumReleaseAge" not in top:
        return (
            f"{PNPM_WORKSPACE}: no minimumReleaseAge ({DEPENDABOT}'s npm cooldown "
            "must equal it)"
        )
    value = top["minimumReleaseAge"]
    # A YAML `true` loads as a bool, which Python also counts as an int.
    if not isinstance(value, int) or isinstance(value, bool):
        return (
            f"{PNPM_WORKSPACE}: minimumReleaseAge is {value!r}, not an integer count "
            f"of minutes ({DEPENDABOT}'s npm cooldown must equal it)"
        )
    return value


def _npm_findings(root: Path, cooldowns: list[str], uv: list[str]) -> list[str]:
    window = _minimum_release_age(root)
    if isinstance(window, str):
        return [window]
    findings: list[str] = []
    for cooldown in cooldowns:
        if not cooldown.isdigit():
            findings.append(
                f"{DEPENDABOT}: the npm cooldown.default-days is {cooldown!r}, not a "
                f"day count ({PNPM_WORKSPACE}'s minimumReleaseAge is {window})"
            )
            continue
        minutes = int(cooldown) * MINUTES_PER_DAY
        if minutes != window:
            findings.append(
                f"{DEPENDABOT}: the npm cooldown.default-days is {cooldown!r} "
                f"({minutes} minutes), but {PNPM_WORKSPACE}'s minimumReleaseAge is "
                f"{window}; change both together"
            )
        findings.extend(
            (
                f"{DEPENDABOT}: the npm cooldown.default-days is {cooldown!r}, but "
                f"the uv one is {other!r}; one window holds for the repository"
            )
            for other in uv
            if not other.isdigit() or int(other) != int(cooldown)
        )
    return findings


def cooldown_findings(root: Path) -> list[str]:
    """Return a finding for each Dependabot cooldown that differs from its window."""
    uv = _cooldown_days(root, "uv")
    npm = _cooldown_days(root, "npm")
    return [
        *(_uv_findings(root, uv) if uv else []),
        *(_npm_findings(root, npm, uv) if npm else []),
    ]


def test_cooldowns_on_repository_equal_their_windows() -> None:
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


# --- the npm cooldown and pnpm's minimumReleaseAge ---


def _dependabot(*, npm: str, uv: str | None = None) -> str:
    """A dependabot.yml with an npm update, and a uv one when ``uv`` is given."""
    text = "version: 2\nupdates:\n"
    if uv is not None:
        text += (
            f'  - package-ecosystem: "uv"\n    cooldown:\n      default-days: {uv}\n'
        )
    return text + (
        f'  - package-ecosystem: "npm"\n    cooldown:\n      default-days: {npm}\n'
    )


def _npm_root(
    make_root: MakeRoot, *, npm: str, workspace: str | None, uv: str | None = None
) -> Path:
    files = {DEPENDABOT: _dependabot(npm=npm, uv=uv)}
    if uv is not None:
        files[PYPROJECT] = f'[tool.uv]\nexclude-newer = "{uv} days"\n'
    if workspace is not None:
        files[PNPM_WORKSPACE] = workspace
    return make_root(files)


@pytest.mark.parametrize(
    ("days", "minutes"),
    [pytest.param(7, 10080, id="7-days"), pytest.param(14, 20160, id="14-days")],
)
def test_cooldown_findings_npm_equal_window_passes(
    make_root: MakeRoot, days: int, minutes: int
) -> None:
    root = _npm_root(
        make_root,
        npm=str(days),
        uv=str(days),
        workspace=f"packages:\n  - frontend\nminimumReleaseAge: {minutes}\n",
    )

    assert cooldown_findings(root) == []


def test_cooldown_findings_without_npm_update_passes(make_root: MakeRoot) -> None:
    # No pnpm-workspace.yaml either: an app that deleted the frontend.
    root = make_root(
        {
            DEPENDABOT: DEPENDABOT_TEXT.format(days=7),
            PYPROJECT: '[tool.uv]\nexclude-newer = "7 days"\n',
        }
    )

    assert cooldown_findings(root) == []


def test_cooldown_findings_npm_shorter_than_window_fails(make_root: MakeRoot) -> None:
    root = _npm_root(make_root, npm="3", workspace="minimumReleaseAge: 10080\n")

    assert cooldown_findings(root) == [
        (
            f"{DEPENDABOT}: the npm cooldown.default-days is '3' (4320 minutes), but "
            f"{PNPM_WORKSPACE}'s minimumReleaseAge is 10080; change both together"
        )
    ]


def test_cooldown_findings_npm_without_workspace_file_fails(
    make_root: MakeRoot,
) -> None:
    root = _npm_root(make_root, npm="7", workspace=None)

    assert cooldown_findings(root) == [
        (
            f"{PNPM_WORKSPACE} is missing: {DEPENDABOT}'s npm cooldown must equal "
            "its minimumReleaseAge"
        )
    ]


def test_cooldown_findings_npm_without_minimum_release_age_fails(
    make_root: MakeRoot,
) -> None:
    root = _npm_root(make_root, npm="7", workspace="packages:\n  - frontend\n")

    assert cooldown_findings(root) == [
        (
            f"{PNPM_WORKSPACE}: no minimumReleaseAge ({DEPENDABOT}'s npm cooldown "
            "must equal it)"
        )
    ]


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        pytest.param('"10080"', "'10080'", id="quoted-integer"),
        pytest.param('"20160"', "'20160'", id="quoted-other-integer"),
        pytest.param("7d", "'7d'", id="duration-string"),
        pytest.param("10080.0", "10080.0", id="float"),
        pytest.param("true", "True", id="boolean"),
    ],
)
def test_cooldown_findings_npm_non_integer_window_fails_closed(
    make_root: MakeRoot, value: str, shown: str
) -> None:
    root = _npm_root(make_root, npm="7", workspace=f"minimumReleaseAge: {value}\n")

    assert cooldown_findings(root) == [
        (
            f"{PNPM_WORKSPACE}: minimumReleaseAge is {shown}, not an integer count "
            f"of minutes ({DEPENDABOT}'s npm cooldown must equal it)"
        )
    ]


def test_cooldown_findings_npm_cooldown_not_a_day_count_fails(
    make_root: MakeRoot,
) -> None:
    root = _npm_root(make_root, npm="'a week'", workspace="minimumReleaseAge: 10080\n")

    assert cooldown_findings(root) == [
        (
            f"{DEPENDABOT}: the npm cooldown.default-days is 'a week', not a day "
            f"count ({PNPM_WORKSPACE}'s minimumReleaseAge is 10080)"
        )
    ]


def test_cooldown_findings_npm_differs_from_uv_fails(make_root: MakeRoot) -> None:
    # Each cooldown matches its own window, but the two windows differ.
    root = _npm_root(
        make_root, npm="14", uv="7", workspace="minimumReleaseAge: 20160\n"
    )

    assert cooldown_findings(root) == [
        (
            f"{DEPENDABOT}: the npm cooldown.default-days is '14', but the uv one is "
            "'7'; one window holds for the repository"
        )
    ]
