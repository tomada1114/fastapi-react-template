"""(a) Every skill loads in both hosts; (b) AGENTS.md's Skills table indexes them.

A skill with a stray frontmatter key, a ``name`` that disagrees with its
directory, a non-ASCII or overlong description, or a nested ``SKILL.md``
mirrors cleanly into ``.claude/skills/`` and then silently never loads (or
loads twice); one with no Skills-table row is never found by a reader. The
rules are the ``authoring-skills`` skill's "Frontmatter" and "Size and
structure". The frontmatter is read strictly with the stdlib: ``key: value``
lines whose value is a plain or quoted one-line string or a ``>``/``|`` block
scalar; anything else is reported, never guessed at.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    type MakeSkill = Callable[..., Path]

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ".agents/skills"
AUTHORING_SKILL = f"{SKILLS_DIR}/authoring-skills/SKILL.md"
# authoring-skills "Frontmatter": "at most 600 characters of printable ASCII".
DESCRIPTION_LIMIT = 600
# authoring-skills "Size and structure": "never exceed 200 (physical lines after
# the frontmatter, blanks included)".
BODY_LIMIT = 200
KEYS = frozenset({"name", "description"})
SKILLS_HEADING = "## Skills"

_FIELD = re.compile(r"^(?P<key>[A-Za-z0-9_-]+):(?:[ \t]+(?P<value>.*?))?[ \t]*$")
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_BLOCK_SCALARS = frozenset({">", ">-", "|", "|-"})
# authoring-skills "Frontmatter": `description` is "a folded block scalar
# (`description: >`)"; the strip-chomping `>-` is the same scalar.
_FOLDED = frozenset({">", ">-"})
# Plain one-line values a strict YAML parser rejects or cuts short.
_PLAIN_TRAPS = re.compile(r": |:\t|:$| #|\t#|^\? |^- |^[\[{&*!%@`|>]")
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")


def test_mypy_targets_cover_authored_production_scripts() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy = config["tool"]["mypy"]
    targets = mypy["files"]
    assert {"src", "scripts", "tests"} <= set(targets)
    assert mypy["strict"] is True
    covered = {
        Path(path).resolve() for target in targets for path in REPO_ROOT.glob(target)
    }
    production = set((REPO_ROOT / SKILLS_DIR).glob("*/scripts/*.py"))
    assert production <= covered
    # Parts relative to the repository root: a checkout under a `.claude/`
    # directory (a Claude Code worktree in .claude/worktrees/) is not a mirror.
    assert not any(
        ".claude" in path.relative_to(REPO_ROOT).parts
        or (path.is_file() and path.parent.name == "tests")
        for path in covered
    )


def test_mypy_hook_uses_the_shared_target_configuration() -> None:
    hooks = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "entry: uv run --locked mypy\n" in hooks


class FrontmatterError(ValueError):
    """A SKILL.md frontmatter is not the strict shape a skill needs."""


def _block_scalar(indicator: str, block: list[str]) -> str:
    lines = [line.strip() for line in block]
    if indicator.startswith("|"):
        return "\n".join(lines).strip()
    paragraphs = " ".join(line or "\n" for line in lines).replace(" \n ", "\n")
    return paragraphs.strip()


def _value(key: str, raw: str, block: list[str]) -> str | None:
    """Return a field's string value, or None for another key's nested block."""
    if raw in _BLOCK_SCALARS:
        if not block:
            msg = f"{key}: empty block scalar"
            raise FrontmatterError(msg)
        return _block_scalar(raw, block)
    if block and raw:
        msg = f"{key}: a plain value continued on the next line; write `{key}: >`"
        raise FrontmatterError(msg)
    if block:
        if key in KEYS:
            msg = f"{key}: holds a nested mapping or list, not a string"
            raise FrontmatterError(msg)
        return None
    if raw[:1] in {'"', "'"}:
        quote = raw[0]
        inner = raw[1:-1]
        if len(raw) < 2 or raw[-1] != quote or quote in inner or "\\" in inner:
            msg = f"{key}: unsupported quoted value {raw!r}"
            raise FrontmatterError(msg)
        return inner
    if _PLAIN_TRAPS.search(raw):
        msg = f"{key}: a strict YAML parser rejects or cuts {raw!r}"
        raise FrontmatterError(msg)
    return raw


def parse_frontmatter(text: str) -> tuple[dict[str, str | None], dict[str, str], int]:
    """Return the fields, each field's raw inline form, and the closing line index.

    Raises:
        FrontmatterError: When the block is missing, unclosed, or unreadable.
    """
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        msg = "does not open with a --- line"
        raise FrontmatterError(msg)
    try:
        end = lines.index("---", 1)
    except ValueError:
        msg = "has no closing --- line"
        raise FrontmatterError(msg) from None
    fields: dict[str, str | None] = {}
    forms: dict[str, str] = {}
    index = 1
    while index < end:
        if not lines[index].strip():
            index += 1
            continue
        if lines[index].startswith("#"):
            msg = f"line {index + 1}: a comment, which the frontmatter may not hold"
            raise FrontmatterError(msg)
        match = _FIELD.match(lines[index])
        if match is None:
            msg = f"line {index + 1}: not a `key: value` line: {lines[index]!r}"
            raise FrontmatterError(msg)
        key = match["key"]
        if key in fields:
            msg = f"line {index + 1}: duplicate key {key!r}"
            raise FrontmatterError(msg)
        index += 1
        block: list[str] = []
        while index < end and (not lines[index].strip() or lines[index][0] in " \t"):
            block.append(lines[index])
            index += 1
        while block and not block[-1].strip():
            block.pop()
        forms[key] = match["value"] or ""
        fields[key] = _value(key, forms[key], block)
    return fields, forms, end


def _description_problem(description: str | None) -> str | None:
    if not description:
        return "description is missing, empty, or not a string"
    bad = sorted({char for char in description if not 32 <= ord(char) < 127} - {"\n"})
    if bad:
        return f"description has non-ASCII or control characters {bad}"
    if len(description) > DESCRIPTION_LIMIT:
        return (
            f"description is {len(description)} characters, over the "
            f"{DESCRIPTION_LIMIT} authoring-skills allows"
        )
    return None


def _skill_problems(skill: Path, directory: str) -> list[str]:
    text = skill.read_text(encoding="utf-8")
    try:
        fields, forms, end = parse_frontmatter(text)
    except FrontmatterError as exc:
        return [f"frontmatter {exc}"]
    problems: list[str] = []
    if extra := sorted(fields.keys() - KEYS):
        problems.append(
            f"frontmatter has keys other than name and description: {extra}"
        )
    if fields.get("name") != directory:
        problems.append(
            f"name {fields.get('name')!r} does not match its directory {directory!r}"
        )
    elif not _NAME.match(directory):
        problems.append(f"name {directory!r} is not lowercase letters, digits, hyphens")
    if problem := _description_problem(fields.get("description")):
        problems.append(problem)
    elif forms["description"] not in _FOLDED:
        problems.append(
            "description is not a folded block scalar (`description: >`), as "
            "authoring-skills requires"
        )
    body = len(text.splitlines()) - end - 1
    if body > BODY_LIMIT:
        problems.append(f"body is {body} lines, over {BODY_LIMIT}")
    return problems


def skill_dirs(root: Path) -> list[Path]:
    """Return every skill directory under ``.agents/skills``, sorted."""
    base = root / SKILLS_DIR
    return sorted(path for path in base.iterdir() if path.is_dir())


def skill_findings(root: Path) -> list[str]:
    """Return every frontmatter, size, and nesting problem of the skills."""
    if not (root / SKILLS_DIR).is_dir():
        return [f"{SKILLS_DIR} is missing"]
    findings: list[str] = []
    for directory in skill_dirs(root):
        skill = directory / "SKILL.md"
        relative = skill.relative_to(root).as_posix()
        findings.extend(
            f"{nested.relative_to(root).as_posix()}: a nested SKILL.md registers "
            "as a second, nameless skill"
            for nested in sorted(directory.rglob("SKILL.md"))
            if nested != skill
        )
        if not skill.is_file():
            findings.append(f"{relative}: missing")
            continue
        findings.extend(
            f"{relative}: {problem}"
            for problem in _skill_problems(skill, directory.name)
        )
    return findings


def _skills_table(agents_text: str) -> list[str] | None:
    """Return the first cell of each row of the Skills table, or None."""
    lines = agents_text.splitlines()
    try:
        start = lines.index(SKILLS_HEADING)
    except ValueError:
        return None
    rows: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        if line.startswith("|"):
            rows.append(line)
        elif rows:
            break
    cells = [row.strip().strip("|").split("|")[0].strip() for row in rows]
    body = [cell for cell in cells[1:] if not _SEPARATOR_CELL.match(cell)]
    return [cell.strip("`").strip() for cell in body] if rows else None


def skills_index_findings(root: Path) -> list[str]:
    """Return how AGENTS.md's Skills table disagrees with the skill directories."""
    listed = _skills_table((root / "AGENTS.md").read_text(encoding="utf-8"))
    if listed is None:
        return [f"AGENTS.md: no table under {SKILLS_HEADING!r}"]
    dirs = (
        {path.name for path in skill_dirs(root)}
        if (root / SKILLS_DIR).is_dir()
        else set()
    )
    findings = [
        f"AGENTS.md: the Skills table lists {name!r} more than once"
        for name in sorted({name for name in listed if listed.count(name) > 1})
    ]
    findings.extend(
        f"AGENTS.md: the Skills table has no row for {SKILLS_DIR}/{name}"
        for name in sorted(dirs - set(listed))
    )
    findings.extend(
        f"AGENTS.md: the Skills table lists {name!r}, which is not a directory "
        f"under {SKILLS_DIR}"
        for name in sorted(set(listed) - dirs)
    )
    return findings


