"""(c) Every ``just <recipe>`` the agent- and human-facing documents name exists.

A renamed or removed recipe must not leave a document pointing a reader at
nothing. Read: every top-level ``*.md`` (AGENTS.md, CLAUDE.md,
README.md, CONTRIBUTING.md, SECURITY.md, ...), each area's ``AGENTS.md`` and
``CLAUDE.md`` one directory down (``backend/AGENTS.md``), ``docs/**/*.md``
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

The root justfile's ``mod NAME`` and ``mod NAME 'PATH'`` statements (``mod?``
for an optional one) declare just modules, read from ``PATH`` or, without one,
from the first of ``NAME.just``, ``NAME/mod.just``, ``NAME/justfile``, and
``NAME/.justfile`` that exists. A module recipe is named as
``just NAME <recipe>`` or ``just NAME::<recipe>``, and must exist in the
module's file; ``just NAME`` alone names no recipe and is reported. A
non-optional module without a file is reported; an optional one is not, but a
call into it is.

``ci_recipe_findings`` keeps the required CI jobs' commands equal to the
recipe lines they mirror, root recipes in a step run at the repository root
and module recipes in a step whose ``working-directory`` is the module's
directory.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import textwrap
import tokenize
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest

from tests.harness._shell import split_comment
from tests.harness._workflows import jobs, read_workflow, steps
from tests.harness._yaml import Mapping, as_mapping, block_text, scalar

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator

    type MakeRoot = Callable[[dict[str, str]], Path]

REPO_ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = "justfile"
DOCUMENT_GLOBS = (
    "*.md",
    "*/AGENTS.md",
    "*/CLAUDE.md",
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
# `just a::b` is one path; after a module name, the next word is its recipe, a
# `<placeholder>` names nothing, and anything else (or nothing) names no recipe.
_CALL = re.compile(
    rf"^just\s+(?P<head>{_NAME})(?P<path>(?:::{_NAME})*)"
    rf"(?:\s+(?:(?P<argument>{_NAME})|(?P<placeholder><)))?"
)
_MOD_START = re.compile(r"^mod\??[ \t]")
_MOD = re.compile(
    rf"^mod(?P<optional>\?)?[ \t]+(?P<name>{_NAME})"
    r"(?:[ \t]+(?:'(?P<raw>[^']*)'|\"(?P<cooked>(?:[^\"\\]|\\.)*)\"))?"
    r"[ \t]*(?:#.*)?$"
)
# Where just looks for `mod NAME` without a path, in its order; the last two
# may have any capitalization (https://just.systems/man/en/modules.html).
MODULE_CANDIDATES = (
    "{name}.just",
    "{name}/mod.just",
    "{name}/justfile",
    "{name}/.justfile",
)
_ANY_CASE = frozenset({"justfile", ".justfile"})
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


@dataclass(frozen=True, slots=True)
class JustModule:
    """A ``mod`` statement and the module files found where just looks."""

    name: str
    optional: bool
    # What just searches, relative to the declaring justfile's directory.
    searched: tuple[str, ...]
    found: tuple[Path, ...]

    @property
    def path(self) -> Path | None:
        """The module's file, or None when there is none or more than one."""
        return self.found[0] if len(self.found) == 1 else None


def _existing(directory: Path, relative: str) -> list[Path]:
    """Return the file ``relative`` names, matching its name in any case if allowed."""
    candidate = directory / relative
    if candidate.name.lower() not in _ANY_CASE:
        return [candidate] if candidate.is_file() else []
    if not candidate.parent.is_dir():
        return []
    return sorted(
        path
        for path in candidate.parent.iterdir()
        if path.name.lower() == candidate.name and path.is_file()
    )


def justfile_modules(text: str, directory: Path) -> dict[str, JustModule]:
    """Return each module a justfile in ``directory`` declares, by name.

    Raises:
        ValueError: on a ``mod`` line this reader cannot parse, so a module is
            never skipped by accident.
    """
    modules: dict[str, JustModule] = {}
    for line in text.splitlines():
        if not _MOD_START.match(line):
            continue
        match = _MOD.match(line)
        if match is None:
            msg = f"unreadable mod statement in a justfile: {line!r}"
            raise ValueError(msg)
        name = match["name"]
        explicit = match["raw"] if match["raw"] is not None else match["cooked"]
        searched = (
            (explicit,)
            if explicit is not None
            else tuple(pattern.format(name=name) for pattern in MODULE_CANDIDATES)
        )
        found = tuple(
            path for relative in searched for path in _existing(directory, relative)
        )
        modules[name] = JustModule(name, bool(match["optional"]), searched, found)
    return modules


