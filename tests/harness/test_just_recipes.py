"""(c) Every ``just <recipe>`` the agent- and human-facing documents name exists.

A renamed or removed recipe must not leave a document pointing a reader at
nothing. Read: every top-level ``*.md`` (AGENTS.md, CLAUDE.md,
README.md, CONTRIBUTING.md, SECURITY.md, ...), ``docs/**/*.md``
but the ADRs and the roadmap, the skills, the agent definitions
(``.claude/agents/*.md``, ``.codex/agents/*.toml``), everything under
``.github/`` (composite actions included), ``.pre-commit-config.yaml``, and the
repository and skill scripts (``scripts/*.py``,
``.agents/skills/*/scripts/*.py``; not their tests). Each is optional: a missing
file or directory names nothing, and a present file that is not UTF-8 fails the
check.

Not read, because they record intent or history rather than instruct:
the ADRs (``docs/architecture/adr/**``, which may decide to add or drop a
recipe), the roadmap (``docs/architecture/roadmap.md``), and the product and
planning documents (``docs/product/**``), whose "done when" names a recipe that
does not exist yet. ``.devcontainer/devcontainer.json`` is not read either: it
is JSON with comments, which no stdlib parser reads.

Only code is read, so English prose ("just to be safe") never counts:

- in Markdown and in YAML or TOML text (issue forms and comments render as
  Markdown), the inline code spans and the lines of a ``bash``/``sh``/
  ``shell``/``zsh`` fence. A fence whose lines carry a ``$ `` prompt counts only
  those lines, the rest being output; a ``console``, ``text``, or ``output``
  fence is output and is skipped; any other fence (a bare one holding a prompt
  template, a python one) counts only its spans;
- in a workflow or a composite action, also the commands of each ``run:``;
- in a script, the code spans inside string literals and comments, which is
  how it names a recipe to a reader.

Within that code only ``just`` in a command's position counts: at the start
(after a ``$ `` prompt, ``NAME=value`` assignments, or ``uvx [--from X]``), or
after ``&&``, ``||``, ``;``, ``|``, ``(``, or ``$(``; never inside quotes or
after an unquoted ``#``. It is then followed by a recipe name, so
``just --list`` and the placeholder ``just <recipe>`` name nothing and
arguments (``just run todo list``) are ignored. ``just -f``/``--justfile``/
``-d``/``--working-directory`` points at another justfile, which this check
cannot read, so that form is reported rather than skipped.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import textwrap
import tokenize
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.harness._shell import split_comment
from tests.harness._workflows import jobs, read_workflow, steps
from tests.harness._yaml import block_text, scalar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    type MakeRoot = Callable[[dict[str, str]], Path]

REPO_ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = "justfile"
DOCUMENT_GLOBS = (
    "*.md",
    "docs/**/*.md",
    ".agents/skills/**/*.md",
    ".claude/agents/**/*.md",
    ".codex/agents/**/*.toml",
    ".github/**/*.md",
    ".github/**/*.yml",
    ".github/**/*.yaml",
    ".pre-commit-config.yaml",
    "scripts/*.py",
    ".agents/skills/*/scripts/*.py",
)
# Intent or history, not instructions: see the module docstring.
UNREAD_GLOBS = (
    "docs/architecture/adr/**/*",
    "docs/architecture/roadmap.md",
    "docs/product/**/*",
)
WORKFLOW_PARENT = ".github/workflows"
ACTIONS_DIR = ".github/actions"
ACTION_FILES = frozenset({"action.yml", "action.yaml"})
# Column-0 justfile lines that look like a recipe header but are not one.
NOT_RECIPES = frozenset({"set", "export", "unexport", "import", "mod", "alias"})

_NAME = r"[A-Za-z_][A-Za-z0-9_-]*"
_RECIPE_HEADER = re.compile(rf"^@?(?P<name>{_NAME})(?:[ \t]+[^:]*?)?[ \t]*:(?!=)")
_ALIAS = re.compile(rf"^alias[ \t]+(?P<name>{_NAME})[ \t]*:=")
_CALL = re.compile(rf"^just\s+(?P<name>{_NAME})")
_OTHER_JUSTFILE = re.compile(
    r"^just\s+(?P<flag>-f|-d|--justfile|--working-directory)(?![\w-])"
)
_QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
_COMMENT = re.compile(r"(?:^|\s)#")
_SEPARATOR = re.compile(r"&&|\|\||\$\(|[;|(]")
_PROMPT = re.compile(r"^\s*\$\s+")
_COMMAND_PREFIX = re.compile(
    r"^(?:[A-Za-z_]\w*=\S*\s+)*(?:uvx\s+(?:--from(?:\s+|=)\S+\s+)?)?"
)
_RUN_KEY = re.compile(r"^\s*(?:-\s+)?run:(?:\s+(?P<value>.*?))?\s*$")
_BLOCK_INDICATOR = re.compile(r"^[|>][+-]?[1-9]?$")
_SCRIPT_TOKENS = frozenset({tokenize.STRING, tokenize.COMMENT, tokenize.FSTRING_MIDDLE})
_FENCE = re.compile(r"^\s*(?:`{3,}|~{3,})\s*(?P<info>[\w-]*)")
# A fence in one of these is a command listing, one in OUTPUT_FENCES is skipped,
# and any other (a bare one holding a prompt template, a python one) is prose
# whose inline spans alone count.
SHELL_FENCES = frozenset({"bash", "sh", "shell", "zsh"})
OUTPUT_FENCES = frozenset({"console", "text", "output"})
_SPAN = re.compile(r"`([^`]+)`")


def justfile_recipes(text: str) -> set[str]:
    """Return the recipe and alias names a justfile defines."""
    names: set[str] = set()
    for line in text.splitlines():
        match = _ALIAS.match(line) or _RECIPE_HEADER.match(line)
        if match and match["name"] not in NOT_RECIPES:
            names.add(match["name"])
    return names


def _paragraphs(lines: list[str]) -> Iterator[tuple[int, str]]:
    """Yield ``(first line number, text)`` of each blank-line-separated run."""
    start, run = 0, []
    for number, line in enumerate([*lines, ""], start=1):
        if line.strip():
            start = start or number
            run.append(line)
        elif run:
            yield start, "\n".join(run)
            start, run = 0, []


def _shell_lines(block: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Return a shell fence's commands: its ``$ `` lines if it has any, else all."""
    prompted = [(number, line) for number, line in block if _PROMPT.match(line)]
    return prompted or block


