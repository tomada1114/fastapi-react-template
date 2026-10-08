"""Whether a job with ``needs:`` fails on its own when a needed job did not succeed.

A required job guarded by ``!cancelled()``/``always()`` runs after a needed job
failed, so unless one of its steps fails on that result, the required check goes
green over the failure. ``skipped`` and ``cancelled`` are not ``success`` either,
so a required job cannot depend on a job that is skipped on purpose.

The shell is read as text, never run, so only a few step shapes count. A step
counts for needed job ``X`` when it has no ``continue-on-error``, its ``run:`` is
an inline scalar or a literal ``|`` block, any lines before the shape below are
plain ``echo`` lines, and either

1. its ``if:`` is ``needs.X.result != 'success'`` (several joined by ``||``
   count for each), and its first command after the echoes is ``exit N``; or
2. its ``if:`` is absent, ``success()``, ``always()``, or ``!cancelled()``, and
   its first command after the echoes is

   - ``if [ "$R" != "success" ]; then`` followed by echo lines, ``exit N``, and
     ``fi`` (Coverage's shape); or
   - ``[ "$R" = "success" ] || exit N``, or ``[ "$R" != "success" ] && exit N``,

   where ``[[ ]]`` may stand for ``[ ]``, ``==`` for ``=``, the quotes are
   optional, ``N`` is a literal from 1, and ``"$R"`` is ``"${{ needs.X.result }}"``
   or a variable the step's ``env:`` (or else the job's) sets to exactly that.

Anything else does not count: ``needs.*.result``, ``contains(...)``, a step
``if:`` with another condition, an inverted comparison, an ``exit`` inside a
string, a subshell, or after other commands, and a folded ``>`` block. That makes
the check fail rather than pass on a step it cannot read. An unreadable
``needs:`` or an incorrectly shaped ``env:``/``run:`` raises
`UnreadableYamlError`; valid inline mappings follow the same policy.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests.harness._shell import split_comment
from tests.harness._workflows import Check, entry_value, steps
from tests.harness._yaml import (
    Mapping,
    UnreadableYamlError,
    as_mapping,
    as_str,
    scalar,
    scalar_list,
    scalar_style,
)

if TYPE_CHECKING:
    from pathlib import Path

_ID = r"[A-Za-z_][A-Za-z0-9_-]*"
_JOB_ID = re.compile(rf"^{_ID}$")
_RESULT = re.compile(rf"^\$\{{\{{\s*needs\.(?P<job>{_ID})\.result\s*\}}\}}$")
_VARIABLE = re.compile(r"^\$(?:(?P<name>[A-Za-z_]\w*)|\{(?P<braced>[A-Za-z_]\w*)\})$")
_NOT_SUCCESS = re.compile(
    rf"^\(?\s*needs\.(?P<job>{_ID})\.result\s*!=\s*'success'\s*\)?$"
)
_STEP_RUNS = frozenset({"success()", "always()", "!cancelled()"})

_OPERAND = r"(?P<operand>\"[^\"]*\"|\$\{?[A-Za-z_]\w*\}?)"
_SUCCESS = r"(?:success|\"success\"|'success')"
_TEST = (
    rf"(?P<open>\[\[?)\s+{_OPERAND}\s+(?P<op>!=|==?)\s+{_SUCCESS}\s+(?P<close>\]\]?)"
)
_IF_LINE = re.compile(rf"^if\s+{_TEST}\s*;\s*then$")
_GUARD_LINE = re.compile(rf"^{_TEST}\s*(?P<list>\|\||&&)\s*exit\s+[1-9][0-9]*$")
_EXIT_LINE = re.compile(r"^exit\s+[1-9][0-9]*$")
_ECHO_LINE = re.compile(
    r"^echo(?:\s+(?:\"[^\"`\\]*\"|'[^']*'|[\w:.,/=+@%-]+))*(?:\s+>&2)?$"
)


def _needs(job: Mapping, path: Path) -> list[str]:
    """Return the job ids a job's ``needs:`` names."""
    if "needs" not in job:
        return []
    names = scalar_list(job["needs"], path, where="needs")
    if not names or not all(_JOB_ID.match(name) for name in names):
        msg = f"{path.name}: cannot read `needs: {job['needs']}`"
        raise UnreadableYamlError(msg)
    return names


