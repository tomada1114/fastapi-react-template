"""(e) Every label the repository applies is declared exactly once in labels.yml.

`just labels` creates only what ``.github/labels.yml`` declares, so a label
applied anywhere else and missing there fails the write that applies it (or
GitHub creates it with no colour or description); one declared twice, case
aside (GitHub compares label names case-insensitively), is two conflicting
definitions. Applied labels are read from ``.github/workflows/pr-label.yml``
(``label=<name>`` and literal ``--add-label``/``--label`` values in its
``run:`` steps), each issue form's top-level ``labels`` and each Markdown issue
template's front-matter ``labels``, and each ``.github/dependabot.yml``
update's ``labels`` (Dependabot's default ``dependencies`` when an entry sets
none). With more than one update entry, Dependabot adds an ecosystem label
(``github_actions``, ``python``) to any entry that sets no ``labels``, which
this check cannot see, so each entry must then declare ``labels`` explicitly.
Applied and declared names are compared case-insensitively, as GitHub does.

Each of those files is optional — an app may delete pr-label.yml — but one that
is present and cannot be read fails closed: a pr-label.yml with no label this
check can read, or a Markdown template without front matter.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.harness._workflows import jobs, read_workflow, steps
from tests.harness._yaml import (
    UnreadableYamlError,
    as_mapping,
    as_sequence,
    block_text,
    load_yaml,
    scalar,
    scalar_list,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    type MakeRoot = Callable[[dict[str, str]], Path]

REPO_ROOT = Path(__file__).resolve().parents[2]
LABELS = ".github/labels.yml"
PR_LABEL = ".github/workflows/pr-label.yml"
ISSUE_FORMS = ".github/ISSUE_TEMPLATE"
DEPENDABOT = ".github/dependabot.yml"
DEPENDABOT_DEFAULT = "dependencies"

_LABEL_VALUE = r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s;|&)]+)"
_APPLIED = re.compile(rf"(?:(?<![\w-])label=|--(?:add-)?label(?:=|\s+)){_LABEL_VALUE}")


def _load_sync_labels() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sync_labels", REPO_ROOT / "scripts" / "sync_labels.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules while the class body runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync_labels = _load_sync_labels()


def _pr_label_labels(root: Path) -> list[tuple[str, str]]:
    path = root / PR_LABEL
    if not path.is_file():
        return []
    top = read_workflow(path)
    applied = [
        (PR_LABEL, match["value"].strip("\"'"))
        for job in jobs(top, path).values()
        for step in steps(job, path)
        if "run" in step
        for match in _APPLIED.finditer(block_text(step["run"]))
        if "$" not in match["value"]
    ]
    if not applied:
        msg = f"{PR_LABEL}: no `label=<name>` or literal `--add-label` found to check"
        raise UnreadableYamlError(msg)
    return applied


def _front_matter(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        end = lines.index("---", 1) if lines and lines[0] == "---" else -1
    except ValueError:
        end = -1
    if end < 0:
        msg = f"{path.name}: an issue template without a --- front matter block"
        raise UnreadableYamlError(msg)
    return "\n".join(lines[1:end])


def _issue_form_labels(root: Path) -> list[tuple[str, str]]:
    applied: list[tuple[str, str]] = []
    templates = (root / ISSUE_FORMS).glob("*")
    for path in sorted(p for p in templates if p.suffix in {".yml", ".yaml", ".md"}):
        text = _front_matter(path) if path.suffix == ".md" else None
        top = as_mapping(load_yaml(path, text=text), str(path))
        if "labels" in top:
            relative = path.relative_to(root).as_posix()
            applied.extend(
                (relative, label) for label in scalar_list(top["labels"], path)
            )
    return applied


def _dependabot_labels(root: Path) -> list[tuple[str, str]]:
    path = root / DEPENDABOT
    if not path.is_file():
        return []
    top = as_mapping(load_yaml(path), str(path))
    applied: list[tuple[str, str]] = []
    for index, item in enumerate(
        as_sequence(top.get("updates", []), f"{path}: updates")
    ):
        update = as_mapping(item, f"{path}: updates[{index}]")
        labels = (
            scalar_list(update["labels"], path)
            if "labels" in update
            else [DEPENDABOT_DEFAULT]
        )
        applied.extend((DEPENDABOT, label) for label in labels)
    return applied


def _dependabot_implicit_label_findings(root: Path) -> list[str]:
    path = root / DEPENDABOT
    if not path.is_file():
        return []
    top = as_mapping(load_yaml(path), str(path))
    updates = [
        as_mapping(item, f"{path}: updates[{index}]")
        for index, item in enumerate(
            as_sequence(top.get("updates", []), f"{path}: updates")
        )
    ]
    if len(updates) <= 1:  # one ecosystem gets no ecosystem label added
        return []
    return [
        f"{DEPENDABOT}: the {scalar(update.get('package-ecosystem', '?'))!r} "
        "update sets no `labels:`; with more than one ecosystem Dependabot adds an "
        "undeclared ecosystem label"
        for update in updates
        if "labels" not in update
    ]


def label_findings(root: Path) -> list[str]:
    """Return each applied label not declared, and each label declared twice."""
    path = root / LABELS
    if not path.is_file():
        return [f"{LABELS} is missing"]
    try:
        declared = [
            label.name
            for label in sync_labels.parse_labels(path.read_text(encoding="utf-8"))
        ]
    except sync_labels.LabelsFileError as exc:
        return [f"{LABELS}: {exc}"]
    counts = Counter(name.casefold() for name in declared)
    findings = [
        f"{LABELS}: {sorted(n for n in declared if n.casefold() == key)} name one "
        "label (GitHub ignores case); declare it once"
        for key in sorted(key for key, count in counts.items() if count > 1)
    ]
    applied = [
        *_pr_label_labels(root),
        *_issue_form_labels(root),
        *_dependabot_labels(root),
    ]
    findings.extend(
        f"{where}: applies label {label!r}, which {LABELS} does not declare"
        for where, label in sorted(set(applied))
        if label.casefold() not in counts
    )
    findings.extend(_dependabot_implicit_label_findings(root))
    return findings


# --- the repository ---


def test_labels_applied_on_repository_are_declared_once() -> None:
    assert label_findings(REPO_ROOT) == []


# --- fixtures ---

LABELS_TEXT = """\
- name: bug
  color: d73a4a
  description: "Broken."