def module_findings(root: Path) -> list[str]:
    """Return each module the root justfile declares whose file just cannot read."""
    text = (root / JUSTFILE).read_text(encoding="utf-8")
    findings: list[str] = []
    for module in justfile_modules(text, root).values():
        if len(module.found) > 1:
            files = ", ".join(
                path.relative_to(root).as_posix() for path in module.found
            )
            findings.append(
                f"{JUSTFILE}: `mod {module.name}` matches more than one file: {files}"
            )
        elif not module.found and not module.optional:
            findings.append(
                f"{JUSTFILE}: `mod {module.name}` has no module file "
                f"(looked for {', '.join(module.searched)})"
            )
    return findings


@dataclass(frozen=True, slots=True)
class ModuleRecipes:
    """A module that has a file: where it is and the recipes it defines."""

    file: str
    recipes: frozenset[str]


def module_recipes(root: Path) -> dict[str, ModuleRecipes]:
    """Return the recipes of each root module whose file exists, by module name."""
    text = (root / JUSTFILE).read_text(encoding="utf-8")
    return {
        name: ModuleRecipes(
            module.path.relative_to(root).as_posix(),
            frozenset(justfile_recipes(module.path.read_text(encoding="utf-8"))),
        )
        for name, module in justfile_modules(text, root).items()
        if module.path is not None
    }


@dataclass(frozen=True, slots=True)
class Call:
    """A ``just`` invocation in command position, as far as it names a recipe.

    ``module`` is None for a root recipe. ``recipe`` is None for a bare
    ``just MODULE``, which names no recipe. ``spelled`` is how a finding quotes it.
    """

    module: str | None
    recipe: str | None
    spelled: str


def parse_call(command: str, modules: Collection[str]) -> Call | None:
    """Return what a command beginning with ``just`` names, or None for nothing.

    ``modules`` are the root justfile's module names, declared ones included
    even when their file is missing, so a call into one is never read as a
    root recipe.
    """
    match = _CALL.match(command)
    if match is None:
        return None
    head, path = match["head"], match["path"]
    if path:
        return Call(head, path[2:], f"{head}{path}")
    if head not in modules:
        return Call(None, head, head)
    if match["placeholder"]:
        return None
    argument = match["argument"]
    return Call(head, argument, f"{head} {argument}" if argument else head)


def _module_call_finding(
    call: Call, declared: Collection[str], available: dict[str, ModuleRecipes]
) -> str | None:
    """Return why a call into a module names nothing, or None for a recipe."""
    module = available.get(call.module or "")
    if call.module not in declared:
        problem = f"names no module in the {JUSTFILE}"
    elif module is None:
        problem = f"names the module {call.module}, which has no module file"
    elif call.recipe is None:
        problem = (
            f"names no recipe of {module.file}; name one, "
            f"as `just {call.module} <recipe>`"
        )
    elif call.recipe not in module.recipes:
        problem = f"names no recipe in {module.file}"
    else:
        return None
    return f"`just {call.spelled}` {problem}"