def code_snippets(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(line number, code)`` for each shell-fenced line and code span."""
    prose: list[str] = []
    fence: str | None = None
    block: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if match := _FENCE.match(line):
            if fence is not None:
                yield from _shell_lines(block)
                block = []
            fence = match["info"] if fence is None else None
            prose.append("")
        elif fence in SHELL_FENCES:
            block.append((number, line))
            prose.append("")
        elif fence in OUTPUT_FENCES:
            prose.append("")
        else:
            prose.append(line)
    yield from _shell_lines(block)
    for start, paragraph in _paragraphs(prose):
        for match in _SPAN.finditer(paragraph):
            yield start + paragraph.count("\n", 0, match.start()), match[1]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def workflow_run_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(line number, command)`` for each line of every ``run:`` step."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if (match := _RUN_KEY.match(line)) is None:
            continue
        value = split_comment(match["value"] or "")[0]
        if not _BLOCK_INDICATOR.match(value):
            yield index + 1, value
            continue
        key_column = line.index("run:")
        for number, body in enumerate(lines[index + 1 :], start=index + 2):
            if body.strip() and _indent(body) <= key_column:
                break
            if not body.lstrip().startswith("#"):
                yield number, split_comment(body)[0]


def script_snippets(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(line number, code)`` for each code span in a string or comment."""
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in _SCRIPT_TOKENS:
            for match in _SPAN.finditer(token.string):
                yield (
                    token.start[0] + token.string.count("\n", 0, match.start()),
                    match[1],
                )


def commands(code: str) -> Iterator[str]:
    """Yield each command of a snippet, from its command name on.

    Quoted text is dropped first, then everything after an unquoted ``#``; an
    unclosed quote drops the rest of the snippet.
    """
    unquoted = _QUOTED.sub(" ", code)
    for end in (_COMMENT.search(unquoted), re.search(r"[\"']", unquoted)):
        if end is not None:
            unquoted = unquoted[: end.start()]
    for segment in _SEPARATOR.split(_PROMPT.sub("", unquoted, count=1)):
        yield _COMMAND_PREFIX.sub("", segment.strip(), count=1)


def documents(root: Path) -> list[Path]:
    """Return every document this check reads, sorted and without repeats."""
    found = {path for pattern in DOCUMENT_GLOBS for path in root.glob(pattern)}
    unread = {path for pattern in UNREAD_GLOBS for path in root.glob(pattern)}
    return sorted(path for path in found - unread if path.is_file())


def _runs_commands(path: Path, root: Path) -> bool:
    """Whether ``path`` is a workflow or a composite action, whose ``run:`` counts."""
    is_action = path.name in ACTION_FILES and path.is_relative_to(root / ACTIONS_DIR)
    return is_action or path.parent == root / WORKFLOW_PARENT


def _snippets(path: Path, root: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return list(script_snippets(text))
    snippets = list(code_snippets(text))
    if _runs_commands(path, root):
        snippets.extend(workflow_run_lines(text))
    return snippets


def recipe_findings(root: Path) -> list[str]:
    """Return each ``just <recipe>`` a document names that the justfile lacks."""
    justfile = root / JUSTFILE
    if not justfile.is_file():
        return [f"{JUSTFILE} is missing"]
    recipes = justfile_recipes(justfile.read_text(encoding="utf-8"))
    findings: list[str] = []
    for path in documents(root):
        relative = path.relative_to(root).as_posix()
        snippets = _snippets(path, root)
        calls = sorted(
            {
                (number, command)
                for number, code in snippets
                for command in commands(code)
            }
        )
        findings.extend(
            f"{relative}:{number}: `just {match['flag']}` names another justfile, "
            "which this check cannot read; name the recipe of the root justfile"
            for number, command in calls
            if (match := _OTHER_JUSTFILE.match(command))
        )
        missing = sorted(
            {
                (number, match["name"])
                for number, command in calls
                if (match := _CALL.match(command)) and match["name"] not in recipes
            }
        )
        findings.extend(
            f"{relative}:{number}: `just {name}` names no recipe in the {JUSTFILE}"
            for number, name in missing
        )
    return findings


# --- the repository ---


def test_recipes_named_on_repository_exist() -> None:
    assert recipe_findings(REPO_ROOT) == []


def test_justfile_recipes_reads_repository_justfile() -> None:
    recipes = justfile_recipes((REPO_ROOT / JUSTFILE).read_text(encoding="utf-8"))

    # Only the harness's own recipes: an app may delete the others (`just run`
    # goes with the CLI).
    assert {"verify", "check-harness"} <= recipes
    assert not recipes & NOT_RECIPES


# --- fixtures ---

JUSTFILE_TEXT = """\
set shell := ["bash", "-c"]
version := "1"
alias t := test

# Run the tests
test:
    uv run pytest

[positional-arguments]
run *ARGS:
    uv run app "$@"

@quiet arg="x": test
    echo {{arg}}
"""


@pytest.fixture
def make_root(tmp_path: Path) -> MakeRoot:
    def make(files: dict[str, str]) -> Path:
        (tmp_path / JUSTFILE).write_text(JUSTFILE_TEXT, encoding="utf-8")
        for relative, text in files.items():
            (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / relative).write_text(text, encoding="utf-8")
        return tmp_path

    return make


def test_justfile_recipes_reads_headers_and_aliases() -> None:
    assert justfile_recipes(JUSTFILE_TEXT) == {"t", "test", "run", "quiet"}


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Run `just test` first.\n", id="inline-span"),
        pytest.param("```bash\njust run --help\n```\n", id="recipe-with-arguments"),
        pytest.param("Use `just t`, the alias.\n", id="alias"),
        pytest.param("It is just docs, nothing more.\n", id="prose"),
        pytest.param("```\nIts CI just failed.\n```\n", id="bare-fence-prose"),
        pytest.param("Replace `just <recipe>` or run `just --list`.\n", id="no-name"),
        pytest.param("Run `uvx --from rust-just==1 just test`.\n", id="tool-prefix"),
        # Shell text that names `just` outside a command's position.
        pytest.param("```bash\n# just lists them\njust --list\n```\n", id="comment"),
        pytest.param(
            "```bash\njust test # then just docs\n```\n", id="trailing-comment"
        ),
        pytest.param(
            "```bash\nmy-app todo add \"just docs\"\nmy-app todo add 'just docs'\n```\n",
            id="quoted-argument",
        ),
        pytest.param("```bash\necho just docs\n```\n", id="argument"),
        pytest.param(
            "```console\n$ my-app todo list\njust docs  [ ]\n```\n", id="console"
        ),
        pytest.param("```text\njust docs\n```\n", id="text-fence"),
        pytest.param("```output\njust docs\n```\n", id="output-fence"),
        pytest.param(
            "```bash\n$ my-app todo list\njust docs  [ ]\n$ just test\n```\n",
            id="prompt-fence-output-line",
        ),
        pytest.param("Run `echo 'it is \"just docs\"'`.\n", id="nested-quotes"),
        pytest.param('Run `say "just docs`.\n', id="unclosed-quote"),
    ],
)
def test_recipe_findings_existing_or_no_recipe_passes(
    make_root: MakeRoot, text: str
) -> None:
    assert recipe_findings(make_root({"AGENTS.md": text})) == []


