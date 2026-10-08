"""(d) Every required context of the main ruleset is a job every PR runs.

A required check must be a job that runs on every pull request and cannot be
skipped: a context no workflow produces, or one from a workflow whose
``pull_request`` trigger has ``paths``/``paths-ignore``, leaves every other
pull request waiting forever, and a skipped required check counts as passing.
A required job with ``needs:`` runs under ``!cancelled()``/``always()`` even
when a needed job failed, so it must also fail on its own: some step fails
when ``needs.<job>.result`` is not ``success``, for each needed job, as CI's
``Coverage`` does. ``_needs.py`` lists the step shapes that count; it reads
only required jobs. The workflow scanner (``_workflows.py``) fails closed on a
layout it cannot read. The ruleset's own content
is pinned by ``tests/test_apply_ruleset.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.harness._needs import unfailed_needs
from tests.harness._workflows import can_skip, every_pr_checks
from tests.harness._yaml import UnreadableYamlError

if TYPE_CHECKING:
    from collections.abc import Callable

    type MakeRoot = Callable[..., Path]

REPO_ROOT = Path(__file__).resolve().parents[2]
RULESET = ".github/rulesets/main.json"
SHAPES_HINT = "see the step shapes tests/harness/_needs.py accepts"
WORKFLOWS = ".github/workflows"


def _required_contexts(ruleset: object) -> list[str] | None:
    """Return the ruleset's required contexts, or None when its shape is unknown."""
    if not isinstance(ruleset, dict) or not isinstance(ruleset.get("rules"), list):
        return None
    contexts: list[str] = []
    for rule in ruleset["rules"]:
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        parameters = rule.get("parameters")
        checks = (
            parameters.get("required_status_checks")
            if isinstance(parameters, dict)
            else None
        )
        if not isinstance(checks, list) or not all(
            isinstance(check, dict) and isinstance(check.get("context"), str)
            for check in checks
        ):
            return None
        contexts.extend(check["context"] for check in checks)
    return contexts