def _call_finding(
    call: Call,
    recipes: Collection[str],
    declared: Collection[str],
    available: dict[str, ModuleRecipes],
) -> str | None:
    """Return why a call names nothing, or None when it names a recipe."""
    if call.module is not None:
        return _module_call_finding(call, declared, available)
    if call.recipe in recipes:
        return None
    return f"`just {call.spelled}` names no recipe in the {JUSTFILE}"


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
    """Return each ``just <recipe>`` a document names that its justfile lacks."""
    justfile = root / JUSTFILE
    if not justfile.is_file():
        return [f"{JUSTFILE} is missing"]
    text = justfile.read_text(encoding="utf-8")
    recipes = justfile_recipes(text)
    declared = set(justfile_modules(text, root))
    available = module_recipes(root)
    findings = module_findings(root)
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
                (number, finding)
                for number, command in calls
                if (call := parse_call(command, declared))
                and (finding := _call_finding(call, recipes, declared, available))
            }
        )
        findings.extend(
            f"{relative}:{number}: {finding}" for number, finding in missing
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


def test_module_recipes_reads_repository_backend_module() -> None:
    modules = module_recipes(REPO_ROOT)

    assert modules["backend"].file == "backend/justfile"
    assert {"lint", "fmt", "test", "dev"} <= modules["backend"].recipes
    assert module_findings(REPO_ROOT) == []


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


# --- modules ---

MODULE_JUSTFILE_TEXT = """\
lint:
    uv run ruff check .

alias t := test

test:
    uv run pytest
"""


@pytest.fixture
def make_module_root(tmp_path: Path) -> Callable[..., Path]:
    def make(
        files: dict[str, str],
        *,
        mod: str = "mod backend",
        module_file: str | None = "backend/justfile",
    ) -> Path:
        (tmp_path / JUSTFILE).write_text(f"{mod}\n\n{JUSTFILE_TEXT}", encoding="utf-8")
        if module_file is not None:
            files = {module_file: MODULE_JUSTFILE_TEXT, **files}
        for relative, text in files.items():
            (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / relative).write_text(text, encoding="utf-8")
        return tmp_path

    return make


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        pytest.param("backend.just", "backend.just", id="name-dot-just"),
        pytest.param("backend/mod.just", "backend/mod.just", id="mod-just"),
        pytest.param("backend/justfile", "backend/justfile", id="justfile"),
        pytest.param("backend/.justfile", "backend/.justfile", id="dot-justfile"),
        pytest.param("backend/Justfile", "backend/Justfile", id="justfile-any-case"),
    ],
)
def test_justfile_modules_implicit_path_is_found_where_just_looks(
    tmp_path: Path, relative: str, expected: str
) -> None:
    (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / relative).write_text("test:\n    true\n", encoding="utf-8")

    modules = justfile_modules("mod backend # the app\n", tmp_path)

    assert modules["backend"].path == tmp_path / expected
    assert not modules["backend"].optional


@pytest.mark.parametrize(
    ("line", "relative"),
    [
        pytest.param("mod tools 'build/tools.just'", "build/tools.just", id="raw"),
        pytest.param('mod tools "build/tools.just"', "build/tools.just", id="cooked"),
    ],
)
def test_justfile_modules_explicit_path_is_read(
    tmp_path: Path, line: str, relative: str
) -> None:
    (tmp_path / relative).parent.mkdir(parents=True)
    (tmp_path / relative).write_text("test:\n    true\n", encoding="utf-8")

    modules = justfile_modules(f"{line}\n", tmp_path)

    assert modules["tools"].path == tmp_path / relative
    assert modules["tools"].searched == (relative,)


def test_justfile_modules_optional_module_without_file(tmp_path: Path) -> None:
    module = justfile_modules("mod? extras\n", tmp_path)["extras"]

    assert module.optional
    assert module.path is None


def test_justfile_modules_unreadable_statement_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unreadable mod statement"):
        justfile_modules("mod backend backend/justfile\n", tmp_path)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Run `just backend test`.\n", id="subcommand"),
        pytest.param("Run `just backend::test`.\n", id="path"),
        pytest.param("Run `just backend t`.\n", id="module-alias"),
        pytest.param("```bash\njust backend test -k slow\n```\n", id="arguments"),
        pytest.param("Run `(just backend lint)`.\n", id="subshell"),
        pytest.param("Use `just backend <recipe>`.\n", id="placeholder"),
        pytest.param("Run `just test` at the root.\n", id="root-recipe"),
    ],
)
def test_recipe_findings_existing_module_recipe_passes(
    make_module_root: Callable[..., Path], text: str
) -> None:
    assert recipe_findings(make_module_root({"AGENTS.md": text})) == []


