"""(f) Every workflow is pinned, least-privileged, bounded, and fails closed.

Per workflow under ``.github/workflows/``:

- every non-local ``uses:`` (a step's, or a job's reusable-workflow call) is
  ``owner/repo[/path]@<40-hex SHA>`` with a ``# v<version>`` comment, the form
  Dependabot keeps when it bumps a pin; a local ``./`` action is skipped;
- every job sets ``timeout-minutes`` (a reusable-workflow call cannot, and is
  exempt);
- the top-level ``permissions`` is ``{}`` or exactly ``contents: read``; a job
  that needs more declares it on the job;
- every ``actions/checkout`` step sets ``persist-credentials: false``;
- no ``pull_request_target`` trigger, no ``continue-on-error`` other than
  ``false`` on a job or step, and no ``|| true`` on a non-comment line;
- on a workflow triggered on ``push``, no concurrency (top-level or a job's)
  cancels a push run on main: ``cancel-in-progress`` is absent, ``false``, or
  ``${{ github.event_name == 'pull_request' }}``; and the group differs per
  push run, because GitHub also cancels a *pending* run when a newer one joins
  its group. The group is read as text, not evaluated: it passes only as the
  idiom ``${{ github.event_name == 'pull_request' && github.ref || github.sha }}``
  (``head_ref``/``run_id``/``run_number`` accepted in their places), or with no
  ``github.ref``/``head_ref``/``event_name`` and a ``github.sha``, ``run_id``, or
  ``run_number``. Inline mappings follow the same policy as block mappings.

Per local action under ``.github/actions/`` (``**/action.yml`` or
``action.yaml``), when its ``runs.using`` is ``composite``, every step meets the
step rules above: a pinned ``uses:``, ``persist-credentials: false`` on a
checkout, and no ``continue-on-error``; and no line has ``|| true``. An action with another ``runs.using``
(a JavaScript or Docker action) has no ``uses:`` steps to check; a Docker
action's image and Dockerfile are not read. An action file without a readable
``runs.using`` fails closed. No directory, no action, no finding.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.harness._workflows import (
    WORKFLOWS_DIR,
    entry_value,
    jobs,
    read_workflow,
    steps,
    triggers,
    workflow_files,
)
from tests.harness._yaml import (
    Mapping,
    UnreadableYamlError,
    as_mapping,
    as_str,
    scalar,
    source_comment,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    type MakeWorkflow = Callable[[str], Path]

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIONS_DIR = ".github/actions"
ACTION_FILES = ("action.yml", "action.yaml")
COMPOSITE_ACTION = "composite"
MINIMAL_PERMISSIONS: tuple[dict[str, str], ...] = ({}, {"contents": "read"})
SAFE_CANCEL = frozenset({"false", "${{ github.event_name == 'pull_request' }}"})
PER_RUN_CONTEXTS = ("github.sha", "github.run_id", "github.run_number")
CHECKOUT = "actions/checkout"

_PINNED = re.compile(r"^[\w.-]+/[\w.-]+(?:/[^@\s]+)?@[0-9a-f]{40}$")
_VERSION_COMMENT = re.compile(r"^#\s*v\d")
_OR_TRUE = re.compile(r"\|\|\s*true\b")
# The one idiom that keeps a ref group for pull requests and a per-run group for
# everything else. Any other reference to the ref (or the event) in a group is
# read as possibly shared by push runs.
_PR_REF_OR_RUN = re.compile(
    r"\$\{\{\s*github\.event_name\s*==\s*'pull_request'\s*&&\s*"
    r"github\.(?:ref|head_ref)\s*\|\|\s*github\.(?:sha|run_id|run_number)\s*\}\}"
)
_REF_OR_EVENT = re.compile(r"github\.(?:ref|head_ref|event_name)\b")


def _pin_problems(entry: object, where: str) -> list[str]:
    ref = as_str(entry, f"{where}.uses")
    comment = source_comment(entry)
    if ref.startswith("./"):
        return []
    if not _PINNED.match(ref):
        return [f"{where}: `uses: {ref}` is not pinned to a full commit SHA"]
    if comment is None or not _VERSION_COMMENT.match(comment):
        return [f"{where}: `uses: {ref}` has no `# v<version>` comment"]
    return []


def _permissions(entry: object, path: Path) -> dict[str, str] | None:
    """Return the top-level permissions as a dict, or None for a shorthand."""
    if entry is None or isinstance(entry, str):
        return None
    return {
        key: scalar(scope, f"{path}: permissions.{key}")
        for key, scope in as_mapping(entry, f"{path}: permissions").items()
    }


def _is_per_push_run(group: str) -> bool:
    """Whether a concurrency group differs between any two push runs."""
    rest = _PR_REF_OR_RUN.sub("", group)
    if _REF_OR_EVENT.search(rest):
        return False
    return rest != group or any(context in rest for context in PER_RUN_CONTEXTS)


def _concurrency_problems(entry: object, where: str, path: Path) -> list[str]:
    if isinstance(entry, str):
        group, cancel = entry, None
    else:
        settings = as_mapping(entry, f"{path}: concurrency")
        group = entry_value(settings.get("group")) or ""
        cancel = entry_value(settings.get("cancel-in-progress"))
    problems: list[str] = []
    if cancel is not None and " ".join(cancel.split()) not in SAFE_CANCEL:
        problems.append(
            f"{where}: `cancel-in-progress: {cancel}` can cancel a push run on main"
        )
    if not _is_per_push_run(group):
        problems.append(
            f"{where}: concurrency group {group!r} is shared by push runs, so a "
            "newer push cancels a pending one"
        )
    return problems


def _continue_on_error(entry: object, where: str) -> list[str]:
    value = entry_value(entry)
    if value is None or value == "false":
        return []
    return [f"{where}: `continue-on-error: {value}` lets a failure pass"]


def _keeps_credentials(step: Mapping, path: Path) -> bool:
    settings = as_mapping(step.get("with", {}), f"{path}: steps.with")
    persist = entry_value(settings.get("persist-credentials"))
    return persist != "false"


def _step_problems(step: Mapping, where: str, path: Path) -> list[str]:
    problems = _continue_on_error(step.get("continue-on-error"), where)
    if "uses" not in step:
        return problems
    problems.extend(_pin_problems(step["uses"], where))
    is_checkout = scalar(step["uses"]).split("@")[0] == CHECKOUT
    if is_checkout and _keeps_credentials(step, path):
        problems.append(f"{where}: actions/checkout without persist-credentials: false")
    return problems


def _job_problems(job_id: str, job: Mapping, path: Path, *, is_push: bool) -> list[str]:
    relative = f"{WORKFLOWS_DIR}/{path.name}"
    where = f"{relative}: job {job_id!r}"
    problems = _continue_on_error(job.get("continue-on-error"), where)
    if "uses" in job:
        problems.extend(_pin_problems(job["uses"], where))
    elif "timeout-minutes" not in job:
        problems.append(f"{where}: no timeout-minutes")
    if is_push and "concurrency" in job:
        problems.extend(_concurrency_problems(job["concurrency"], where, path))
    for number, step in enumerate(steps(job, path), start=1):
        name = entry_value(step.get("name"))
        label = f"{where} step {number}" + (f" ({name})" if name else "")
        problems.extend(_step_problems(step, label, path))
    return problems


def _or_true_problems(path: Path, relative: str) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        f"{relative}:{number}: `|| true` swallows a failure"
        for number, line in enumerate(lines, start=1)
        if not line.lstrip().startswith("#") and _OR_TRUE.search(line)
    ]


def workflow_problems(path: Path) -> list[str]:
    """Return every hygiene problem of one workflow file."""
    relative = f"{WORKFLOWS_DIR}/{path.name}"
    top = read_workflow(path)
    events = triggers(top, path)
    problems: list[str] = []
    if "pull_request_target" in events:
        problems.append(f"{relative}: triggers on pull_request_target")
    if _permissions(top.get("permissions"), path) not in MINIMAL_PERMISSIONS:
        problems.append(
            f"{relative}: top-level permissions must be {{}} or contents: read"
        )
    problems.extend(_or_true_problems(path, relative))
    is_push = "push" in events
    if is_push and "concurrency" in top:
        problems.extend(_concurrency_problems(top["concurrency"], relative, path))
    for job_id, job in jobs(top, path).items():
        problems.extend(_job_problems(job_id, job, path, is_push=is_push))
    return problems


def action_files(root: Path) -> list[Path]:
    """Return every local action file under ``root``'s actions directory, sorted."""
    found = {
        path
        for name in ACTION_FILES
        for path in (root / ACTIONS_DIR).glob(f"**/{name}")
        if path.is_file()
    }
    return sorted(found)