@pytest.mark.parametrize(
    ("relative", "text", "line"),
    [
        pytest.param("AGENTS.md", "# Guide\n\nRun `just docs`.\n", 3, id="agents-span"),
        pytest.param(
            "CLAUDE.md", "```bash\njust test\njust docs\n```\n", 3, id="fence"
        ),
        pytest.param(
            "CLAUDE.md", "```\nPrompt: run `just docs`.\n```\n", 2, id="bare-fence-span"
        ),
        pytest.param(
            ".agents/skills/foo/references/x.md",
            "A span may wrap: `just\ndocs` here.\n",
            1,
            id="skill-reference-wrapped-span",
        ),
        pytest.param(
            ".github/workflows/ci.yml",
            "jobs:\n  a:\n    steps:\n      - run: just docs\n",
            4,
            id="workflow-run",
        ),
        pytest.param(
            ".github/workflows/ci.yml",
            "jobs:\n  a:\n    steps:\n      - name: Check\n        run: |\n"
            "          # just a comment\n          just test\n\n"
            "          uvx --from rust-just==1 just docs # the docs\n",
            9,
            id="workflow-run-block",
        ),
        pytest.param(
            ".agents/skills/foo/scripts/tool.py",
            '"""Tool.\n\nRun `just test` first.\n"""\n'
            "# A prose comment: just fixed.\n"
            'print(f"next: `just test`, then `just docs`")  # `just t`\n',
            6,
            id="skill-script-strings",
        ),
        pytest.param(
            ".github/ISSUE_TEMPLATE/bug.yml",
            "body:\n  - type: markdown\n    attributes:\n      value: Run `just docs`.\n",
            4,
            id="issue-form",
        ),
        pytest.param(
            "README.md", "# App\n\n```bash\njust docs # build\n```\n", 4, id="readme"
        ),
        pytest.param(
            "CONTRIBUTING.md",
            "## Commands\n\nRun `just test`, then `just docs`.\n",
            3,
            id="contributing",
        ),
        pytest.param(
            "docs/architecture/README.md",
            "# Architecture\n\nRun `just docs`.\n",
            3,
            id="docs-index",
        ),
        pytest.param("docs/guide/setup.md", "Run `just docs`.\n", 1, id="other-docs"),
        pytest.param("TEMPLATE.md", "Run `just docs`.\n", 1, id="template-md"),
        pytest.param("SECURITY.md", "Run `just docs`.\n", 1, id="security-md"),
        pytest.param(
            "scripts/tool.py",
            '"""Tool.\n\nRun `just docs` first.\n"""\n',
            3,
            id="repository-script",
        ),
        pytest.param(
            ".pre-commit-config.yaml",
            "repos: []\n# CI and `just docs` judge the commit.\n",
            2,
            id="pre-commit-config",
        ),
        pytest.param(
            ".github/actions/setup/action.yml",
            "runs:\n  using: composite\n  steps:\n    - shell: bash\n"
            "      run: |\n        uv sync\n        just docs\n",
            7,
            id="composite-action-run",
        ),
        pytest.param("AGENTS.md", "Run `uv sync && just docs`.\n", 1, id="after-and"),
        pytest.param("AGENTS.md", "Run `false || just docs`.\n", 1, id="after-or"),
        pytest.param("AGENTS.md", "Run `cd x; just docs`.\n", 1, id="after-semicolon"),
        pytest.param("AGENTS.md", "Run `yes | just docs`.\n", 1, id="after-pipe"),
        pytest.param("AGENTS.md", "Run `(just docs)`.\n", 1, id="subshell"),
        pytest.param("AGENTS.md", "Run `x=$(just docs)`.\n", 1, id="substitution"),
        pytest.param("AGENTS.md", "Run `CI=1 just docs`.\n", 1, id="env-prefix"),
        pytest.param(
            "AGENTS.md", "```bash\n$ just docs\nok\n```\n", 2, id="prompt-line"
        ),
        pytest.param(
            ".claude/agents/executor.md",
            "---\nname: executor\n---\n\nRun `just docs` before reporting.\n",
            5,
            id="claude-agent",
        ),
        pytest.param(
            ".codex/agents/executor.toml",
            'name = "executor"\ndeveloper_instructions = """\n'
            'Run `just docs` before reporting.\n"""\n',
            3,
            id="codex-agent",
        ),
    ],
)
def test_recipe_findings_missing_recipe_names_file_and_recipe(
    make_root: MakeRoot, relative: str, text: str, line: int
) -> None:
    findings = recipe_findings(make_root({relative: text}))

    assert findings == [
        f"{relative}:{line}: `just docs` names no recipe in the {JUSTFILE}"
    ]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("# It is just docs here.\njobs: {}\n", id="comment"),
        pytest.param(
            "jobs:\n  a:\n    name: Run just the fast checks\n    steps:\n"
            "      - name: Run just the docs\n        run: just test\n",
            id="step-and-job-names",
        ),
        pytest.param(
            "defaults:\n  run:\n    shell: bash\njobs: {}\n", id="defaults-run"
        ),
    ],
)
def test_recipe_findings_workflow_prose_is_not_a_command(
    make_root: MakeRoot, text: str
) -> None:
    assert recipe_findings(make_root({".github/workflows/ci.yml": text})) == []