# --- the repository ---


def test_skills_on_repository_load_in_both_hosts() -> None:
    assert skill_findings(REPO_ROOT) == []


def test_skills_index_on_repository_matches_directories() -> None:
    assert skills_index_findings(REPO_ROOT) == []


def test_limits_match_authoring_skills() -> None:
    text = (REPO_ROOT / AUTHORING_SKILL).read_text(encoding="utf-8")
    prose = " ".join(text.split())

    assert f"at most {DESCRIPTION_LIMIT} characters of printable ASCII" in prose
    assert f"never exceed {BODY_LIMIT}" in prose


# --- fixtures ---

GOOD_FRONTMATTER = "name: {name}\ndescription: >\n  Use when testing the harness.\n"


@pytest.fixture
def make_skill(tmp_path: Path) -> MakeSkill:
    def make(
        directory: str = "foo",
        frontmatter: str | None = None,
        body_lines: int = 3,
        *,
        rows: tuple[str, ...] | None = None,
    ) -> Path:
        skill = tmp_path / SKILLS_DIR / directory / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        head = (
            GOOD_FRONTMATTER.format(name=directory)
            if frontmatter is None
            else frontmatter
        )
        skill.write_text(f"---\n{head}---\n" + "body\n" * body_lines, encoding="utf-8")
        listed = (directory,) if rows is None else rows
        table = "".join(f"| `{name}` | when |\n" for name in listed)
        (tmp_path / "AGENTS.md").write_text(
            f"# Guide\n\n{SKILLS_HEADING}\n\nIntro.\n\n| Skill | Load it when |\n"
            f"|---|---|\n{table}\n## Sub-agents\n",
            encoding="utf-8",
        )
        return tmp_path

    return make


