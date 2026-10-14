"""(k) No job an app keeps needs a job only the template has.

The bootstrap removes every template-only block from the files it keeps: a line
holding only ``<!-- template-only -->`` (behind ``#`` in YAML) through the line
holding only ``<!-- /template-only -->``, as CI's ``Template Bootstrap Smoke`` job
is. A job outside such a block whose ``needs:`` names a job inside one would leave
every app with a workflow GitHub refuses to run, so each workflow under
``.github/workflows/`` is read with its template-only blocks removed, and every
``needs:`` entry of a job that is left must name a job that is left too. A marker
opened inside a block, closed without one, or never closed raises
`UnreadableYamlError`, as the bootstrap refuses it, so the check never passes on a
workflow it cannot strip. In an app no block remains and the check reads the
workflows as they are, so it assumes no template-only file exists.

Also, while the smoke job exists: every tracked file holding a marker line is under
a path its "Assert no placeholder survived" step scans for leftover template-only
text, so a block added to a new file cannot outlive the bootstrap unseen.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.harness._workflows import jobs, workflow_files
from tests.harness._yaml import UnreadableYamlError, as_mapping, load_yaml, scalar_list

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ".github/workflows/ci.yml"
# Spelled so that no line of this file is a marker the bootstrap would act on.
OPEN = "<!-- " + "template-only -->"
CLOSE = "<!-- /" + "template-only -->"
# The marker shape the bootstrap removes (an app no longer carries the script).
_MARKER = re.compile(r"^\s*(?:#\s*)?<!-- (?P<close>/)?template-only -->\s*$")
# The smoke job's scan for template-only text the bootstrap should have removed.
_LEFTOVER_SCAN = re.compile(
    r"^\s*if grep -rn -e 'template-only' -e 'Template Bootstrap Smoke' (?P<paths>[^;]+);"
    r" then$",
    re.MULTILINE,
)


def strip_template_only(text: str, where: str) -> str:
    """Return ``text`` without its template-only blocks, marker lines included."""
    kept: list[str] = []
    open_line: int | None = None
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        marker = _MARKER.match(line)
        if marker is None:
            if open_line is None:
                kept.append(line)
        elif marker["close"]:
            if open_line is None:
                msg = f"{where}:{number}: template-only block closed but never opened"
                raise UnreadableYamlError(msg)
            open_line = None
        elif open_line is not None:
            msg = (
                f"{where}:{number}: template-only block opened inside the one at "
                f"line {open_line}"
            )
            raise UnreadableYamlError(msg)
        else:
            open_line = number
    if open_line is not None:
        msg = f"{where}:{open_line}: template-only block never closed"
        raise UnreadableYamlError(msg)
    return "".join(kept)


def _job_needs(job: dict[str, object], path: Path, job_id: str) -> list[str]:
    if "needs" not in job:
        return []
    return scalar_list(job["needs"], path, where=f"jobs.{job_id}.needs")


def _needs_findings(path: Path, relative: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    template = jobs(as_mapping(load_yaml(path, allow_merges=False), relative), path)
    stripped = strip_template_only(text, relative)
    if stripped == text:
        return []
    kept = jobs(
        as_mapping(load_yaml(path, text=stripped, allow_merges=False), relative),
        path,
    )
    template_only = set(template) - set(kept)
    return [
        f"{relative}: job {job_id!r} needs {needed!r}, which sits in a template-only "
        "block: the bootstrap removes it, and the app's workflow would name a "
        "missing job"
        for job_id, job in kept.items()
        for needed in _job_needs(job, path, job_id)
        if needed in template_only
    ]


def template_only_needs_findings(root: Path) -> list[str]:
    """Return each kept job that needs a job inside a template-only block."""
    return [
        finding
        for path in workflow_files(root)
        for finding in _needs_findings(path, path.relative_to(root).as_posix())
    ]


def unscanned_marker_files(root: Path, tracked: Iterable[str]) -> list[str]:
    """Return tracked files with a marker line that the smoke's leftover scan misses.

    Without the smoke job (an app), there is nothing to cover. With it, a scan line
    this check cannot read is a finding, so a reworded scan never passes unread.
    """
    ci = root / CI_WORKFLOW
    text = ci.read_text(encoding="utf-8") if ci.is_file() else ""
    if "name: Template Bootstrap Smoke" not in text:
        return []
    scan = _LEFTOVER_SCAN.search(text)
    if scan is None:
        return [f"{CI_WORKFLOW}: the smoke job's leftover scan line cannot be read"]
    scanned = scan["paths"].split()
    found = []
    for relative in tracked:
        path = root / relative
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        if not any(_MARKER.match(line) for line in lines):
            continue
        if relative == CI_WORKFLOW:
            continue
        if not any(
            relative == item or relative.startswith(f"{item}/") for item in scanned
        ):
            found.append(relative)
    return found


# --- the repository ---


def test_template_only_needs_on_repository_names_only_kept_jobs() -> None:
    assert template_only_needs_findings(REPO_ROOT) == []


def test_template_only_scan_on_repository_covers_every_marker_file() -> None:
    tracked = subprocess.run(
        # A fixed argv; git is resolved from PATH, as a shell would.
        ["git", "ls-files", "-z"],  # noqa: S607 -- see the line above
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.split("\0")

    assert unscanned_marker_files(REPO_ROOT, filter(None, tracked)) == []


# --- fixtures ---

WORKFLOW = f"""\
on: pull_request
jobs:
  lint:
    name: Lint
  ci-result:
    name: CI result
    needs: [lint]
  # {OPEN}
  bootstrap-smoke:
    name: Template Bootstrap Smoke
    needs: [lint]
  # {CLOSE}