def test_recipe_findings_skill_script_tests_are_not_read(make_root: MakeRoot) -> None:
    text = '"""Fixture: `just docs` is a fake recipe."""\n'

    assert (
        recipe_findings(make_root({".agents/skills/foo/scripts/tests/t.py": text}))
        == []
    )


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        pytest.param("Run `just -f other/justfile docs`.\n", "-f", id="short"),
        pytest.param("Run `just --justfile=x test`.\n", "--justfile", id="long-equals"),
        pytest.param("```bash\njust -d sub test\n```\n", "-d", id="working-dir"),
    ],
)
def test_recipe_findings_other_justfile_is_reported(
    make_root: MakeRoot, text: str, flag: str
) -> None:
    findings = recipe_findings(make_root({"AGENTS.md": text}))

    assert len(findings) == 1
    assert findings[0].startswith("AGENTS.md:")
    assert f"`just {flag}` names another justfile" in findings[0]


@pytest.mark.parametrize(
    ("relative", "text"),
    [
        pytest.param(
            "docs/architecture/adr/0001-drop-dev.md",
            "# ADR-0001\n\n- **Status:** Accepted 2026-01-01\n\nDrop `just docs`.\n",
            id="accepted-adr",
        ),
        pytest.param(
            "docs/architecture/adr/0002-e2e.md",
            "- **Status:** Proposed\n\nAdd `just docs`.\n",
            id="proposed-adr",
        ),
        pytest.param(
            "docs/architecture/adr/template.md", "Run `just docs`.\n", id="adr-template"
        ),
        pytest.param(
            "docs/architecture/roadmap.md",
            "- Done when: `just docs` passes\n",
            id="roadmap",
        ),
        pytest.param(
            "docs/product/requirements.md", "Later: `just docs`.\n", id="product-docs"
        ),
        pytest.param(
            ".devcontainer/devcontainer.json",
            '{"postCreateCommand": "just docs"}\n',
            id="devcontainer",
        ),
        pytest.param(
            "scripts/tests/test_tool.py",
            '"""Fixture: `just docs`."""\n',
            id="script-tests",
        ),
    ],
)
def test_recipe_findings_intent_or_history_is_not_read(
    make_root: MakeRoot, relative: str, text: str
) -> None:
    assert recipe_findings(make_root({relative: text})) == []