def test_skill_findings_well_formed_skill_passes(make_skill: MakeSkill) -> None:
    root = make_skill(body_lines=BODY_LIMIT)

    assert skill_findings(root) == []
    assert skills_index_findings(root) == []


@pytest.mark.parametrize(
    ("frontmatter", "problem"),
    [
        pytest.param(
            "name: bar\ndescription: >\n  x\n",
            "name 'bar' does not match its directory 'foo'",
            id="name-mismatch",
        ),
        pytest.param(
            "name: foo\ndescription: >\n  x\nallowed-tools: Bash\n",
            "frontmatter has keys other than name and description: ['allowed-tools']",
            id="extra-key",
        ),
        pytest.param(
            "name: foo\ndescription: >\n  x\nmetadata:\n  platforms: codex\n",
            "frontmatter has keys other than name and description: ['metadata']",
            id="nested-extra-key",
        ),
        pytest.param(
            "name: foo\n",
            "description is missing, empty, or not a string",
            id="no-description",
        ),
        pytest.param(
            "name: foo\ndescription: >\n  Use when café breaks.\n",
            "description has non-ASCII or control characters ['é']",
            id="non-ascii",
        ),
        pytest.param(
            "name: foo\ndescription: >\n  " + "x" * (DESCRIPTION_LIMIT + 1) + "\n",
            f"description is {DESCRIPTION_LIMIT + 1} characters, over the "
            f"{DESCRIPTION_LIMIT} authoring-skills allows",
            id="over-limit",
        ),
        pytest.param(
            "name: foo\ndescription: Use when: things break\n",
            "frontmatter description: a strict YAML parser rejects or cuts "
            "'Use when: things break'",
            id="colon-in-plain-value",
        ),
        pytest.param(
            "name: foo\ndescription: Use when the harness runs\n",
            "description is not a folded block scalar (`description: >`), as "
            "authoring-skills requires",
            id="plain-description",
        ),
        pytest.param(
            "name: foo:\ndescription: >\n  x\n",
            "frontmatter name: a strict YAML parser rejects or cuts 'foo:'",
            id="value-ending-in-colon",
        ),
        pytest.param(
            "name: ? foo\ndescription: >\n  x\n",
            "frontmatter name: a strict YAML parser rejects or cuts '? foo'",
            id="value-starting-with-question-mark",
        ),
        pytest.param(
            "name: foo\t# skill\ndescription: >\n  x\n",
            "frontmatter name: a strict YAML parser rejects or cuts 'foo\\t# skill'",
            id="value-with-tab-comment",
        ),
        pytest.param(
            "name: foo\nname: foo\ndescription: >\n  x\n",
            "frontmatter line 3: duplicate key 'name'",
            id="duplicate-key",
        ),
        pytest.param(
            "name: foo\n- description\n",
            "frontmatter line 3: not a `key: value` line: '- description'",
            id="unreadable-line",
        ),
        pytest.param(
            "# a skill\nname: foo\ndescription: >\n  x\n",
            "frontmatter line 2: a comment, which the frontmatter may not hold",
            id="comment-line",
        ),
        pytest.param(
            "name: foo\ndescription: Use when\n  the harness runs\n",
            "frontmatter description: a plain value continued on the next line; "
            "write `description: >`",
            id="multi-line-plain",
        ),
        pytest.param(
            "name: foo\ndescription:\n  when: always\n",
            "frontmatter description: holds a nested mapping or list, not a string",
            id="nested-description",
        ),
    ],
)
def test_skill_findings_bad_frontmatter_names_skill(
    make_skill: MakeSkill, frontmatter: str, problem: str
) -> None:
    root = make_skill(frontmatter=frontmatter)

    assert skill_findings(root) == [f"{SKILLS_DIR}/foo/SKILL.md: {problem}"]