- name: dependencies
  color: 0366d6
  description: "Bumps."
- name: "priority: P2"
  color: fbca04
  description: "Normal."
"""

PR_LABEL_TEXT = """\
on: pull_request
jobs:
  label:
    steps:
      - name: Apply label
        run: |
          case "$type" in
            fix) label=bug ;;
            {extra}
          esac
          gh pr edit "$PR_NUMBER" --add-label "$label"
"""


@pytest.fixture
def make_root(tmp_path: Path) -> MakeRoot:
    def make(files: dict[str, str]) -> Path:
        files = {LABELS: LABELS_TEXT, **files}
        for relative, text in files.items():
            (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / relative).write_text(text, encoding="utf-8")
        return tmp_path

    return make


def test_label_findings_declared_labels_pass(make_root: MakeRoot) -> None:
    root = make_root(
        {
            PR_LABEL: PR_LABEL_TEXT.format(extra="deps) label=dependencies ;;"),
            f"{ISSUE_FORMS}/bug.yml": 'name: Bug\nlabels: ["bug", "priority: P2"]\n',
            f"{ISSUE_FORMS}/config.yml": "blank_issues_enabled: false\n",
            f"{ISSUE_FORMS}/task.md": "---\nname: Task\nlabels: 'BUG, Priority: P2'\n---\nBody\n",
            f"{ISSUE_FORMS}/blank.md": "---\nname: Blank\nlabels: ''\n---\n",
            DEPENDABOT: "version: 2\nupdates:\n  - package-ecosystem: pip\n",
        }
    )

    assert label_findings(root) == []


def test_label_findings_without_pr_label_workflow_passes(make_root: MakeRoot) -> None:
    root = make_root({DEPENDABOT: "version: 2\nupdates:\n  - package-ecosystem: pip\n"})

    assert not (root / PR_LABEL).exists()
    assert label_findings(root) == []


@pytest.mark.parametrize(
    ("files", "finding"),
    [
        pytest.param(
            {PR_LABEL: PR_LABEL_TEXT.format(extra="feat) label=enhancement ;;")},
            f"{PR_LABEL}: applies label 'enhancement', which {LABELS} does not declare",
            id="pr-label-case-arm",
        ),
        pytest.param(
            {
                PR_LABEL: PR_LABEL_TEXT.format(
                    extra='docs) gh pr edit 1 --add-label "documentation" ;;'
                )
            },
            f"{PR_LABEL}: applies label 'documentation', which {LABELS} does not "
            "declare",
            id="pr-label-literal-add-label",
        ),
        pytest.param(
            {f"{ISSUE_FORMS}/feature.yml": "name: Feature\nlabels: [enhancement]\n"},
            f"{ISSUE_FORMS}/feature.yml: applies label 'enhancement', which {LABELS} "
            "does not declare",
            id="issue-form-flow-list",
        ),
        pytest.param(
            {f"{ISSUE_FORMS}/feature.yml": "name: F\nlabels:\n  - triage\n"},
            f"{ISSUE_FORMS}/feature.yml: applies label 'triage', which {LABELS} does "
            "not declare",
            id="issue-form-block-list",
        ),
        pytest.param(
            {f"{ISSUE_FORMS}/feature.yml": "name: F\nlabels: bug, triage\n"},
            f"{ISSUE_FORMS}/feature.yml: applies label 'triage', which {LABELS} does "
            "not declare",
            id="issue-form-comma-string",
        ),
        pytest.param(
            {f"{ISSUE_FORMS}/task.md": "---\nname: Task\nlabels: triage\n---\nBody\n"},
            f"{ISSUE_FORMS}/task.md: applies label 'triage', which {LABELS} does "
            "not declare",
            id="markdown-template",
        ),
        pytest.param(
            {
                DEPENDABOT: "version: 2\nupdates:\n  - package-ecosystem: pip\n"
                "    labels: [python]\n"
            },
            f"{DEPENDABOT}: applies label 'python', which {LABELS} does not declare",
            id="dependabot-labels",
        ),
        pytest.param(
            {LABELS: LABELS_TEXT.replace("dependencies", "deps")},
            f"{DEPENDABOT}: applies label 'dependencies', which {LABELS} does not "
            "declare",
            id="dependabot-default",
        ),
        pytest.param(
            {
                LABELS: LABELS_TEXT
                + '- name: Bug\n  color: d73a4a\n  description: "x"\n'
            },
            f"{LABELS}: ['Bug', 'bug'] name one label (GitHub ignores case); "
            "declare it once",
            id="declared-twice-by-case",
        ),
        pytest.param(
            {
                LABELS: LABELS_TEXT
                + '- name: bug\n  color: d73a4a\n  description: "x"\n'
            },
            f"{LABELS}: duplicated label names: ['bug']",
            id="declared-twice",
        ),
    ],
)
def test_label_findings_undeclared_or_duplicate_label_fails(
    make_root: MakeRoot, files: dict[str, str], finding: str
) -> None:
    root = make_root(
        {DEPENDABOT: "version: 2\nupdates:\n  - package-ecosystem: pip\n", **files}
    )

    assert label_findings(root) == [finding]


TWO_ECOSYSTEMS = """\
version: 2
updates:
  - package-ecosystem: "github-actions"
    labels: ["dependencies"]
  - package-ecosystem: "uv"
{uv_labels}"""


def test_label_findings_two_ecosystems_with_explicit_labels_pass(
    make_root: MakeRoot,
) -> None:
    root = make_root(
        {DEPENDABOT: TWO_ECOSYSTEMS.format(uv_labels='    labels: ["dependencies"]\n')}
    )

    assert label_findings(root) == []


def test_label_findings_two_ecosystems_one_without_labels_fails(
    make_root: MakeRoot,
) -> None:
    root = make_root({DEPENDABOT: TWO_ECOSYSTEMS.format(uv_labels="")})

    assert label_findings(root) == [
        (
            f"{DEPENDABOT}: the 'uv' update sets no `labels:`; with more than one "
            "ecosystem Dependabot adds an undeclared ecosystem label"
        )
    ]


def test_label_findings_without_labels_file_fails(tmp_path: Path) -> None:
    assert label_findings(tmp_path) == [f"{LABELS} is missing"]


@pytest.mark.parametrize(
    ("files", "message"),
    [
        pytest.param(
            {DEPENDABOT: "version: 2\nupdates:\n  package-ecosystem: pip\n"},
            r"dependabot\.yml: updates: expected sequence",
            id="dependabot-updates-not-a-list",
        ),
        pytest.param(
            {f"{ISSUE_FORMS}/f.yml": "labels:\n  - {bug: triage}\n"},
            r"f\.yml: list\[0\]: expected string",
            id="issue-form-mapping-item",
        ),
        pytest.param(
            {f"{ISSUE_FORMS}/f.yml": "labels: [bug,\n  triage\n"},
            r"f\.yml: while parsing",
            id="issue-form-unclosed-flow-list",
        ),
        pytest.param(
            {f"{ISSUE_FORMS}/task.md": "name: Task\nlabels: triage\n"},
            r"task\.md: an issue template without a --- front matter block",
            id="markdown-template-without-front-matter",
        ),
    ],
)
def test_label_findings_unreadable_file_fails_closed(
    make_root: MakeRoot, files: dict[str, str], message: str
) -> None:
    root = make_root(files)

    with pytest.raises(UnreadableYamlError, match=message):
        label_findings(root)


def test_label_findings_pr_label_without_readable_label_fails_closed(
    make_root: MakeRoot,
) -> None:
    text = PR_LABEL_TEXT.format(extra="").replace("fix) label=bug ;;", "")
    root = make_root({PR_LABEL: text})

    with pytest.raises(UnreadableYamlError, match=r"pr-label\.yml: no `label=<name>`"):
        label_findings(root)


PR_TITLE = ".github/workflows/check-pr-title.yml"


def pr_type_findings(root: Path) -> list[str]:
    """Require every labelled conventional type to pass the title gate."""
    title = root / PR_TITLE
    label = root / PR_LABEL
    if not label.is_file():
        return []
    assert title.is_file(), "PR label workflow needs a title gate"
    accepted: set[str] = set()
    for job in jobs(read_workflow(title), title).values():
        for step in steps(job, title):
            if scalar(step.get("uses", "")).startswith(
                "amannn/action-semantic-pull-request@"
            ):
                inputs = as_mapping(step.get("with", {}), f"{title}: steps.with")
                assert "types" in inputs, "PR title gate must declare types explicitly"
                accepted.update(block_text(inputs["types"]).split())
    assert accepted, "PR title gate has no accepted types"
    labelled = {
        match[1]
        for job in jobs(read_workflow(label), label).values()
        for step in steps(job, label)
        if "run" in step
        for match in re.finditer(
            r"^\s*([a-z][a-z0-9_-]*)\)", block_text(step["run"]), re.MULTILINE
        )
    }
    assert labelled, "PR label workflow has no readable type arms"
    return [
        f"{PR_LABEL}: type {value!r} is rejected by the title gate"
        for value in sorted(labelled - accepted)
    ]


def test_pr_type_findings_repository_types_are_accepted() -> None:
    assert pr_type_findings(REPO_ROOT) == []


def test_pr_type_findings_extra_label_arm_is_rejected(make_root: MakeRoot) -> None:
    root = make_root(
        {
            PR_TITLE: "jobs:\n  title:\n    steps:\n      - uses: amannn/action-semantic-pull-request@pin\n        with:\n          types: |\n            fix\n",
            PR_LABEL: PR_LABEL_TEXT.format(extra="unknown) label=bug ;;"),
        }
    )
    assert pr_type_findings(root) == [
        f"{PR_LABEL}: type 'unknown' is rejected by the title gate"
    ]


@pytest.mark.parametrize(
    "labels", ["[bug,\n  dependencies]", "\n  - bug\n  - dependencies"]
)
def test_label_findings_multiline_sequences_apply_labels(
    make_root: MakeRoot, labels: str
) -> None:
    root = make_root({f"{ISSUE_FORMS}/f.yml": f"labels: {labels}\n"})
    assert label_findings(root) == []