@pytest.mark.parametrize(
    ("relative", "text", "finding"),
    [
        pytest.param(
            "AGENTS.md",
            "Run `just backend tests`.\n",
            "AGENTS.md:1: `just backend tests` names no recipe in backend/justfile",
            id="missing-module-recipe",
        ),
        pytest.param(
            ".agents/skills/foo/SKILL.md",
            "```bash\njust backend::tests\n```\n",
            ".agents/skills/foo/SKILL.md:2: `just backend::tests` names no recipe "
            "in backend/justfile",
            id="path-form",
        ),
        pytest.param(
            "AGENTS.md",
            "Run `just backend`.\n",
            "AGENTS.md:1: `just backend` names no recipe of backend/justfile; "
            "name one, as `just backend <recipe>`",
            id="bare-module",
        ),
        pytest.param(
            "AGENTS.md",
            "Run `just frontend::test`.\n",
            "AGENTS.md:1: `just frontend::test` names no module in the justfile",
            id="undeclared-module-path",
        ),
        pytest.param(
            "backend/AGENTS.md",
            "# Backend\n\nRun `just backend docs`.\n",
            "backend/AGENTS.md:3: `just backend docs` names no recipe in "
            "backend/justfile",
            id="area-agents-md",
        ),
        pytest.param(
            "backend/CLAUDE.md",
            "@AGENTS.md\n\nRun `just backend::docs`.\n",
            "backend/CLAUDE.md:3: `just backend::docs` names no recipe in "
            "backend/justfile",
            id="area-claude-md",
        ),
    ],
)
def test_recipe_findings_missing_module_recipe_names_file_and_line(
    make_module_root: Callable[..., Path], relative: str, text: str, finding: str
) -> None:
    assert recipe_findings(make_module_root({relative: text})) == [finding]


def test_recipe_findings_missing_module_file_is_reported(
    make_module_root: Callable[..., Path],
) -> None:
    root = make_module_root(
        {"AGENTS.md": "Run `just backend test`.\n"}, module_file=None
    )

    assert recipe_findings(root) == [
        (
            f"{JUSTFILE}: `mod backend` has no module file (looked for backend.just, "
            "backend/mod.just, backend/justfile, backend/.justfile)"
        ),
        (
            "AGENTS.md:1: `just backend test` names the module backend, which has no "
            "module file"
        ),
    ]


def test_recipe_findings_optional_module_without_file_reports_only_calls(
    make_module_root: Callable[..., Path],
) -> None:
    root = make_module_root(
        {"AGENTS.md": "Run `just test`, then `just backend lint`.\n"},
        mod="mod? backend",
        module_file=None,
    )

    assert recipe_findings(root) == [
        (
            "AGENTS.md:1: `just backend lint` names the module backend, which has no "
            "module file"
        )
    ]


def test_recipe_findings_ambiguous_module_file_is_reported(
    make_module_root: Callable[..., Path],
) -> None:
    root = make_module_root({"backend.just": MODULE_JUSTFILE_TEXT})

    assert recipe_findings(root) == [
        (
            f"{JUSTFILE}: `mod backend` matches more than one file: backend.just, "
            "backend/justfile"
        )
    ]


# Each recipe whose commands a required CI job repeats verbatim. A module
# recipe (`module::recipe`) runs in its module's directory, so its CI step sets
# `working-directory` to that directory; a root recipe's step sets none.
CI_RECIPES = {
    "agents-check": "Lint & Type Check",
    "lint": "Lint & Type Check",
    "test-skills": "Lint & Type Check",
    "test": "Coverage",
    "backend::lint": "Lint & Type Check",
    "backend::test": "Coverage",
}
# `uv run` commands a job may run that mirror no recipe, each in its directory.
CI_ONLY_COMMANDS = {
    "Lint & Type Check": {
        ("", "uv run --locked pre-commit run shellcheck --all-files")
    },
    "Coverage": set(),
}
_UV_RUN = ("uv run ", "PYTHONDONTWRITEBYTECODE=1 uv run ")

type Located = tuple[str, str]  # (directory relative to the root, "" there; command)


def _directory(value: str) -> str:
    """Normalize a ``working-directory`` to a root-relative path, "" for the root."""
    parts = [part for part in PurePosixPath(value.strip()).parts if part != "."]
    return PurePosixPath(*parts).as_posix() if parts else ""