def test_recipe_findings_undecodable_document_fails_closed(
    make_root: MakeRoot,
) -> None:
    root = make_root({})
    (root / "README.md").write_bytes(b"Run `just docs` \xff\n")

    with pytest.raises(
        UnicodeDecodeError, match=r"'utf-8' codec can't decode byte 0xff"
    ):
        recipe_findings(root)


def test_recipe_findings_without_justfile_fails(tmp_path: Path) -> None:
    assert recipe_findings(tmp_path) == [f"{JUSTFILE} is missing"]


def ci_recipe_findings(root: Path) -> list[str]:
    """Keep required CI jobs' commands identical to local check recipes."""
    path = root / ".github/workflows/ci.yml"
    workflow_jobs = jobs(read_workflow(path), path)
    commands_by_job = {
        scalar(job.get("name", job_id)): {
            line.strip()
            for step in steps(job, path)
            if "run" in step
            for line in block_text(step["run"]).splitlines()
        }
        for job_id, job in workflow_jobs.items()
    }
    text = (root / JUSTFILE).read_text(encoding="utf-8")
    findings: list[str] = []
    local_by_job: dict[str, set[str]] = {}
    for recipe, job_name in {
        "agents-check": "Lint & Type Check",
        "lint": "Lint & Type Check",
        "test-skills": "Lint & Type Check",
        "test": "Coverage",
    }.items():
        match = re.search(rf"^{recipe}:.*\n((?:[ \t]+[^\n]*\n)+)", text, re.MULTILINE)
        assert match is not None, f"recipe {recipe} is missing"
        commands = [
            line.strip()
            for line in match[1].splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert commands, f"recipe {recipe} has no commands"
        local_by_job.setdefault(job_name, set()).update(commands)
        findings.extend(
            f"{job_name}: missing {recipe} command: {command}"
            for command in commands
            if command not in commands_by_job.get(job_name, set())
        )
    ci_only_commands = {
        "Lint & Type Check": {"uv run --locked pre-commit run shellcheck --all-files"},
        "Coverage": set(),
    }
    for job_name, local_commands in local_by_job.items():
        ci_commands = {
            command
            for command in commands_by_job.get(job_name, set())
            if command.startswith(("uv run ", "PYTHONDONTWRITEBYTECODE=1 uv run "))
        }
        findings.extend(
            f"{job_name}: extra CI command: {command}"
            for command in sorted(
                ci_commands - local_commands - ci_only_commands[job_name]
            )
        )
    return findings


def test_ci_recipe_findings_repository_commands_match() -> None:
    assert ci_recipe_findings(REPO_ROOT) == []


def test_ci_recipe_findings_drifted_command_is_rejected(tmp_path: Path) -> None:
    workflow = REPO_ROOT / ".github/workflows/ci.yml"
    destination = tmp_path / ".github/workflows/ci.yml"
    destination.parent.mkdir(parents=True)
    destination.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "uv run --locked ruff check .", "uv run --locked ruff check src"
        ),
        encoding="utf-8",
    )
    (tmp_path / JUSTFILE).write_text(
        (REPO_ROOT / JUSTFILE).read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert (
        "Lint & Type Check: missing lint command: uv run --locked ruff check ."
        in ci_recipe_findings(tmp_path)
    )


def test_ci_recipe_findings_removed_local_command_is_rejected(tmp_path: Path) -> None:
    destination = tmp_path / ".github/workflows/ci.yml"
    destination.parent.mkdir(parents=True)
    destination.write_text(
        (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / JUSTFILE).write_text(
        (REPO_ROOT / JUSTFILE)
        .read_text(encoding="utf-8")
        .replace("    uv run --locked mypy\n", ""),
        encoding="utf-8",
    )
    assert (
        "Lint & Type Check: extra CI command: uv run --locked mypy"
        in ci_recipe_findings(tmp_path)
    )


@pytest.mark.parametrize(
    ("skill_rc", "lint_rc", "expected"), [(0, 0, 0), (1, 0, 1), (0, 1, 1)]
)
def test_ci_parallel_checks_propagate_each_failure(
    tmp_path: Path, skill_rc: int, lint_rc: int, expected: int
) -> None:
    path = REPO_ROOT / ".github/workflows/ci.yml"
    lint = jobs(read_workflow(path), path)["lint"]
    run = next(
        (
            step["run"]
            for step in steps(lint, path)
            if scalar(step.get("name", "")) == "Run independent checks"
        ),
        None,
    )
    assert run is not None, "CI must run independent checks together and await both"
    uv = tmp_path / "uv"
    uv.write_text(
        '#!/usr/bin/env bash\ncase "$*" in\n  *pytest*) exit "$SKILL_RC" ;;\n  *mypy*) exit "$LINT_RC" ;;\nesac\nexit 0\n',
        encoding="utf-8",
    )
    uv.chmod(0o755)
    proc = subprocess.run(  # noqa: S603 -- repository CI script with fixture-only uv
        ["/bin/bash", "-euo", "pipefail", "-c", textwrap.dedent(block_text(run))],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "SKILL_RC": str(skill_rc),
            "LINT_RC": str(lint_rc),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == expected, proc.stderr
