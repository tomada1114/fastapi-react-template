"""(j) CI's aggregate job needs every gating job in ``ci.yml``.

The ruleset requires one CI context, ``CI result`` (the ``ci-result`` job), so a
job outside its ``needs:`` gates nothing: a pull request can merge with it red.
Every job in ``.github/workflows/ci.yml`` is therefore either named in
``ci-result``'s ``needs:`` or listed in `EXEMPT_JOBS` with the reason it does not
gate. A ``needs:`` entry that names no job (an exempt one the bootstrap removed,
say) is an invalid workflow, so it fails too. That ``CI result`` is required,
cannot be skipped, and fails on each needed job's result is
``test_ruleset_contexts.py``'s. A ``ci.yml`` that is missing fails; one that cannot
be read raises `UnreadableYamlError`, so the check never passes by accident. An
exempt job need not exist: the check holds in an app the bootstrap cut from the
template too.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.harness._workflows import jobs, read_workflow
from tests.harness._yaml import UnreadableYamlError, scalar_list

if TYPE_CHECKING:
    from collections.abc import Callable

    type MakeRoot = Callable[[str | None], Path]

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ".github/workflows/ci.yml"
AGGREGATE = "ci-result"
# Jobs in ci.yml that deliberately do not gate a merge, each with its reason.
EXEMPT_JOBS = {
    "skill-scripts-py39": (
        "skill scripts on macOS's python3; a failure leaves the PR unstable, "
        "which automated merges stop on, without blocking a human's merge"
    ),
    "bootstrap-smoke": (
        "the template's own check: the bootstrap removes the job from the app "
        "it cuts, whose `needs:` would then name a missing job"
    ),
}


NO_AGGREGATE = (
    f"{CI_WORKFLOW}: no `{AGGREGATE}` job, so no single required check gates "
    "every CI job"
)


def _ungated(job: str) -> str:
    return (
        f"{CI_WORKFLOW}: job {job!r} is neither in `{AGGREGATE}`'s `needs:` nor "
        "exempt in tests/harness/test_ci_aggregate.py, so it gates nothing"
    )


def aggregate_findings(root: Path) -> list[str]:
    """Return each way ``ci.yml``'s jobs escape the ``ci-result`` aggregate."""
    path = root / CI_WORKFLOW
    if not path.is_file():
        return [f"{CI_WORKFLOW} is missing: the aggregate job cannot be checked"]
    workflow_jobs = jobs(read_workflow(path), path)
    if AGGREGATE not in workflow_jobs:
        return [NO_AGGREGATE]
    aggregate = workflow_jobs[AGGREGATE]
    if "needs" not in aggregate:
        return [f"{CI_WORKFLOW}: `{AGGREGATE}` has no `needs:`"]
    needed = scalar_list(aggregate["needs"], path, where=f"jobs.{AGGREGATE}.needs")
    if not needed:
        msg = f"{path.name}: cannot read `jobs.{AGGREGATE}.needs`"
        raise UnreadableYamlError(msg)
    findings = [
        f"{CI_WORKFLOW}: `{AGGREGATE}` needs {job!r}, which is not a job in it"
        for job in needed
        if job not in workflow_jobs
    ]
    findings.extend(
        _ungated(job)
        for job in workflow_jobs
        if job != AGGREGATE and job not in needed and job not in EXEMPT_JOBS
    )
    return findings


# --- the repository ---


def test_ci_aggregate_on_repository_needs_every_gating_job() -> None:
    assert aggregate_findings(REPO_ROOT) == []


def test_ci_aggregate_on_repository_runs_even_when_the_run_is_cancelled() -> None:
    # `!cancelled()` skips the job on a manual cancel, and a skipped required
    # check reports success, so a cancelled run could merge with no gate at all.
    path = REPO_ROOT / CI_WORKFLOW
    aggregate = jobs(read_workflow(path), path)[AGGREGATE]
    assert str(aggregate.get("if", "")).removeprefix("${{").removesuffix(
        "}}"
    ).strip() == ("always()")