def action_problems(path: Path, root: Path) -> list[str]:
    """Return every hygiene problem of one local action's composite steps.

    The scanner names a file by its basename, and every action is an
    ``action.yml``, so an unreadable one is re-raised under its relative path.
    """
    relative = path.relative_to(root).as_posix()
    try:
        return _composite_problems(path, relative)
    except UnreadableYamlError as exc:
        detail = str(exc).removeprefix(f"{path}: ").removeprefix(f"{path.name}: ")
        msg = f"{relative}: {detail}"
        raise UnreadableYamlError(msg) from exc


def _composite_problems(path: Path, relative: str) -> list[str]:
    runs = read_workflow(path).get("runs")
    if runs is None:
        msg = f"{path.name}: no `runs:`"
        raise UnreadableYamlError(msg)
    settings = as_mapping(runs, f"{path}: runs")
    using = entry_value(settings.get("using"))
    if using is None:
        msg = f"{path.name}: no `runs.using`"
        raise UnreadableYamlError(msg)
    if using != COMPOSITE_ACTION:
        return []
    problems = _or_true_problems(path, relative)
    for number, step in enumerate(steps(settings, path), start=1):
        name = entry_value(step.get("name"))
        label = f"{relative}: step {number}" + (f" ({name})" if name else "")
        problems.extend(_step_problems(step, label, path))
    return problems