"""


def _root(tmp_path: Path, workflow: str, name: str = "ci.yml") -> Path:
    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(workflow, encoding="utf-8")
    return tmp_path


def test_template_only_needs_kept_jobs_needing_kept_jobs_pass(tmp_path: Path) -> None:
    assert template_only_needs_findings(_root(tmp_path, WORKFLOW)) == []


def test_template_only_needs_without_blocks_passes(tmp_path: Path) -> None:
    workflow = strip_template_only(WORKFLOW, "ci.yml")

    assert template_only_needs_findings(_root(tmp_path, workflow)) == []


@pytest.mark.parametrize(
    "needs",
    [
        pytest.param("[lint, bootstrap-smoke]", id="list"),
        pytest.param("bootstrap-smoke", id="string"),
    ],
)
def test_template_only_needs_kept_job_needing_template_job_fails_naming_both(
    tmp_path: Path, needs: str
) -> None:
    workflow = WORKFLOW.replace(
        "    needs: [lint]\n  # <!--", f"    needs: {needs}\n  # <!--", 1
    )

    assert template_only_needs_findings(_root(tmp_path, workflow)) == [
        (
            ".github/workflows/ci.yml: job 'ci-result' needs 'bootstrap-smoke', "
            "which sits in a template-only block: the bootstrap removes it, and "
            "the app's workflow would name a missing job"
        )
    ]


def test_template_only_needs_reads_every_workflow(tmp_path: Path) -> None:
    other = WORKFLOW.replace(
        "needs: [lint]\n  # <!--", "needs: [bootstrap-smoke]\n  # <!--", 1
    )
    root = _root(tmp_path, WORKFLOW)
    _root(tmp_path, other, name="other.yml")

    assert template_only_needs_findings(root) == [
        (
            ".github/workflows/other.yml: job 'ci-result' needs 'bootstrap-smoke', "
            "which sits in a template-only block: the bootstrap removes it, and "
            "the app's workflow would name a missing job"
        )
    ]


@pytest.mark.parametrize(
    ("workflow", "message"),
    [
        pytest.param(
            WORKFLOW.replace(f"  # {CLOSE}\n", ""),
            r"ci\.yml:8: template-only block never closed",
            id="never-closed",
        ),
        pytest.param(
            WORKFLOW.replace(f"  # {OPEN}\n", ""),
            r"ci\.yml:11: template-only block closed but never opened",
            id="never-opened",
        ),
        pytest.param(
            WORKFLOW.replace(
                "    name: Template Bootstrap Smoke\n",
                f"    name: Template Bootstrap Smoke\n  # {OPEN}\n",
            ),
            r"ci\.yml:11: template-only block opened inside the one at line 8",
            id="nested",
        ),
    ],
)
def test_template_only_needs_unbalanced_markers_fail_closed(
    tmp_path: Path, workflow: str, message: str
) -> None:
    with pytest.raises(UnreadableYamlError, match=message):
        template_only_needs_findings(_root(tmp_path, workflow))


SMOKE = f"""\
jobs:
  # {OPEN}
  bootstrap-smoke:
    name: Template Bootstrap Smoke
    steps:
      - name: Assert no placeholder survived
        run: |
          if grep -rn -e 'template-only' -e 'Template Bootstrap Smoke' .agents AGENTS.md; then
            exit 1
          fi
  # {CLOSE}
"""
MARKED = f"text\n{OPEN}\nblock\n{CLOSE}\n"


def test_template_only_scan_covers_files_under_its_paths(tmp_path: Path) -> None:
    root = _root(tmp_path, SMOKE)
    (root / ".agents" / "skills").mkdir(parents=True)
    (root / ".agents" / "skills" / "SKILL.md").write_text(MARKED, encoding="utf-8")
    (root / "AGENTS.md").write_text(MARKED, encoding="utf-8")
    (root / "notes.md").write_text(
        "mentions <!-- template-only --> inline\n", encoding="utf-8"
    )
    tracked = [CI_WORKFLOW, ".agents/skills/SKILL.md", "AGENTS.md", "notes.md"]

    assert unscanned_marker_files(root, tracked) == []


def test_template_only_scan_missing_a_marker_file_names_it(tmp_path: Path) -> None:
    root = _root(tmp_path, SMOKE)
    (root / "backend").mkdir()
    (root / "backend" / "AGENTS.md").write_text(MARKED, encoding="utf-8")
    (root / "AGENTS.mdx").write_text(MARKED, encoding="utf-8")

    assert unscanned_marker_files(
        root, [CI_WORKFLOW, "backend/AGENTS.md", "AGENTS.mdx"]
    ) == ["backend/AGENTS.md", "AGENTS.mdx"]


def test_template_only_scan_without_the_smoke_job_passes(tmp_path: Path) -> None:
    root = _root(tmp_path, strip_template_only(SMOKE, "ci.yml"))
    (root / "AGENTS.md").write_text(MARKED, encoding="utf-8")

    assert unscanned_marker_files(root, [CI_WORKFLOW, "AGENTS.md"]) == []


def test_template_only_scan_unreadable_scan_line_fails(tmp_path: Path) -> None:
    root = _root(tmp_path, SMOKE.replace("grep -rn -e", "grep -rnI -e"))

    assert unscanned_marker_files(root, [CI_WORKFLOW]) == [
        f"{CI_WORKFLOW}: the smoke job's leftover scan line cannot be read"
    ]