def _default_directory(owner: Mapping, path: Path) -> str | None:
    """Return a workflow's or a job's ``defaults.run.working-directory``, if set."""
    run = as_mapping(owner.get("defaults", {}), f"{path}: defaults").get("run", {})
    value = as_mapping(run, f"{path}: defaults.run").get("working-directory")
    return None if value is None else scalar(value)


def _job_commands(root: Path) -> dict[str, set[Located]]:
    """Return each ci.yml job's ``run:`` lines with the directory they run in."""
    path = root / ".github/workflows/ci.yml"
    top = read_workflow(path)
    workflow_default = _default_directory(top, path)
    commands_by_job: dict[str, set[Located]] = {}
    for job_id, job in jobs(top, path).items():
        job_default = _default_directory(job, path)
        located: set[Located] = set()
        for step in steps(job, path):
            if "run" not in step:
                continue
            given = step.get("working-directory")
            directory = _directory(
                scalar(given)
                if given is not None
                else job_default or workflow_default or ""
            )
            located.update(
                (directory, line.strip())
                for line in block_text(step["run"]).splitlines()
            )
        commands_by_job[scalar(job.get("name", job_id))] = located
    return commands_by_job


def _recipe_commands(root: Path, recipe: str) -> tuple[str, list[str]]:
    """Return the directory a recipe runs in and its command lines."""
    text = (root / JUSTFILE).read_text(encoding="utf-8")
    directory, name = "", recipe
    if "::" in recipe:
        module_name, name = recipe.split("::", 1)
        module = justfile_modules(text, root).get(module_name)
        assert module is not None, f"module {module_name} is not declared"
        assert module.path is not None, f"module {module_name} has no module file"
        text = module.path.read_text(encoding="utf-8")
        directory = _directory(module.path.parent.relative_to(root).as_posix())
    match = re.search(rf"^{name}:.*\n((?:[ \t]+[^\n]*\n)+)", text, re.MULTILINE)
    assert match is not None, f"recipe {recipe} is missing"
    commands = [
        line.strip()
        for line in match[1].splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert commands, f"recipe {recipe} has no commands"
    return directory, commands


def _where(directory: str) -> str:
    return (
        f"`working-directory: {directory}`" if directory else "no `working-directory`"
    )


def ci_recipe_findings(root: Path) -> list[str]:
    """Keep required CI jobs' commands identical to local check recipes."""
    commands_by_job = _job_commands(root)
    findings: list[str] = []
    local_by_job: dict[str, set[Located]] = {}
    for recipe, job_name in CI_RECIPES.items():
        directory, commands = _recipe_commands(root, recipe)
        local_by_job.setdefault(job_name, set()).update(
            (directory, command) for command in commands
        )
        ci = commands_by_job.get(job_name, set())
        for command in commands:
            if (directory, command) in ci:
                continue
            if any(line == command for _, line in ci):
                findings.append(
                    f"{job_name}: {recipe} command not in a step with "
                    f"{_where(directory)}: {command}"
                )
            else:
                findings.append(f"{job_name}: missing {recipe} command: {command}")
    for job_name, local_commands in local_by_job.items():
        ci_commands = {
            (directory, command)
            for directory, command in commands_by_job.get(job_name, set())
            if command.startswith(_UV_RUN)
        }
        findings.extend(
            f"{job_name}: extra CI command"
            f"{f' in {directory}' if directory else ''}: {command}"
            for directory, command in sorted(
                ci_commands - local_commands - CI_ONLY_COMMANDS[job_name]
            )
        )
    return findings


def test_ci_recipe_findings_repository_commands_match() -> None:
    assert ci_recipe_findings(REPO_ROOT) == []


def _copy_module_justfile(tmp_path: Path) -> None:
    module = tmp_path / "backend/justfile"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(
        (REPO_ROOT / "backend/justfile").read_text(encoding="utf-8"), encoding="utf-8"
    )


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
    _copy_module_justfile(tmp_path)
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
    _copy_module_justfile(tmp_path)
    assert (
        "Lint & Type Check: extra CI command: uv run --locked mypy"
        in ci_recipe_findings(tmp_path)
    )


CI_ROOT_JUSTFILE = """\
mod backend

agents-check:
    uv run --locked python scripts/sync_agents.py --check

lint: backend::lint
    uv run --locked ruff check .

test-skills:
    uv run --locked pytest skills

test: backend::test
    uv run --locked pytest
"""

CI_BACKEND_JUSTFILE = """\
lint:
    uv run --locked ruff check .
    uv run --locked mypy

test:
    uv run --locked pytest --cov
"""

CI_WORKFLOW = """\
jobs:
  lint:
    name: Lint & Type Check
    steps:
      - run: |
          uv run --locked python scripts/sync_agents.py --check
          uv run --locked ruff check .
          uv run --locked pytest skills
      - name: Backend
        working-directory: backend
        run: |
          uv run --locked ruff check .
          uv run --locked mypy
  coverage:
    name: Coverage
    steps:
      - run: uv run --locked pytest
      - working-directory: ./backend/
        run: uv run --locked pytest --cov
"""


def _ci_root(tmp_path: Path, workflow: str) -> Path:
    for relative, text in {
        JUSTFILE: CI_ROOT_JUSTFILE,
        "backend/justfile": CI_BACKEND_JUSTFILE,
        ".github/workflows/ci.yml": workflow,
    }.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(text, encoding="utf-8")
    return tmp_path


def test_ci_recipe_findings_module_steps_in_module_directory_pass(
    tmp_path: Path,
) -> None:
    assert ci_recipe_findings(_ci_root(tmp_path, CI_WORKFLOW)) == []


def test_ci_recipe_findings_job_default_directory_counts(tmp_path: Path) -> None:
    workflow = CI_WORKFLOW.replace(
        "    name: Coverage\n    steps:\n"
        "      - run: uv run --locked pytest\n"
        "      - working-directory: ./backend/\n"
        "        run: uv run --locked pytest --cov\n",
        "    name: Coverage\n"
        "    defaults:\n      run:\n        working-directory: backend\n"
        "    steps:\n"
        "      - working-directory: .\n        run: uv run --locked pytest\n"
        "      - run: uv run --locked pytest --cov\n",
    )

    assert ci_recipe_findings(_ci_root(tmp_path, workflow)) == []


def test_ci_recipe_findings_module_line_outside_its_directory_is_rejected(
    tmp_path: Path,
) -> None:
    workflow = CI_WORKFLOW.replace("        working-directory: backend\n", "")

    assert ci_recipe_findings(_ci_root(tmp_path, workflow)) == [
        (
            "Lint & Type Check: backend::lint command not in a step with "
            "`working-directory: backend`: uv run --locked ruff check ."
        ),
        (
            "Lint & Type Check: backend::lint command not in a step with "
            "`working-directory: backend`: uv run --locked mypy"
        ),
        "Lint & Type Check: extra CI command: uv run --locked mypy",
    ]


def test_ci_recipe_findings_module_line_missing_is_rejected(tmp_path: Path) -> None:
    workflow = CI_WORKFLOW.replace(
        "      - working-directory: ./backend/\n        run: uv run --locked pytest --cov\n",
        "",
    )

    assert ci_recipe_findings(_ci_root(tmp_path, workflow)) == [
        "Coverage: missing backend::test command: uv run --locked pytest --cov"
    ]


def test_ci_recipe_findings_root_line_only_in_module_directory_is_rejected(
    tmp_path: Path,
) -> None:
    workflow = CI_WORKFLOW.replace(
        "      - run: uv run --locked pytest\n",
        "      - working-directory: backend\n        run: uv run --locked pytest\n",
    )

    assert ci_recipe_findings(_ci_root(tmp_path, workflow)) == [
        (
            "Coverage: test command not in a step with no `working-directory`: "
            "uv run --locked pytest"
        ),
        "Coverage: extra CI command in backend: uv run --locked pytest",
    ]


def test_ci_recipe_findings_module_recipe_without_body_fails(tmp_path: Path) -> None:
    root = _ci_root(tmp_path, CI_WORKFLOW)
    (root / "backend/justfile").write_text(
        "lint: test\n    # only a comment\n\ntest:\n    uv run --locked pytest --cov\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="recipe backend::lint has no commands"):
        ci_recipe_findings(root)


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