def hygiene_findings(root: Path) -> list[str]:
    """Return every hygiene problem across the workflows and local actions."""
    workflows = [
        problem for path in workflow_files(root) for problem in workflow_problems(path)
    ]
    actions = [
        problem
        for path in action_files(root)
        for problem in action_problems(path, root)
    ]
    return workflows + actions


# --- the repository ---


def test_workflows_on_repository_are_hygienic() -> None:
    assert workflow_files(REPO_ROOT)
    assert hygiene_findings(REPO_ROOT) == []


# --- fixtures ---

SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
CLEAN = f"""\
name: W

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

concurrency:
  group: ${{{{ github.workflow }}}}-${{{{ github.event_name == 'pull_request' && github.ref || github.sha }}}}
  cancel-in-progress: ${{{{ github.event_name == 'pull_request' }}}}

jobs:
  build:
    name: Build
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
        with:
          persist-credentials: false
      - uses: ./.github/actions/local
      - name: Test
        run: |
          set -euo pipefail
          # never `|| true` here
          uv run pytest
"""


@pytest.fixture
def make_workflow(tmp_path: Path) -> MakeWorkflow:
    def make(text: str) -> Path:
        (tmp_path / WORKFLOWS_DIR).mkdir(parents=True, exist_ok=True)
        (tmp_path / WORKFLOWS_DIR / "w.yml").write_text(text, encoding="utf-8")
        return tmp_path

    return make


def test_hygiene_findings_clean_workflow_passes(make_workflow: MakeWorkflow) -> None:
    assert hygiene_findings(make_workflow(CLEAN)) == []


@pytest.mark.parametrize("local_comment", ["", " # v7.0.1"])
def test_hygiene_findings_alias_requires_local_pin_comment(
    make_workflow: MakeWorkflow, local_comment: str
) -> None:
    text = CLEAN.replace(
        "name: W", f"name: &pin actions/checkout@{SHA} # v7.0.1"
    ).replace(f"uses: actions/checkout@{SHA} # v7.0.1", f"uses: *pin{local_comment}")

    expected = (
        []
        if local_comment
        else [
            f"{JOB} step 1: `uses: actions/checkout@{SHA}` has no `# v<version>` comment"
        ]
    )
    assert hygiene_findings(make_workflow(text)) == expected