def _env(entry: object, path: Path) -> dict[str, str]:
    """Read both inline and block environment mappings."""
    if entry is None:
        return {}
    return {
        name: scalar(value, f"{path}: env.{name}")
        for name, value in as_mapping(entry, f"{path}: env").items()
    }


def _run_lines(entry: object, path: Path) -> list[str] | None:
    """Keep folded blocks untrusted; literal blocks retain shell line boundaries."""
    value = as_str(entry, f"{path}: run")
    if scalar_style(entry) == ">":
        return None
    return [split_comment(line)[0] for line in value.splitlines()]


def _after_echoes(lines: list[str]) -> list[str]:
    """Return the lines from the first one that is not a plain ``echo``."""
    for index, line in enumerate(lines):
        if not _ECHO_LINE.match(line) or "${{" in line or "$(" in line:
            return lines[index:]
    return []


def _operand_job(operand: str, env: dict[str, str]) -> str | None:
    """Return the job whose result ``operand`` holds, or None."""
    text = operand[1:-1] if operand.startswith('"') else operand
    if variable := _VARIABLE.match(text):
        text = env.get(variable["name"] or variable["braced"], "")
    result = _RESULT.match(text)
    return result["job"] if result else None


def _brackets_match(match: re.Match[str]) -> bool:
    return len(match["open"]) == len(match["close"])


def _compared_job(lines: list[str], env: dict[str, str]) -> str | None:
    """Return the job a step's comparison shape fails on, or None."""
    if not lines:
        return None
    first = lines[0]
    if (guard := _GUARD_LINE.match(first)) and _brackets_match(guard):
        is_negated = guard["op"] == "!="
        if is_negated == (guard["list"] == "&&"):
            return _operand_job(guard["operand"], env)
        return None
    block = _IF_LINE.match(first)
    if block is None or not _brackets_match(block) or block["op"] != "!=":
        return None
    body = _after_echoes(lines[1:])
    if len(body) < 2 or not _EXIT_LINE.match(body[0]) or body[1] != "fi":
        return None
    return _operand_job(block["operand"], env)


def _failed_needs(step: Mapping, job_env: dict[str, str], path: Path) -> set[str]:
    """Return the needed jobs whose non-success result makes this step fail."""
    if "run" not in step:
        return set()
    if entry_value(step.get("continue-on-error")) not in {None, "false"}:
        return set()
    lines = _run_lines(step["run"], path)
    if lines is None:
        return set()
    commands = _after_echoes([line.strip() for line in lines])
    if_expr = entry_value(step.get("if"))
    body = None if if_expr is None else _expression_body(if_expr)
    if body is not None and body not in _STEP_RUNS:
        terms = [_NOT_SUCCESS.match(term.strip()) for term in body.split("||")]
        if not all(terms) or not commands or not _EXIT_LINE.match(commands[0]):
            return set()
        return {term["job"] for term in terms if term}
    env = {**job_env, **_env(step.get("env"), path)}
    job = _compared_job(commands, env)
    return set() if job is None else {job}


def _expression_body(expr: str) -> str:
    # `entry_value` has already removed the quotes around the whole scalar.
    text = expr.strip()
    if text.startswith("${{") and text.endswith("}}"):
        return text[3:-2].strip()
    return text


def _job_unfailed_needs(job: Mapping, path: Path) -> list[str]:
    needed = _needs(job, path)
    if not needed:
        return []
    job_env = _env(job.get("env"), path)
    failed = {
        name for step in steps(job, path) for name in _failed_needs(step, job_env, path)
    }
    return [name for name in needed if name not in failed]


def unfailed_needs(check: Check) -> tuple[str, ...]:
    """Return the needed jobs no step fails on, across every job of ``check``.

    Read only for a required context, so a job no ruleset requires never makes
    the check fail on a layout this module cannot read.
    """
    found = (
        name
        for source in check.jobs
        for name in _job_unfailed_needs(source.job, source.path)
    )
    return tuple(dict.fromkeys(found))
