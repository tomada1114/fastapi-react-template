"""Keep the core deterministic and independent of frameworks and I/O.

ALLOWED_STDLIB is the authoritative import boundary; Ruff's TID251 is a
fast subset. The AST call check rejects bare I/O and dynamic-execution
builtins, recognizable date/datetime clock reads, local-time APIs without
explicit timezones, and the uuid generators that read a clock, randomness, or
the host. Both gates walk core subpackages and imports inside type-checking
branches.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import my_app.core

CORE_PACKAGE = "my_app.core"
CORE_DIR = Path(my_app.core.__file__).parent
# Pure, deterministic stdlib modules the core may import. Adding one is a
# reviewed edit: it must do no I/O and read no clock, randomness, or
# environment. Anything else goes behind a port (designing-core-logic).
ALLOWED_STDLIB = frozenset(
    {
        "__future__",
        "abc",
        "bisect",
        "collections",
        "copy",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "fractions",
        "functools",
        "heapq",
        "itertools",
        "math",
        "operator",
        "re",
        "statistics",
        "string",
        "textwrap",
        "types",
        "typing",
        # UUID values and deterministic generators are allowed; the calls below read a clock,
        # randomness, or the host, so the call check rejects them and ids
        # arrive through the IdFactory port.
        "uuid",
    }
)
FORBIDDEN_BUILTIN_CALLS = frozenset(
    {"open", "input", "print", "breakpoint", "exec", "eval", "compile", "__import__"}
)
CLOCK_READ_METHODS = frozenset({"now", "utcnow", "today"})
NONDETERMINISTIC_UUID_CALLS = frozenset({"uuid1", "uuid4", "uuid6", "uuid7", "getnode"})
CORE_MODULE_PATHS = sorted(CORE_DIR.rglob("*.py"))


def _package_of(path: Path) -> str:
    """Return the package a core file's relative imports are resolved against."""
    subpackages = path.relative_to(CORE_DIR).parent.parts
    return ".".join([CORE_PACKAGE, *subpackages])