def test_hygiene_findings_without_workflows_passes(tmp_path: Path) -> None:
    assert hygiene_findings(tmp_path) == []


W = f"{WORKFLOWS_DIR}/w.yml"
JOB = f"{W}: job 'build'"


@pytest.mark.parametrize(
    ("old", "new", "finding"),
    [
        pytest.param(
            f"@{SHA} # v7.0.1",
            "@v7",
            f"{JOB} step 1: `uses: actions/checkout@v7` is not pinned to a full commit SHA",
            id="tag-pin",
        ),
        pytest.param(
            f"@{SHA} # v7.0.1",
            f"@{SHA}",
            f"{JOB} step 1: `uses: actions/checkout@{SHA}` has no `# v<version>` comment",
            id="no-version-comment",
        ),
        pytest.param(
            "    timeout-minutes: 10\n",
            "",
            f"{JOB}: no timeout-minutes",
            id="no-timeout",
        ),
        pytest.param(
            "permissions:\n  contents: read\n\nconcurrency",
            "permissions:\n  contents: write\n\nconcurrency",
            f"{W}: top-level permissions must be {{}} or contents: read",
            id="write-permissions",
        ),
        pytest.param(
            "permissions:\n  contents: read\n\nconcurrency",
            "permissions: write-all\n\nconcurrency",
            f"{W}: top-level permissions must be {{}} or contents: read",
            id="shorthand-permissions",
        ),
        pytest.param(
            "permissions:\n  contents: read\n\nconcurrency",
            "concurrency",
            f"{W}: top-level permissions must be {{}} or contents: read",
            id="no-permissions",
        ),
        pytest.param(
            "          persist-credentials: false\n",
            "          fetch-depth: 0\n",
            f"{JOB} step 1: actions/checkout without persist-credentials: false",
            id="checkout-keeps-credentials",
        ),
        pytest.param(
            "  pull_request:\n",
            "  pull_request_target:\n",
            f"{W}: triggers on pull_request_target",
            id="pull-request-target",
        ),
        pytest.param(
            "      - name: Test\n",
            "      - name: Test\n        continue-on-error: true\n",
            f"{JOB} step 3 (Test): `continue-on-error: true` lets a failure pass",
            id="step-continue-on-error",
        ),
        pytest.param(
            "    timeout-minutes: 10\n",
            "    timeout-minutes: 10\n    continue-on-error: ${{ matrix.experimental }}\n",
            f"{JOB}: `continue-on-error: ${{{{ matrix.experimental }}}}` lets a "
            "failure pass",
            id="job-continue-on-error",
        ),
        pytest.param(
            "          uv run pytest\n",
            "          uv run pytest || true\n",
            f"{W}:31: `|| true` swallows a failure",
            id="or-true",
        ),
        pytest.param(
            "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n",
            "  cancel-in-progress: true\n",
            f"{W}: `cancel-in-progress: true` can cancel a push run on main",
            id="cancels-push",
        ),
        pytest.param(
            "github.event_name == 'pull_request' && github.ref || github.sha",
            "github.ref",
            f"{W}: concurrency group '${{{{ github.workflow }}}}-${{{{ github.ref }}}}' "
            "is shared by push runs, so a newer push cancels a pending one",
            id="push-group-by-ref",
        ),
        pytest.param(
            "github.event_name == 'pull_request' && github.ref || github.sha",
            "github.event_name == 'push' && github.ref || github.sha",
            f'{W}: concurrency group "${{{{ github.workflow }}}}-${{{{ '
            "github.event_name == 'push' && github.ref || github.sha }}\" is shared "
            "by push runs, so a newer push cancels a pending one",
            id="push-group-inverted-idiom",
        ),
        pytest.param(
            "${{ github.event_name == 'pull_request' && github.ref || github.sha }}",
            "${{ github.ref }}-${{ github.event_name == 'pull_request' && github.sha || '' }}",
            f'{W}: concurrency group "${{{{ github.workflow }}}}-${{{{ github.ref }}}}-'
            "${{ github.event_name == 'pull_request' && github.sha || '' }}\" is shared "
            "by push runs, so a newer push cancels a pending one",
            id="push-group-ref-plus-optional-sha",
        ),
        pytest.param(
            "    permissions:\n      pull-requests: write\n",
            "    concurrency: deploy\n",
            f"{JOB}: concurrency group 'deploy' is shared by push runs, so a newer "
            "push cancels a pending one",
            id="job-concurrency",
        ),
    ],
)
def test_hygiene_findings_violation_names_workflow(
    make_workflow: MakeWorkflow, old: str, new: str, finding: str
) -> None:
    assert old in CLEAN

    root = make_workflow(CLEAN.replace(old, new))

    assert hygiene_findings(root) == [finding]


