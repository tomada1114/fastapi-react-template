"""Tests for scripts/apply_ruleset.py and .github/rulesets/main.json.

That every required context is a job each pull request runs, and cannot skip,
is the harness check in tests/harness/test_ruleset_contexts.py.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
RULESET = REPO_ROOT / ".github" / "rulesets" / "main.json"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "apply_ruleset", REPO_ROOT / "scripts" / "apply_ruleset.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


apply_ruleset = _load_module()


def _rule(ruleset: dict[str, Any], rule_type: str) -> dict[str, Any]:
    matches = [rule for rule in ruleset["rules"] if rule["type"] == rule_type]
    assert len(matches) == 1, rule_type
    rule: dict[str, Any] = matches[0]
    return rule


def _required_contexts() -> list[str]:
    ruleset = json.loads(RULESET.read_text(encoding="utf-8"))
    checks = _rule(ruleset, "required_status_checks")["parameters"]
    return [check["context"] for check in checks["required_status_checks"]]


# --- the JSON ---


def test_ruleset_targets_default_branch_with_empty_bypass() -> None:
    ruleset = json.loads(RULESET.read_text(encoding="utf-8"))

    assert ruleset["name"] == "main"
    assert ruleset["target"] == "branch"
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert ruleset["bypass_actors"] == []


def test_ruleset_blocks_deletion_and_force_push_and_requires_pr() -> None:
    ruleset = json.loads(RULESET.read_text(encoding="utf-8"))

    _rule(ruleset, "deletion")
    _rule(ruleset, "non_fast_forward")
    pull_request = _rule(ruleset, "pull_request")["parameters"]
    assert pull_request["required_approving_review_count"] == 0


def test_required_contexts_match_settled_defaults() -> None:
    contexts = _required_contexts()

    assert len(contexts) == len(set(contexts))
    assert set(contexts) == {
        "Lint & Type Check",
        "Coverage",
        "Spell Check",
        "Workflow Security Lint",
        "Validate PR title",
        "Analyze (python)",
        "Analyze (actions)",
        "Dependency Review",
    }
    assert not [c for c in contexts if c.startswith("Test (shard")]


def test_required_contexts_are_pinned_to_github_actions() -> None:
    ruleset = json.loads(RULESET.read_text(encoding="utf-8"))
    checks = _rule(ruleset, "required_status_checks")["parameters"]

    assert [c["integration_id"] for c in checks["required_status_checks"]] == [
        GITHUB_ACTIONS_APP_ID
    ] * len(checks["required_status_checks"])


# --- the script ---

GITHUB_ACTIONS_APP_ID = 15368
PLAN_ERROR = (
    "gh: Upgrade to GitHub Pro or make this repository public to enable this "
    "feature. (HTTP 403)"
)


def _entry(ruleset_id: int, name: str, **overrides: str) -> dict[str, Any]:
    return {
        "id": ruleset_id,
        "name": name,
        "source_type": "Repository",
        "target": "branch",
        **overrides,
    }


class FakeGh:
    """Stands in for `subprocess.run` at the gh boundary, recording each argv.

    ``fail`` maps a substring of the joined argv to the stderr of a failing
    run; ``stdout`` maps one to the stdout of a successful run.
    """

    def __init__(self, existing: list[dict[str, Any]]) -> None:
        self.pages: list[list[dict[str, Any]]] = [existing]
        self.fail: dict[str, str] = {}
        self.stdout: dict[str, str] = {}
        self.calls: list[list[str]] = []
        self.inputs: list[str | None] = []

    def __call__(
        self, argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        stdin = kwargs.get("input")
        self.inputs.append(stdin if isinstance(stdin, str) else None)
        joined = " ".join(argv)
        for marker, stderr in self.fail.items():
            if marker in joined:
                return subprocess.CompletedProcess(argv, 1, "", stderr)
        for marker, stdout in self.stdout.items():
            if marker in joined:
                return subprocess.CompletedProcess(argv, 0, stdout, "")
        if argv[1:3] == ["repo", "view"]:
            return subprocess.CompletedProcess(argv, 0, "acme/widget\n", "")
        if "--method" in argv:
            return subprocess.CompletedProcess(argv, 0, '{"id": 42}', "")
        return subprocess.CompletedProcess(argv, 0, json.dumps(self.pages), "")


@pytest.fixture
def fake_gh(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[list[dict[str, Any]]], FakeGh]:
    def make(existing: list[dict[str, Any]]) -> FakeGh:
        fake = FakeGh(existing)
        monkeypatch.setattr(apply_ruleset.subprocess, "run", fake)
        return fake

    return make


def _methods(fake: FakeGh) -> list[str]:
    return [
        argv[argv.index("--method") + 1] for argv in fake.calls if "--method" in argv
    ]


def test_main_creates_ruleset_when_none_has_its_name(
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh],
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = fake_gh([_entry(7, "other")])

    code = apply_ruleset.main([], ruleset_file=RULESET)

    assert code == 0
    assert _methods(fake) == ["POST"]
    assert fake.calls[-1][4] == "repos/acme/widget/rulesets"
    assert json.loads(fake.inputs[-1] or "") == json.loads(RULESET.read_text())
    assert "created: ruleset 'main' id 42" in capsys.readouterr().out


def test_main_lists_only_repository_rulesets(
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh],
) -> None:
    fake = fake_gh([])

    apply_ruleset.main(["--repo", "o/r"], ruleset_file=RULESET)

    assert "repos/o/r/rulesets?includes_parents=false" in fake.calls[0]


def test_main_updates_existing_ruleset_by_id(
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh],
) -> None:
    fake = fake_gh([_entry(7, "other"), _entry(9, "main")])

    code = apply_ruleset.main(["--repo", "o/r"], ruleset_file=RULESET)

    assert code == 0
    assert _methods(fake) == ["PUT"]
    assert fake.calls[-1][4] == "repos/o/r/rulesets/9"
    assert not [argv for argv in fake.calls if argv[1:3] == ["repo", "view"]]


def test_main_updates_match_across_pages(
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh],
) -> None:
    fake = fake_gh([_entry(1, "a")])
    fake.pages.append([_entry(5, "main")])

    apply_ruleset.main(["--repo", "o/r"], ruleset_file=RULESET)

    assert fake.calls[-1][4] == "repos/o/r/rulesets/5"


@pytest.mark.parametrize(
    "entry",
    [
        _entry(3, "main", source_type="Organization"),
        _entry(3, "main", target="tag"),
    ],
    ids=["org-ruleset", "tag-ruleset"],
)
def test_main_creates_when_same_name_is_not_a_repository_branch_ruleset(
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh], entry: dict[str, Any]
) -> None:
    fake = fake_gh([entry])

    apply_ruleset.main(["--repo", "o/r"], ruleset_file=RULESET)

    assert _methods(fake) == ["POST"]


@pytest.mark.parametrize("ruleset_id", [None, 3], ids=["create", "update"])
def test_upsert_command_never_deletes(ruleset_id: int | None) -> None:
    command = apply_ruleset.upsert_command("o/r", ruleset_id)

    assert "DELETE" not in [part.upper() for part in command]


def test_main_never_issues_delete(
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh],
) -> None:
    fake = fake_gh([_entry(1, "main"), _entry(2, "main-old")])

    apply_ruleset.main([], ruleset_file=RULESET)

    assert all("DELETE" not in [p.upper() for p in argv] for argv in fake.calls)


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        ('{"name": "main",}', r"invalid JSON"),
        ("[]", r"top level must be a JSON object"),
        ('{"name": "main", "target": "branch"}', r"missing required keys"),
        (
            '{"name": "", "target": "b", "enforcement": "a", "conditions": {}, "rules": []}',
            r"name must be a non-empty string",
        ),
    ],
    ids=["trailing-comma", "not-object", "missing-keys", "empty-name"],
)
def test_main_rejects_bad_file_before_any_gh_call(
    tmp_path: Path,
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh],
    capsys: pytest.CaptureFixture[str],
    content: str,
    detail: str,
) -> None:
    fake = fake_gh([])
    path = tmp_path / "main.json"
    path.write_text(content, encoding="utf-8")

    code = apply_ruleset.main([], ruleset_file=path)

    err = capsys.readouterr().err
    assert code == 1
    assert fake.calls == []
    assert re.search(rf"^ERR_RULESET_FILE: .*{detail}", err, re.MULTILINE)
    assert "\nExpected: " in err
    assert "\nNext: " in err


def test_main_reports_missing_file(
    tmp_path: Path,
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh],
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = fake_gh([])

    code = apply_ruleset.main([], ruleset_file=tmp_path / "absent.json")

    assert code == 1
    assert fake.calls == []
    assert capsys.readouterr().err.startswith("ERR_RULESET_FILE: ")


@pytest.mark.parametrize(
    ("marker", "stderr", "expected"),
    [
        (
            "--method POST",
            "gh: Forbidden (HTTP 403)",
            ("ERR_RULESET_GH", "Next: a repository admin runs `just ruleset`"),
        ),
        (
            "--method PUT",
            "gh: Not Found (HTTP 404)",
            ("ERR_RULESET_GH", "Next: a repository admin runs `just ruleset`"),
        ),
        (
            "includes_parents",
            "gh: Forbidden (HTTP 403)",
            ("ERR_RULESET_GH", "Next: a repository admin runs `just ruleset`"),
        ),
        (
            "--method",
            "gh: Validation Failed (HTTP 422)",
            ("ERR_RULESET_GH", "Next: check `gh auth status`"),
        ),
        (
            "--method",
            PLAN_ERROR,
            (
                "ERR_RULESET_PLAN_UNSUPPORTED",
                "Next: make the repository public or upgrade",
            ),
        ),
        (
            "includes_parents",
            PLAN_ERROR,
            (
                "ERR_RULESET_PLAN_UNSUPPORTED",
                "Next: make the repository public or upgrade",
            ),
        ),
    ],
    ids=[
        "post-403",
        "put-404",
        "list-403",
        "upsert-422",
        "plan-on-upsert",
        "plan-on-list",
    ],
)
def test_main_reports_gh_failures(
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh],
    capsys: pytest.CaptureFixture[str],
    marker: str,
    stderr: str,
    expected: tuple[str, str],
) -> None:
    code, next_line = expected
    existing = [_entry(9, "main")] if "PUT" in marker else []
    fake = fake_gh(existing)
    fake.fail[marker] = stderr

    exit_code = apply_ruleset.main(["--repo", "o/r"], ruleset_file=RULESET)

    err = capsys.readouterr().err
    assert exit_code == 1
    assert err.startswith(f"{code}: ")
    assert "\nExpected: " in err
    assert next_line in err


@pytest.mark.parametrize(
    ("marker", "stdout", "detail"),
    [
        ("repo view", "\n", r"returned no owner/repo"),
        ("repo view", "acme/\n", r"returned no owner/repo"),
        ("includes_parents", "<html>", r"output is not JSON"),
        ("includes_parents", '{"message": "x"}', r"not a JSON array of pages"),
        ("--method", "oops", r"output is not JSON"),
    ],
    ids=[
        "empty-repo",
        "no-repo-name",
        "list-not-json",
        "list-not-array",
        "upsert-not-json",
    ],
)
def test_main_reports_unexpected_gh_output(
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh],
    capsys: pytest.CaptureFixture[str],
    marker: str,
    stdout: str,
    detail: str,
) -> None:
    fake = fake_gh([])
    fake.stdout[marker] = stdout

    code = apply_ruleset.main([], ruleset_file=RULESET)

    err = capsys.readouterr().err
    assert code == 1
    assert re.search(rf"^ERR_RULESET_GH: .*{detail}", err, re.MULTILINE)
    assert "\nExpected: " in err
    assert "\nNext: check `gh auth status`" in err


def test_main_reports_gh_missing_from_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(apply_ruleset.subprocess, "run", missing)

    code = apply_ruleset.main([], ruleset_file=RULESET)

    err = capsys.readouterr().err
    assert code == 1
    assert err.startswith("ERR_RULESET_GH: gh not found on PATH")
    assert "\nExpected: " in err
    assert "\nNext: " in err


def test_main_reports_gh_failure_resolving_repo(
    fake_gh: Callable[[list[dict[str, Any]]], FakeGh],
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = fake_gh([])
    fake.fail["repo view"] = "not a git repository"

    code = apply_ruleset.main([], ruleset_file=RULESET)

    err = capsys.readouterr().err
    assert code == 1
    assert "ERR_RULESET_GH: gh repo view" in err
    assert "Next: check `gh auth status`" in err
    assert len(fake.calls) == 1