def _imported_modules(source: str, package: str = CORE_PACKAGE) -> set[str]:
    """Return every module a core file imports, relative imports resolved."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        match node:
            case ast.Import(names=aliases):
                modules.update(alias.name for alias in aliases)
            case ast.ImportFrom(module=module, level=0) if module is not None:
                modules.add(module)
            case ast.ImportFrom(module=module, level=level) if level > 0:
                parts = package.split(".")
                parent = parts[: len(parts) - level + 1]
                modules.add(".".join([*parent, module] if module else parent))
    return modules


def _is_allowed(module: str) -> bool:
    top_level = module.partition(".")[0]
    is_core = module == CORE_PACKAGE or module.startswith(f"{CORE_PACKAGE}.")
    return is_core or top_level in ALLOWED_STDLIB


def _has_explicit_timezone(call: ast.Call, position: int) -> bool:
    timezone = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "tz"),
        call.args[position] if len(call.args) > position else None,
    )
    return timezone is not None and not (
        isinstance(timezone, ast.Constant) and timezone.value is None
    )


def _uses_local_timezone(call: ast.Call) -> bool:
    match call.func:
        case ast.Attribute(attr="astimezone"):
            return not _has_explicit_timezone(call, 0)
        case ast.Attribute(value=receiver, attr="fromtimestamp"):
            match receiver:
                case ast.Name(id="date") | ast.Attribute(attr="date"):
                    return True
                case ast.Name(id="datetime") | ast.Attribute(attr="datetime"):
                    return not _has_explicit_timezone(call, 1)
    return False


def _uuid8_uses_randomness(call: ast.Call) -> bool:
    """Require every custom block explicitly, as for timezone arguments above."""
    if any(isinstance(argument, ast.Starred) for argument in call.args):
        return True
    for position, name in enumerate(("a", "b", "c")):
        value = next(
            (keyword.value for keyword in call.keywords if keyword.arg == name),
            call.args[position] if len(call.args) > position else None,
        )
        if value is None or (isinstance(value, ast.Constant) and value.value is None):
            return True
    return False


def _forbidden_calls(source: str) -> set[str]:
    """Return forbidden calls with their source lines for actionable failures."""
    forbidden: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if _uses_local_timezone(node):
            forbidden.add(f"line {node.lineno}: {ast.unparse(node.func)}")
        match node.func:
            case ast.Name(id=name) if (
                name in FORBIDDEN_BUILTIN_CALLS
                or name in NONDETERMINISTIC_UUID_CALLS
                or (name == "uuid8" and _uuid8_uses_randomness(node))
            ):
                forbidden.add(f"line {node.lineno}: {name}")
            case ast.Attribute(
                value=ast.Name(id="uuid") | ast.Attribute(attr="uuid"), attr=generator
            ) if generator in NONDETERMINISTIC_UUID_CALLS or (
                generator == "uuid8" and _uuid8_uses_randomness(node)
            ):
                forbidden.add(f"line {node.lineno}: {ast.unparse(node.func)}")
            case ast.Attribute(value=receiver, attr=method) if (
                method in CLOCK_READ_METHODS
            ):
                match receiver:
                    case (
                        ast.Name(id="datetime" | "date")
                        | ast.Attribute(attr="datetime" | "date")
                    ):
                        forbidden.add(f"line {node.lineno}: {ast.unparse(node.func)}")
    return forbidden


def test_core_package_has_modules_to_check():
    assert CORE_DIR / "__init__.py" in CORE_MODULE_PATHS


@pytest.mark.parametrize(
    "path",
    CORE_MODULE_PATHS,
    ids=lambda path: path.relative_to(CORE_DIR).as_posix(),
)
def test_core_module_imports_only_stdlib_and_core(path):
    modules = _imported_modules(path.read_text(encoding="utf-8"), _package_of(path))

    disallowed = sorted(module for module in modules if not _is_allowed(module))

    assert disallowed == [], f"{path.name} imports {disallowed}"


@pytest.mark.parametrize(
    "path",
    CORE_MODULE_PATHS,
    ids=lambda path: path.relative_to(CORE_DIR).as_posix(),
)
def test_core_module_calls_no_io_builtin(path):
    forbidden = _forbidden_calls(path.read_text(encoding="utf-8"))

    assert forbidden == set(), f"{path.relative_to(CORE_DIR)} calls {sorted(forbidden)}"


@pytest.mark.parametrize(
    ("source", "module"),
    [
        pytest.param("import fastapi", "fastapi", id="fastapi"),
        pytest.param("import os", "os", id="os"),
        pytest.param("import socket", "socket", id="socket"),
        pytest.param("import subprocess", "subprocess", id="subprocess"),
        pytest.param(
            "from urllib.request import urlopen", "urllib.request", id="urllib"
        ),
        pytest.param(
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import os",
            "os",
            id="type-checking-io",
        ),
        pytest.param(
            "from typer.testing import CliRunner", "typer.testing", id="typer"
        ),
        pytest.param("import uvicorn", "uvicorn", id="uvicorn"),
        pytest.param("import sqlalchemy", "sqlalchemy", id="sqlalchemy"),
        pytest.param("import httpx", "httpx", id="httpx"),
        pytest.param("from pydantic import BaseModel", "pydantic", id="pydantic"),
        pytest.param("from .. import api", "my_app", id="relative-escape"),
        pytest.param("from ..adapters import memory", "my_app.adapters", id="adapters"),
    ],
)
def test_import_check_forbidden_import_is_rejected(source, module):
    modules = _imported_modules(source)

    assert module in modules
    assert not _is_allowed(module)


def test_import_check_subpackage_relative_escape_is_rejected():
    subpackage_file = CORE_DIR / "billing" / "invoices.py"

    modules = _imported_modules(
        "from ...adapters import sql", _package_of(subpackage_file)
    )

    assert modules == {"my_app.adapters"}
    assert not _is_allowed("my_app.adapters")


@pytest.mark.parametrize(
    ("source", "package"),
    [
        pytest.param("from datetime import datetime", CORE_PACKAGE, id="stdlib"),
        pytest.param("from decimal import Decimal", CORE_PACKAGE, id="decimal"),
        pytest.param("from uuid import UUID", CORE_PACKAGE, id="uuid-type"),
        pytest.param("import uuid", CORE_PACKAGE, id="uuid-module"),
        pytest.param(
            "from my_app.core.errors import AppError", CORE_PACKAGE, id="core-absolute"
        ),
        pytest.param("from .errors import AppError", CORE_PACKAGE, id="core-relative"),
        pytest.param(
            "from ..errors import AppError",
            f"{CORE_PACKAGE}.billing",
            id="subpackage-relative",
        ),
    ],
)
def test_import_check_allowed_import_is_accepted(source, package):
    assert all(_is_allowed(module) for module in _imported_modules(source, package))


@pytest.mark.parametrize(
    ("source", "call"),
    [
        pytest.param('open("x")', "open", id="open"),
        pytest.param('input("x")', "input", id="input"),
        pytest.param('print("x")', "print", id="print"),
        pytest.param("breakpoint()", "breakpoint", id="breakpoint"),
        pytest.param('exec("x")', "exec", id="exec"),
        pytest.param('eval("x")', "eval", id="eval"),
        pytest.param('compile("x", "x", "exec")', "compile", id="compile"),
        pytest.param('__import__("os")', "__import__", id="dynamic-import"),
        pytest.param("datetime.now(tz=UTC)", "datetime.now", id="datetime-now"),
        pytest.param("datetime.utcnow()", "datetime.utcnow", id="datetime-utcnow"),
        pytest.param("datetime.today()", "datetime.today", id="datetime-today"),
        pytest.param("date.today()", "date.today", id="date-today"),
        pytest.param(
            "datetime.datetime.now()", "datetime.datetime.now", id="module-datetime-now"
        ),
        pytest.param(
            "datetime.date.today()", "datetime.date.today", id="module-date-today"
        ),
        pytest.param("uuid.uuid1()", "uuid.uuid1", id="module-uuid1"),
        pytest.param("uuid.uuid4()", "uuid.uuid4", id="module-uuid4"),
        pytest.param("uuid.uuid6()", "uuid.uuid6", id="module-uuid6"),
        pytest.param("uuid.uuid7()", "uuid.uuid7", id="module-uuid7"),
        pytest.param("uuid.uuid8()", "uuid.uuid8", id="module-uuid8"),
        pytest.param("uuid.getnode()", "uuid.getnode", id="module-getnode"),
        pytest.param("uuid.uuid8(1, 2)", "uuid.uuid8", id="uuid8-missing-block"),
        pytest.param(
            "uuid.uuid8(1, None, 3)", "uuid.uuid8", id="uuid8-positional-none"
        ),
        pytest.param("uuid8(a=1, b=2)", "uuid8", id="uuid8-missing-keyword-block"),
        pytest.param("uuid8(a=1, b=2, c=None)", "uuid8", id="uuid8-keyword-none"),
        pytest.param("uuid8(*blocks)", "uuid8", id="uuid8-unpacked-blocks"),
        pytest.param("uuid8(**blocks)", "uuid8", id="uuid8-unpacked-keywords"),
        pytest.param("uuid1()", "uuid1", id="bare-uuid1"),
        pytest.param("uuid4()", "uuid4", id="bare-uuid4"),
        pytest.param("uuid6()", "uuid6", id="bare-uuid6"),
        pytest.param("uuid7()", "uuid7", id="bare-uuid7"),
        pytest.param("uuid8()", "uuid8", id="bare-uuid8"),
        pytest.param("getnode()", "getnode", id="bare-getnode"),
        pytest.param("ids.uuid.uuid8()", "ids.uuid.uuid8", id="attribute-uuid8"),
        pytest.param("ids.uuid.getnode()", "ids.uuid.getnode", id="attribute-getnode"),
        pytest.param("ids.uuid.uuid7()", "ids.uuid.uuid7", id="attribute-uuid7"),
    ],
)
def test_call_check_forbidden_call_is_rejected(source, call):
    assert _forbidden_calls(source) == {f"line 1: {call}"}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("datetime(2026, 10, 7)", id="datetime-construction"),
        pytest.param("date(2026, 10, 7)", id="date-construction"),
        pytest.param("value.today()", id="unrelated-receiver"),
        pytest.param("clock()", id="injected-clock"),
        pytest.param('message = "open(x)"', id="string-literal"),
        pytest.param("UUID(int=0)", id="uuid-construction"),
        pytest.param(
            'uuid.UUID("01900000-0000-7000-8000-000000000001")', id="uuid-parse"
        ),
        pytest.param('uuid.uuid5(uuid.NAMESPACE_URL, "x")', id="uuid5-deterministic"),
        pytest.param('uuid5(NAMESPACE_URL, "x")', id="bare-uuid5-deterministic"),
        pytest.param("uuid8(0, 0, 0)", id="uuid8-zero-blocks"),
        pytest.param("uuid.uuid8(1, 2, 3)", id="uuid8-positional-blocks"),
        pytest.param("uuid.uuid8(a=1, b=2, c=3)", id="uuid8-keyword-blocks"),
        pytest.param("uuid8(1, b=2, c=3)", id="uuid8-mixed-blocks"),
        pytest.param("ids.uuid.uuid8(c=3, a=1, b=2)", id="uuid8-attribute-blocks"),
        pytest.param("new_id()", id="injected-id-factory"),
        pytest.param("generator.uuid7()", id="unrelated-uuid-receiver"),
    ],
)
def test_call_check_allowed_call_is_accepted(source):
    assert _forbidden_calls(source) == set()


def test_call_check_nested_call_reports_source_line():
    source = "def read():\n    return open('x')"

    assert _forbidden_calls(source) == {"line 2: open"}


@pytest.mark.parametrize(
    ("source", "call"),
    [
        pytest.param(
            "datetime.fromtimestamp(0)", "datetime.fromtimestamp", id="timestamp-no-tz"
        ),
        pytest.param(
            "datetime.fromtimestamp(0, None)",
            "datetime.fromtimestamp",
            id="timestamp-positional-none",
        ),
        pytest.param(
            "datetime.fromtimestamp(0, tz=None)",
            "datetime.fromtimestamp",
            id="timestamp-keyword-none",
        ),
        pytest.param(
            "datetime.fromtimestamp(timestamp=0)",
            "datetime.fromtimestamp",
            id="timestamp-keyword-no-tz",
        ),
        pytest.param(
            "datetime.datetime.fromtimestamp(0)",
            "datetime.datetime.fromtimestamp",
            id="module-timestamp",
        ),
        pytest.param(
            "date.fromtimestamp(0)", "date.fromtimestamp", id="date-timestamp"
        ),
        pytest.param(
            "datetime.date.fromtimestamp(0)",
            "datetime.date.fromtimestamp",
            id="module-date-timestamp",
        ),
        pytest.param(
            "some_datetime.astimezone()",
            "some_datetime.astimezone",
            id="conversion-no-tz",
        ),
        pytest.param(
            "some_datetime.astimezone(None)",
            "some_datetime.astimezone",
            id="conversion-positional-none",
        ),
        pytest.param(
            "some_datetime.astimezone(tz=None)",
            "some_datetime.astimezone",
            id="conversion-keyword-none",
        ),
        pytest.param(
            "record.timestamp.astimezone()",
            "record.timestamp.astimezone",
            id="attribute-conversion-no-tz",
        ),
    ],
)
def test_call_check_local_timezone_dependency_is_rejected(source, call):
    assert _forbidden_calls(source) == {f"line 1: {call}"}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("datetime.fromtimestamp(0, UTC)", id="timestamp-positional-tz"),
        pytest.param("datetime.fromtimestamp(0, tz=UTC)", id="timestamp-keyword-tz"),
        pytest.param(
            "datetime.fromtimestamp(timestamp=0, tz=UTC)", id="timestamp-all-keywords"
        ),
        pytest.param(
            "datetime.datetime.fromtimestamp(0, UTC)", id="module-timestamp-tz"
        ),
        pytest.param("some_datetime.astimezone(UTC)", id="conversion-positional-tz"),
        pytest.param("some_datetime.astimezone(tz=UTC)", id="conversion-keyword-tz"),
        pytest.param("record.timestamp.astimezone(UTC)", id="attribute-conversion-tz"),
    ],
)
def test_call_check_explicit_timezone_is_accepted(source):
    assert _forbidden_calls(source) == set()