def test_hygiene_findings_pull_request_only_may_cancel(
    make_workflow: MakeWorkflow,
) -> None:
    text = (
        CLEAN.replace("  push:\n    branches: [main]\n", "")
        .replace(
            "github.event_name == 'pull_request' && github.ref || github.sha",
            "github.ref",
        )
        .replace("${{ github.event_name == 'pull_request' }}", "true")
    )

    assert hygiene_findings(make_workflow(text)) == []


def test_hygiene_findings_reusable_workflow_call_needs_pin_not_timeout(
    make_workflow: MakeWorkflow,
) -> None:
    text = (
        "on: pull_request\npermissions: {}\njobs:\n  call:\n"
        "    uses: org/repo/.github/workflows/x.yml@main\n"
    )

    assert hygiene_findings(make_workflow(text)) == [
        (
            f"{W}: job 'call': `uses: org/repo/.github/workflows/x.yml@main` is not "
            "pinned to a full commit SHA"
        )
    ]


def test_hygiene_findings_indentless_steps_pass(
    make_workflow: MakeWorkflow,
) -> None:
    text = (
        CLEAN.replace("      -", "    -")
        .replace("        ", "      ")
        .replace("          ", "        ")
    )

    assert hygiene_findings(make_workflow(text)) == []


@pytest.mark.parametrize(
    "group",
    [
        pytest.param("${{ github.workflow }}-${{ github.sha }}", id="sha"),
        pytest.param("deploy-${{ github.run_id }}", id="run-id"),
        pytest.param(
            "${{ github.workflow }}-${{ github.event_name == 'pull_request' "
            "&& github.head_ref || github.run_id }}",
            id="head-ref-idiom",
        ),
    ],
)
def test_hygiene_findings_per_run_push_group_passes(
    make_workflow: MakeWorkflow, group: str
) -> None:
    text = CLEAN.replace(
        "${{ github.workflow }}-${{ github.event_name == 'pull_request' "
        "&& github.ref || github.sha }}",
        group,
    )

    assert hygiene_findings(make_workflow(text)) == []


def test_hygiene_findings_inline_concurrency_enforces_cancel_policy(
    make_workflow: MakeWorkflow,
) -> None:
    start = CLEAN.index("concurrency:\n")
    end = CLEAN.index("jobs:\n")
    text = (
        CLEAN[:start]
        + 'concurrency: {group: "x-${{ github.sha }}", cancel-in-progress: true}\n\n'
        + CLEAN[end:]
    )

    assert hygiene_findings(make_workflow(text)) == [
        f"{W}: `cancel-in-progress: true` can cancel a push run on main"
    ]


# --- composite actions ---

COMPOSITE = f"""\
name: Setup
description: Check out and install.
runs:
  using: composite
  steps:
    - uses: actions/checkout@{SHA} # v7.0.1
      with:
        persist-credentials: false
    - uses: ./.github/actions/other
    - name: Install
      shell: bash
      run: uv sync --locked
"""


@pytest.fixture
def make_action(tmp_path: Path) -> MakeWorkflow:
    def make(text: str) -> Path:
        (tmp_path / ACTIONS_DIR / "setup").mkdir(parents=True, exist_ok=True)
        (tmp_path / ACTIONS_DIR / "setup" / "action.yml").write_text(
            text, encoding="utf-8"
        )
        return tmp_path

    return make


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(COMPOSITE, id="composite"),
        pytest.param(
            "name: N\ndescription: D\nruns:\n  using: node24\n  main: index.js\n",
            id="javascript-action",
        ),
    ],
)
def test_hygiene_findings_clean_action_passes(
    make_action: MakeWorkflow, text: str
) -> None:
    assert hygiene_findings(make_action(text)) == []