def ruleset_context_findings(root: Path) -> list[str]:
    """Return each required context that is not an unskippable every-PR job."""
    path = root / RULESET
    if not path.is_file():
        return [f"{RULESET} is missing: the required contexts cannot be checked"]
    try:
        contexts = _required_contexts(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        return [f"{RULESET}: invalid JSON ({exc})"]
    if contexts is None:
        return [f"{RULESET}: no readable rules[].parameters.required_status_checks"]
    if not contexts:
        return [f"{RULESET}: requires no status check, so nothing gates a merge"]
    available = every_pr_checks(root / WORKFLOWS)
    findings: list[str] = []
    for context in contexts:
        if context not in available:
            findings.append(
                f"{RULESET}: required context {context!r} is not a job that runs "
                "on every pull request"
            )
            continue
        check = available[context]
        if can_skip(check):
            findings.append(
                f"{RULESET}: required context {context!r} is a job whose `if:` or "
                "`needs:` can skip it"
            )
        findings.extend(
            f"{RULESET}: required context {context!r} needs {job!r}, but no step "
            f"fails when `needs.{job}.result` is not 'success'; {SHAPES_HINT}"
            for job in unfailed_needs(check)
        )
    return findings


# --- the repository ---


def test_ruleset_contexts_on_repository_are_every_pr_jobs() -> None:
    assert ruleset_context_findings(REPO_ROOT) == []


# --- fixtures ---

LINT_WORKFLOW = "on: pull_request\njobs:\n  lint:\n    name: Lint\n"
# The step that fails a needs-job on its own, as ci.yml's Coverage spells it.
FAIL_ON_LINT = (
    "    steps:\n"
    "      - name: Fail when lint did not succeed\n"
    "        env:\n"
    "          LINT_RESULT: ${{ needs.lint.result }}\n"
    "        run: |\n"
    '          if [ "$LINT_RESULT" != "success" ]; then\n'
    '            echo "::error::lint finished with result: $LINT_RESULT"\n'
    "            exit 1\n"
    "          fi\n"
)


def _ruleset(*contexts: str) -> str:
    checks = [{"context": context, "integration_id": 15368} for context in contexts]
    rule = {
        "type": "required_status_checks",
        "parameters": {"required_status_checks": checks},
    }
    return json.dumps({"name": "main", "rules": [{"type": "deletion"}, rule]})


@pytest.fixture
def make_root(tmp_path: Path) -> MakeRoot:
    def make(ruleset: str | None, workflow: str = LINT_WORKFLOW) -> Path:
        (tmp_path / WORKFLOWS).mkdir(parents=True)
        (tmp_path / WORKFLOWS / "w.yml").write_text(workflow, encoding="utf-8")
        if ruleset is not None:
            (tmp_path / RULESET).parent.mkdir(parents=True)
            (tmp_path / RULESET).write_text(ruleset, encoding="utf-8")
        return tmp_path

    return make


def test_ruleset_contexts_pass_on_every_pr_job(make_root: MakeRoot) -> None:
    assert ruleset_context_findings(make_root(_ruleset("Lint"))) == []


def test_ruleset_contexts_missing_ruleset_fails(make_root: MakeRoot) -> None:
    findings = ruleset_context_findings(make_root(None))

    assert findings == [
        f"{RULESET} is missing: the required contexts cannot be checked"
    ]


@pytest.mark.parametrize(
    ("ruleset", "message"),
    [
        pytest.param("{", r"invalid JSON", id="not-json"),
        pytest.param('{"name": "main"}', r"no readable rules", id="no-rules"),
        pytest.param(
            '{"rules": [{"type": "required_status_checks", "parameters": {}}]}',
            r"no readable rules",
            id="no-check-list",
        ),
        pytest.param(
            '{"rules": [{"type": "required_status_checks", "parameters": '
            '{"required_status_checks": [{"integration_id": 1}]}}]}',
            r"no readable rules",
            id="check-without-context",
        ),
        pytest.param(
            '{"rules": [{"type": "deletion"}]}',
            r"requires no status check",
            id="no-required-checks-rule",
        ),
        pytest.param(
            '{"rules": [{"type": "required_status_checks", "parameters": '
            '{"required_status_checks": []}}]}',
            r"requires no status check",
            id="empty-contexts",
        ),
    ],
)
def test_ruleset_contexts_unreadable_ruleset_fails(
    make_root: MakeRoot, ruleset: str, message: str
) -> None:
    findings = ruleset_context_findings(make_root(ruleset))

    assert len(findings) == 1
    assert findings[0].startswith(RULESET)
    assert re.search(message, findings[0])


@pytest.mark.parametrize(
    ("workflow", "message"),
    [
        pytest.param(
            "on: pull_request\njobs:\n  docs:\n    name: Lint Docs\n",
            "'Docs Build' is not a job that runs on every pull request",
            id="no-such-job",
        ),
        pytest.param(
            "on:\n  pull_request:\n    paths: [docs/**]\n"
            "jobs:\n  docs:\n    name: Docs Build\n",
            "'Docs Build' is not a job that runs on every pull request",
            id="path-filtered",
        ),
        pytest.param(
            "on: pull_request\njobs:\n  docs:\n    name: Docs Build\n"
            "    if: github.event_name == 'push'\n",
            "'Docs Build' is a job whose `if:` or `needs:` can skip it",
            id="skippable-if",
        ),
        pytest.param(
            "on: pull_request\njobs:\n  docs:\n    name: Docs Build\n    needs: lint\n"
            + FAIL_ON_LINT,
            "'Docs Build' is a job whose `if:` or `needs:` can skip it",
            id="unguarded-needs",
        ),
        pytest.param(
            "on: pull_request\njobs:\n  docs:\n    name: Docs Build\n"
            "    needs: lint\n    if: always() # also on failure\n"
            + FAIL_ON_LINT
            + "  again:\n    name: Docs Build\n    if: github.actor == 'me'\n",
            "'Docs Build' is a job whose `if:` or `needs:` can skip it",
            id="duplicate-name-skippable-wins",
        ),
    ],
)
def test_ruleset_contexts_unrunnable_context_fails(
    make_root: MakeRoot, workflow: str, message: str
) -> None:
    findings = ruleset_context_findings(make_root(_ruleset("Docs Build"), workflow))

    assert findings == [f"{RULESET}: required context {message}"]


def _fail_on_lint_with(old: str, new: str) -> str:
    assert old in FAIL_ON_LINT
    return FAIL_ON_LINT.replace(old, new)


def _with_step_key(line: str) -> str:
    """FAIL_ON_LINT with one more key on its step, before ``env:``."""
    return _fail_on_lint_with("        env:\n", f"        {line}\n        env:\n")


def _coverage_workflow(steps: str, needs: str = "lint") -> str:
    """A workflow whose required ``Coverage`` job needs ``lint`` under a guard."""
    return (
        "on: pull_request\njobs:\n  lint:\n    name: Lint\n"
        "  build:\n    name: Build\n"
        "  coverage:\n    name: Coverage\n    if: ${{ !cancelled() }}\n"
        f"    needs: {needs}\n{steps}"
    )


@pytest.mark.parametrize(
    ("steps", "needs"),
    [
        pytest.param(FAIL_ON_LINT, "lint", id="coverage-shape"),
        pytest.param(
            "    steps:\n      - if: needs.lint.result != 'success'\n"
            "        run: exit 1\n",
            "lint",
            id="step-if-not-success",
        ),
        pytest.param(
            "    steps:\n      - name: Fail\n"
            "        if: ${{ needs.lint.result != 'success' || "
            "needs.build.result != 'success' }}\n"
            '        run: |\n          echo failed: "$X" >&2\n          exit 1\n',
            "[lint, build]",
            id="step-if-either-not-success",
        ),
        pytest.param(
            '    steps:\n      - run: \'[ "${{ needs.lint.result }}" = success ] '
            "|| exit 1'\n",
            "lint",
            id="inline-expression",
        ),
        pytest.param(
            "    env:\n      R: ${{ needs.lint.result }}\n"
            "    steps:\n      - run: '[[ $R != success ]] && exit 3'\n",
            "lint",
            id="not-success-and-exit",
        ),
        pytest.param(
            _with_step_key("if: success()"),
            "lint",
            id="step-if-success",
        ),
        pytest.param(
            FAIL_ON_LINT.replace(
                "        run: |\n", "        run: |\n          echo 'checking lint'\n"
            ),
            "lint",
            id="echo-before-the-check",
        ),
        pytest.param(
            "    env:\n      LINT_RESULT: ${{ needs.lint.result }}\n"
            "    steps:\n      - uses: actions/checkout@v7\n"
            '      - if: always()\n        run: \'[ "${LINT_RESULT}" = success ] '
            "|| exit 2'\n",
            "lint",
            id="job-env-and-guarded-step",
        ),
        pytest.param(
            FAIL_ON_LINT + "      - env:\n          B: ${{ needs.build.result }}\n"
            "        run: |\n"
            '          if [[ "${B}" != success ]]; then  # the build\n'
            "            exit 1\n          fi\n          echo done\n",
            "\n      - lint\n      - build",
            id="block-list-one-step-each",
        ),
    ],
)
def test_ruleset_contexts_needs_job_failing_on_its_own_passes(
    make_root: MakeRoot, steps: str, needs: str
) -> None:
    root = make_root(_ruleset("Coverage"), _coverage_workflow(steps, needs))

    assert ruleset_context_findings(root) == []


@pytest.mark.parametrize(
    ("steps", "needs", "unfailed"),
    [
        pytest.param("", "lint", "lint", id="no-steps"),
        pytest.param(
            "    uses: org/repo/.github/workflows/x.yml@main\n",
            "lint",
            "lint",
            id="reusable-workflow-call",
        ),
        pytest.param(
            _fail_on_lint_with("            exit 1\n", ""),
            "lint",
            "lint",
            id="no-exit",
        ),
        pytest.param(
            _fail_on_lint_with("exit 1", "exit 0"),
            "lint",
            "lint",
            id="exit-zero",
        ),
        pytest.param(
            _fail_on_lint_with('!= "success"', '= "failure"'),
            "lint",
            "lint",
            id="failure-only-lets-cancelled-pass",
        ),
        pytest.param(
            _fail_on_lint_with('[ "$LINT_RESULT"', '[ "$OTHER"'),
            "lint",
            "lint",
            id="result-variable-unused",
        ),
        pytest.param(
            _fail_on_lint_with("needs.lint.result", "needs.build.result"),
            "lint",
            "lint",
            id="other-job-result",
        ),
        pytest.param(
            _with_step_key("if: failure()"), "lint", "lint", id="step-if-skips-it"
        ),
        pytest.param(
            "    steps:\n      - if: needs.lint.result == 'failure'\n"
            "        run: exit 1\n",
            "lint",
            "lint",
            id="step-if-failure-only",
        ),
        pytest.param(
            "    steps:\n      - if: needs.lint.result != 'success' && "
            "github.event_name == 'push'\n        run: exit 1\n",
            "lint",
            "lint",
            id="step-if-extra-condition",
        ),
        pytest.param(
            _with_step_key("continue-on-error: true"),
            "lint",
            "lint",
            id="continue-on-error",
        ),
        pytest.param(
            FAIL_ON_LINT, "[lint, build]", "build", id="second-need-unchecked"
        ),
        # The three false passes a review reproduced on a copy of ci.yml.
        pytest.param(
            _fail_on_lint_with(
                "            exit 1\n          fi\n",
                "          fi\n          uv run coverage report || exit 1\n",
            ),
            "lint",
            "lint",
            id="exit-on-another-command",
        ),
        pytest.param(
            _fail_on_lint_with(
                "            exit 1\n", '            echo "would exit 1"\n'
            ),
            "lint",
            "lint",
            id="exit-inside-a-string",
        ),
        pytest.param(
            "    env:\n      LINT_RESULT: ${{ needs.lint.result }}\n    steps:\n"
            '      - run: ( if [ "$LINT_RESULT" != "success" ]; then exit 1; fi ) '
            "|| echo ignored\n",
            "lint",
            "lint",
            id="exit-inside-a-subshell",
        ),
        pytest.param(
            _fail_on_lint_with("        run: |\n", "        run: |\n          (\n")
            + "          ) || echo ignored\n",
            "lint",
            "lint",
            id="block-inside-a-subshell",
        ),
        pytest.param(
            _fail_on_lint_with(
                "        run: |\n", "        run: |\n          exit 0\n"
            ),
            "lint",
            "lint",
            id="exit-zero-first",
        ),
        pytest.param(
            _fail_on_lint_with('!= "success" ]', '= "success" ]'),
            "lint",
            "lint",
            id="inverted-if-comparison",
        ),
        pytest.param(
            "    env:\n      R: ${{ needs.lint.result }}\n"
            "    steps:\n      - run: '[ \"$R\" != success ] || exit 1'\n",
            "lint",
            "lint",
            id="inverted-guard-comparison",
        ),
        pytest.param(
            "    steps:\n      - if: contains(needs.*.result, 'failure')\n"
            "        run: exit 1\n",
            "lint",
            "lint",
            id="contains-needs-star",
        ),
        pytest.param(
            "    steps:\n      - if: needs.*.result != 'success'\n        run: exit 1\n",
            "lint",
            "lint",
            id="needs-star-result",
        ),
        pytest.param(
            "    env:\n      LINT_RESULT: ${{ needs.lint.result }}\n"
            + _fail_on_lint_with(
                "          LINT_RESULT: ${{ needs.lint.result }}\n",
                "          LINT_RESULT: success\n",
            ),
            "lint",
            "lint",
            id="step-env-overrides-job-env",
        ),
        pytest.param(
            _fail_on_lint_with("        run: |\n", "        run: >\n"),
            "lint",
            "lint",
            id="folded-run",
        ),
        pytest.param(
            _fail_on_lint_with('echo "::error::', 'echo "$(date) ::error::'),
            "lint",
            "lint",
            id="echo-with-command-substitution",
        ),
    ],
)
def test_ruleset_contexts_needs_job_not_failing_on_its_own_fails(
    make_root: MakeRoot, steps: str, needs: str, unfailed: str
) -> None:
    root = make_root(_ruleset("Coverage"), _coverage_workflow(steps, needs))

    assert ruleset_context_findings(root) == [
        (
            f"{RULESET}: required context 'Coverage' needs {unfailed!r}, but no step "
            f"fails when `needs.{unfailed}.result` is not 'success'; {SHAPES_HINT}"
        )
    ]


def test_ruleset_contexts_unguarded_needs_without_failing_step_reports_both(
    make_root: MakeRoot,
) -> None:
    workflow = (
        "on: pull_request\njobs:\n  docs:\n    name: Docs Build\n    needs: lint\n"
    )

    assert ruleset_context_findings(make_root(_ruleset("Docs Build"), workflow)) == [
        (
            f"{RULESET}: required context 'Docs Build' is a job whose `if:` or `needs:` "
            "can skip it"
        ),
        (
            f"{RULESET}: required context 'Docs Build' needs 'lint', but no step fails "
            f"when `needs.lint.result` is not 'success'; {SHAPES_HINT}"
        ),
    ]


@pytest.mark.parametrize(
    ("steps", "needs", "message"),
    [
        pytest.param(FAIL_ON_LINT, "{lint: x}", r"expected sequence", id="needs-map"),
        pytest.param(FAIL_ON_LINT, "[]", r"cannot read `needs: ", id="needs-empty"),
        pytest.param(
            _fail_on_lint_with(
                "        env:\n          LINT_RESULT: ${{ needs.lint.result }}\n",
                "        env: [x]\n",
            ),
            "lint",
            r"env: expected mapping",
            id="env-sequence",
        ),
        pytest.param(
            "    steps:\n      - run: [exit, 1]\n",
            "lint",
            r"run: expected string",
            id="run-sequence",
        ),
    ],
)
def test_ruleset_contexts_unreadable_needs_job_fails_closed(
    make_root: MakeRoot, steps: str, needs: str, message: str
) -> None:
    root = make_root(_ruleset("Coverage"), _coverage_workflow(steps, needs))

    with pytest.raises(UnreadableYamlError, match=message):
        ruleset_context_findings(root)


@pytest.mark.parametrize(
    ("steps", "needs"),
    [
        pytest.param("", "lint", id="no-failing-step"),
        pytest.param(FAIL_ON_LINT, "{lint: x}", id="unreadable-needs"),
        pytest.param(
            "    steps:\n      - run: if true; then\n          exit 1\n          fi\n",
            "lint",
            id="multi-line-plain-run",
        ),
    ],
)
def test_ruleset_contexts_needs_job_not_required_is_not_read(
    make_root: MakeRoot, steps: str, needs: str
) -> None:
    root = make_root(_ruleset("Lint"), _coverage_workflow(steps, needs))

    assert ruleset_context_findings(root) == []


def test_ruleset_contexts_inline_env_uses_same_failure_policy(
    make_root: MakeRoot,
) -> None:
    steps = _fail_on_lint_with(
        "        env:\n          LINT_RESULT: ${{ needs.lint.result }}\n",
        "        env: {LINT_RESULT: '${{ needs.lint.result }}'}\n",
    )
    root = make_root(_ruleset("Coverage"), _coverage_workflow(steps, "lint"))
    assert ruleset_context_findings(root) == []