def test_skill_findings_description_at_limit_passes(make_skill: MakeSkill) -> None:
    description = ("word " * DESCRIPTION_LIMIT)[: DESCRIPTION_LIMIT - 1] + "x"
    assert len(description) == DESCRIPTION_LIMIT
    root = make_skill(frontmatter=f"name: foo\ndescription: >\n  {description}\n")

    assert skill_findings(root) == []


def test_skill_findings_blank_line_between_keys_passes(make_skill: MakeSkill) -> None:
    root = make_skill(frontmatter="name: foo\n\ndescription: >\n  x\n\n")

    assert skill_findings(root) == []


def test_skill_findings_body_over_limit_fails(make_skill: MakeSkill) -> None:
    root = make_skill(body_lines=BODY_LIMIT + 1)

    assert skill_findings(root) == [
        f"{SKILLS_DIR}/foo/SKILL.md: body is {BODY_LIMIT + 1} lines, over {BODY_LIMIT}"
    ]


def test_skill_findings_nested_skill_md_fails(make_skill: MakeSkill) -> None:
    root = make_skill()
    nested = root / SKILLS_DIR / "foo" / "references" / "SKILL.md"
    nested.parent.mkdir()
    nested.write_text("# nested\n", encoding="utf-8")

    assert skill_findings(root) == [
        (
            f"{SKILLS_DIR}/foo/references/SKILL.md: a nested SKILL.md registers as a "
            "second, nameless skill"
        )
    ]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        pytest.param("# no frontmatter\n", "does not open with a --- line", id="none"),
        pytest.param("---\nname: foo\n", "has no closing --- line", id="unclosed"),
    ],
)
def test_skill_findings_missing_frontmatter_fails(
    make_skill: MakeSkill, text: str, problem: str
) -> None:
    root = make_skill()
    (root / SKILLS_DIR / "foo" / "SKILL.md").write_text(text, encoding="utf-8")

    assert skill_findings(root) == [f"{SKILLS_DIR}/foo/SKILL.md: frontmatter {problem}"]


def test_skill_findings_directory_without_skill_md_fails(make_skill: MakeSkill) -> None:
    root = make_skill()
    (root / SKILLS_DIR / "empty").mkdir()

    assert skill_findings(root) == [f"{SKILLS_DIR}/empty/SKILL.md: missing"]


@pytest.mark.parametrize(
    ("rows", "finding"),
    [
        pytest.param(
            (),
            f"AGENTS.md: the Skills table has no row for {SKILLS_DIR}/foo",
            id="missing-row",
        ),
        pytest.param(
            ("foo", "gone"),
            f"AGENTS.md: the Skills table lists 'gone', which is not a directory "
            f"under {SKILLS_DIR}",
            id="stale-row",
        ),
        pytest.param(
            ("foo", "foo"),
            "AGENTS.md: the Skills table lists 'foo' more than once",
            id="duplicate-row",
        ),
    ],
)
def test_skills_index_findings_disagreeing_table_fails(
    make_skill: MakeSkill, rows: tuple[str, ...], finding: str
) -> None:
    root = make_skill(rows=rows)

    assert skills_index_findings(root) == [finding]


def test_skills_index_findings_without_skills_heading_fails(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Guide\n", encoding="utf-8")

    assert skills_index_findings(tmp_path) == [
        f"AGENTS.md: no table under {SKILLS_HEADING!r}"
    ]