A = f"{ACTIONS_DIR}/setup/action.yml"


@pytest.mark.parametrize(
    ("old", "new", "finding"),
    [
        pytest.param(
            f"@{SHA} # v7.0.1",
            "@v7",
            f"{A}: step 1: `uses: actions/checkout@v7` is not pinned to a full "
            "commit SHA",
            id="tag-pin",
        ),
        pytest.param(
            f"@{SHA} # v7.0.1",
            f"@{SHA}",
            f"{A}: step 1: `uses: actions/checkout@{SHA}` has no `# v<version>` "
            "comment",
            id="no-version-comment",
        ),
        pytest.param(
            "        persist-credentials: false\n",
            "        fetch-depth: 0\n",
            f"{A}: step 1: actions/checkout without persist-credentials: false",
            id="checkout-keeps-credentials",
        ),
        pytest.param(
            "    - name: Install\n",
            "    - name: Install\n      continue-on-error: true\n",
            f"{A}: step 3 (Install): `continue-on-error: true` lets a failure pass",
            id="continue-on-error",
        ),
        pytest.param(
            "      run: uv sync --locked\n",
            "      run: uv sync --locked || true\n",
            f"{A}:12: `|| true` swallows a failure",
            id="or-true",
        ),
    ],
)
def test_hygiene_findings_action_violation_names_action(
    make_action: MakeWorkflow, old: str, new: str, finding: str
) -> None:
    assert old in COMPOSITE

    root = make_action(COMPOSITE.replace(old, new))

    assert hygiene_findings(root) == [finding]


def test_hygiene_findings_action_yaml_extension_is_read(tmp_path: Path) -> None:
    (tmp_path / ACTIONS_DIR / "x").mkdir(parents=True)
    (tmp_path / ACTIONS_DIR / "x" / "action.yaml").write_text(
        COMPOSITE.replace(f"@{SHA} # v7.0.1", "@main"), encoding="utf-8"
    )

    assert hygiene_findings(tmp_path) == [
        (
            f"{ACTIONS_DIR}/x/action.yaml: step 1: `uses: actions/checkout@main` is not "
            "pinned to a full commit SHA"
        )
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param("name: N\ndescription: D\n", r"no `runs:`", id="no-runs"),
        pytest.param(
            "name: N\nruns: [composite]\n",
            r".*runs: expected mapping",
            id="runs-sequence",
        ),
        pytest.param(
            "name: N\nruns:\n  steps: []\n", r"no `runs.using`", id="no-using"
        ),
        pytest.param(
            COMPOSITE.replace("    - uses: actions", "  - uses: actions"),
            r".*while parsing",
            id="bad-step-indent",
        ),
        pytest.param(
            COMPOSITE.replace(
                "      with:\n        persist-credentials: false\n",
                "      with: [false]\n",
            ),
            r".*steps.with: expected mapping",
            id="with-sequence",
        ),
    ],
)
def test_hygiene_findings_unreadable_action_fails_closed(
    make_action: MakeWorkflow, text: str, message: str
) -> None:
    # The repository-relative path, not a bare `action.yml`, names the file.
    with pytest.raises(UnreadableYamlError, match=rf"^{re.escape(A)}: {message}"):
        hygiene_findings(make_action(text))


def test_hygiene_findings_inline_action_mappings_pass(
    make_action: MakeWorkflow,
) -> None:
    text = COMPOSITE.replace(
        "      with:\n        persist-credentials: false\n",
        "      with: {persist-credentials: false}\n",
    )
    assert hygiene_findings(make_action(text)) == []
    assert hygiene_findings(make_action("runs: {using: composite, steps: []}\n")) == []


def test_hygiene_findings_action_merge_keys_fail_closed(
    make_action: MakeWorkflow,
) -> None:
    text = "defaults: &defaults {using: composite, steps: []}\nruns: {<<: *defaults}\n"

    with pytest.raises(UnreadableYamlError, match=r"merge keys.*GitHub Actions"):
        hygiene_findings(make_action(text))