def test_ci_aggregate_exempt_jobs_each_carry_a_reason() -> None:
    assert all(reason.strip() for reason in EXEMPT_JOBS.values())


# --- fixtures ---

AGGREGATE_JOB = (
    "  ci-result:\n    name: CI result\n    if: ${{ !cancelled() }}\n"
    "    needs: [lint, test]\n"
)
WORKFLOW = (
    "on: pull_request\njobs:\n  lint:\n    name: Lint\n  test:\n    name: Test\n"
    + AGGREGATE_JOB
)


@pytest.fixture
def make_root(tmp_path: Path) -> MakeRoot:
    def make(workflow: str | None) -> Path:
        (tmp_path / CI_WORKFLOW).parent.mkdir(parents=True)
        if workflow is not None:
            (tmp_path / CI_WORKFLOW).write_text(workflow, encoding="utf-8")
        return tmp_path

    return make


def test_ci_aggregate_every_job_needed_passes(make_root: MakeRoot) -> None:
    assert aggregate_findings(make_root(WORKFLOW)) == []


@pytest.mark.parametrize("job", sorted(EXEMPT_JOBS))
def test_ci_aggregate_exempt_job_outside_needs_passes(
    make_root: MakeRoot, job: str
) -> None:
    workflow = WORKFLOW + f"  {job}:\n    name: Not gating\n"

    assert aggregate_findings(make_root(workflow)) == []


def test_ci_aggregate_job_missing_from_needs_fails_naming_it(
    make_root: MakeRoot,
) -> None:
    workflow = WORKFLOW + "  e2e:\n    name: End to end\n"

    assert aggregate_findings(make_root(workflow)) == [_ungated("e2e")]


def test_ci_aggregate_string_needs_counts_its_job(make_root: MakeRoot) -> None:
    workflow = WORKFLOW.replace("[lint, test]", "lint")

    assert aggregate_findings(make_root(workflow)) == [_ungated("test")]


@pytest.mark.parametrize("job", ["e2e", "bootstrap-smoke"])
def test_ci_aggregate_needs_naming_no_job_fails(make_root: MakeRoot, job: str) -> None:
    workflow = WORKFLOW.replace("[lint, test]", f"[lint, test, {job}]")

    assert aggregate_findings(make_root(workflow)) == [
        f"{CI_WORKFLOW}: `ci-result` needs {job!r}, which is not a job in it"
    ]


def test_ci_aggregate_missing_aggregate_fails(make_root: MakeRoot) -> None:
    workflow = WORKFLOW.replace(AGGREGATE_JOB, "")

    assert aggregate_findings(make_root(workflow)) == [NO_AGGREGATE]


def test_ci_aggregate_aggregate_without_needs_fails(make_root: MakeRoot) -> None:
    workflow = WORKFLOW.replace("    needs: [lint, test]\n", "")

    assert aggregate_findings(make_root(workflow)) == [
        f"{CI_WORKFLOW}: `ci-result` has no `needs:`"
    ]


def test_ci_aggregate_missing_workflow_fails(make_root: MakeRoot) -> None:
    assert aggregate_findings(make_root(None)) == [
        f"{CI_WORKFLOW} is missing: the aggregate job cannot be checked"
    ]


@pytest.mark.parametrize(
    ("workflow", "message"),
    [
        pytest.param("on: pull_request\njobs: [\n", r"ci\.yml", id="invalid-yaml"),
        pytest.param("on: pull_request\njobs: [lint]\n", r"jobs", id="jobs-sequence"),
        pytest.param(
            WORKFLOW.replace("[lint, test]", "{lint: x}"),
            r"jobs\.ci-result\.needs",
            id="needs-mapping",
        ),
        pytest.param(
            WORKFLOW.replace("[lint, test]", "[]"),
            r"cannot read `jobs\.ci-result\.needs`",
            id="needs-empty",
        ),
    ],
)
def test_ci_aggregate_unreadable_workflow_fails_closed(
    make_root: MakeRoot, workflow: str, message: str
) -> None:
    with pytest.raises(UnreadableYamlError, match=message):
        aggregate_findings(make_root(workflow))
