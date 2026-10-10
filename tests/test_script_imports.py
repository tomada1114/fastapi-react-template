"""Keep repository and skill scripts runnable without third-party packages."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
# The inventory includes modules from every platform. Keep the scripts portable
# across macOS and Linux, including when the check runs on either host.
# CPython PC/config.c and Modules/Setup.stdlib.in (3.14), checked 2026-10-09:
# https://github.com/python/cpython/blob/3.14/PC/config.c
# https://github.com/python/cpython/blob/3.14/Modules/Setup.stdlib.in
HOST_SPECIFIC_MODULES = frozenset(
    {"winreg", "msvcrt", "winsound", "_winapi", "_overlapped", "_msi", "nt", "_scproxy"}
)
# Supported builds: ordinary POSIX CPython with core/bundled extensions intact;
# external-library extensions may be absent (including Apple's system Python).
# Do not infer availability from the check runner's installed extensions.
# CPython's optional build requirements and Setup.stdlib.in, checked 2026-10-10:
# https://docs.python.org/3.14/using/configure.html#requirements-for-optional-modules
# https://github.com/python/cpython/blob/3.14/Modules/Setup.stdlib.in
# hashlib, decimal and uuid retain their bundled/pure-Python fallbacks.
BUILD_OPTIONAL_MODULES = frozenset(
    {
        "_gdbm",
        "_dbm",
        "dbm.gnu",
        "dbm.ndbm",
        "dbm.sqlite3",
        "bz2",
        "_bz2",
        "lzma",
        "_lzma",
        "_zstd",
        "compression.zstd",
        "ctypes",
        "_ctypes",
        "curses",
        "_curses",
        "_curses_panel",
        "readline",
        "rlcompleter",
        "sqlite3",
        "_sqlite3",
        "ssl",
        "_ssl",
        "_hashlib",
        "tkinter",
        "_tkinter",
        "idlelib",
        "turtle",
        "turtledemo",
        "_uuid",
        "zlib",
        "gzip",
        "compression.bz2",
        "compression.gzip",
        "compression.lzma",
        "compression.zlib",
        "multiprocessing.sharedctypes",
    }
)
# CPython 3.10's platform-independent inventory, pinned to its source revision:
# https://github.com/python/cpython/blob/a8d15704295419e94f06e1e0727839113faabbf7/Python/stdlib_module_names.h
STDLIB_PY310 = frozenset(
    [
        "__future__",
        "_abc",
        "_aix_support",
        "_ast",
        "_asyncio",
        "_bisect",
        "_blake2",
        "_bootsubprocess",
        "_bz2",
        "_codecs",
        "_codecs_cn",
        "_codecs_hk",
        "_codecs_iso2022",
        "_codecs_jp",
        "_codecs_kr",
        "_codecs_tw",
        "_collections",
        "_collections_abc",
        "_compat_pickle",
        "_compression",
        "_contextvars",
        "_crypt",
        "_csv",
        "_ctypes",
        "_curses",
        "_curses_panel",
        "_datetime",
        "_dbm",
        "_decimal",
        "_elementtree",
        "_frozen_importlib",
        "_frozen_importlib_external",
        "_functools",
        "_gdbm",
        "_hashlib",
        "_heapq",
        "_imp",
        "_io",
        "_json",
        "_locale",
        "_lsprof",
        "_lzma",
        "_markupbase",
        "_md5",
        "_msi",
        "_multibytecodec",
        "_multiprocessing",
        "_opcode",
        "_operator",
        "_osx_support",
        "_overlapped",
        "_pickle",
        "_posixshmem",
        "_posixsubprocess",
        "_py_abc",
        "_pydecimal",
        "_pyio",
        "_queue",
        "_random",
        "_scproxy",
        "_sha1",
        "_sha256",
        "_sha3",
        "_sha512",
        "_signal",
        "_sitebuiltins",
        "_socket",
        "_sqlite3",
        "_sre",
        "_ssl",
        "_stat",
        "_statistics",
        "_string",
        "_strptime",
        "_struct",
        "_symtable",
        "_thread",
        "_threading_local",
        "_tkinter",
        "_tracemalloc",
        "_uuid",
        "_warnings",
        "_weakref",
        "_weakrefset",
        "_winapi",
        "_zoneinfo",
        "abc",
        "aifc",
        "antigravity",
        "argparse",
        "array",
        "ast",
        "asynchat",
        "asyncio",
        "asyncore",
        "atexit",
        "audioop",
        "base64",
        "bdb",
        "binascii",
        "binhex",
        "bisect",
        "builtins",
        "bz2",
        "cProfile",
        "calendar",
        "cgi",
        "cgitb",
        "chunk",
        "cmath",
        "cmd",
        "code",
        "codecs",
        "codeop",
        "collections",
        "colorsys",
        "compileall",
        "concurrent",
        "configparser",
        "contextlib",
        "contextvars",
        "copy",
        "copyreg",
        "crypt",
        "csv",
        "ctypes",
        "curses",
        "dataclasses",
        "datetime",
        "dbm",
        "decimal",
        "difflib",
        "dis",
        "distutils",
        "doctest",
        "email",
        "encodings",
        "ensurepip",
        "enum",
        "errno",
        "faulthandler",
        "fcntl",
        "filecmp",
        "fileinput",
        "fnmatch",
        "fractions",
        "ftplib",
        "functools",
        "gc",
        "genericpath",
        "getopt",
        "getpass",
        "gettext",
        "glob",
        "graphlib",
        "grp",
        "gzip",
        "hashlib",
        "heapq",
        "hmac",
        "html",
        "http",
        "idlelib",
        "imaplib",
        "imghdr",
        "imp",
        "importlib",
        "inspect",
        "io",
        "ipaddress",
        "itertools",
        "json",
        "keyword",
        "lib2to3",
        "linecache",
        "locale",
        "logging",
        "lzma",
        "mailbox",
        "mailcap",
        "marshal",
        "math",
        "mimetypes",
        "mmap",
        "modulefinder",
        "msilib",
        "msvcrt",
        "multiprocessing",
        "netrc",
        "nis",
        "nntplib",
        "nt",
        "ntpath",
        "nturl2path",
        "numbers",
        "opcode",
        "operator",
        "optparse",
        "os",
        "ossaudiodev",
        "pathlib",
        "pdb",
        "pickle",
        "pickletools",
        "pipes",
        "pkgutil",
        "platform",
        "plistlib",
        "poplib",
        "posix",
        "posixpath",
        "pprint",
        "profile",
        "pstats",
        "pty",
        "pwd",
        "py_compile",
        "pyclbr",
        "pydoc",
        "pydoc_data",
        "pyexpat",
        "queue",
        "quopri",
        "random",
        "re",
        "readline",
        "reprlib",
        "resource",
        "rlcompleter",
        "runpy",
        "sched",
        "secrets",
        "select",
        "selectors",
        "shelve",
        "shlex",
        "shutil",
        "signal",
        "site",
        "smtpd",
        "smtplib",
        "sndhdr",
        "socket",
        "socketserver",
        "spwd",
        "sqlite3",
        "sre_compile",
        "sre_constants",
        "sre_parse",
        "ssl",
        "stat",
        "statistics",
        "string",
        "stringprep",
        "struct",
        "subprocess",
        "sunau",
        "symtable",
        "sys",
        "sysconfig",
        "syslog",
        "tabnanny",
        "tarfile",
        "telnetlib",
        "tempfile",
        "termios",
        "textwrap",
        "this",
        "threading",
        "time",
        "timeit",
        "tkinter",
        "token",
        "tokenize",
        "trace",
        "traceback",
        "tracemalloc",
        "tty",
        "turtle",
        "turtledemo",
        "types",
        "typing",
        "unicodedata",
        "unittest",
        "urllib",
        "uu",
        "uuid",
        "venv",
        "warnings",
        "wave",
        "weakref",
        "webbrowser",
        "winreg",
        "winsound",
        "wsgiref",
        "xdrlib",
        "xml",
        "xmlrpc",
        "zipapp",
        "zipfile",
        "zipimport",
        "zlib",
        "zoneinfo",
    ]
)
# Python 3.9 also shipped these modules removed in 3.10. Sources:
# https://github.com/python/cpython/tree/0bbaf5de9744ae1acea3e2c9ad2257d1cc68e847/Lib
# https://github.com/python/cpython/tree/0bbaf5de9744ae1acea3e2c9ad2257d1cc68e847/Modules
STDLIB_PY39 = STDLIB_PY310 | {
    "_bootlocale",
    "_peg_parser",
    "formatter",
    "parser",
    "symbol",
}


# Known submodule gaps from each supported CPython minor's Lib tree.
# Frozen source trees, fetched through GitHub MCP on 2026-10-10:
# 3.9: 0bbaf5de9744ae1acea3e2c9ad2257d1cc68e847
# 3.10: a8d15704295419e94f06e1e0727839113faabbf7
# 3.11: 59d1bd5f0beb95f26771a96fe11eac1653d69ffa
# 3.12: 58ed60b7415e218ce3d608302e39b5e55bfb0e88
# 3.13: 24d048d3601c2f1d41fa357897c1c91bb0a0bc13
# 3.14: 8b0ab08ef18c6d7517126016aa82ed78387d45e4
# https://github.com/python/cpython/tree/8b0ab08ef18c6d7517126016aa82ed78387d45e4/Lib
# Exclude known paths missing in any minor of the supported range. Module-to-
# package moves count as the same module; os.path and collections.abc are aliases.
# Root inventories already reject packages absent from either endpoint.
INCOMPATIBLE_SUBMODULES_PY39 = frozenset(
    {
        "asyncio.graph",
        "asyncio.mixins",
        "asyncio.taskgroups",
        "asyncio.timeouts",
        "asyncio.tools",
        "concurrent.futures.interpreter",
        "concurrent.interpreters",
        "concurrent.interpreters._crossinterp",
        "concurrent.interpreters._queues",
        "ctypes._layout",
        "dbm.sqlite3",
        "encodings._win_cp_codecs",
        "ensurepip._bundled",
        "importlib._abc",
        "importlib._adapters",
        "importlib._common",
        "importlib.metadata._adapters",
        "importlib.metadata._collections",
        "importlib.metadata._functools",
        "importlib.metadata._itertools",
        "importlib.metadata._meta",
        "importlib.metadata._text",
        "importlib.metadata.diagnose",
        "importlib.readers",
        "importlib.resources._adapters",
        "importlib.resources._common",
        "importlib.resources._functional",
        "importlib.resources._itertools",
        "importlib.resources._legacy",
        "importlib.resources.abc",
        "importlib.resources.readers",
        "importlib.resources.simple",
        "importlib.simple",
        "json.__main__",
        "pathlib._abc",
        "pathlib._local",
        "pathlib._os",
        "pathlib.types",
        "pydoc_data.module_docs",
        "re._casefix",
        "re._compiler",
        "re._constants",
        "re._parser",
        "sqlite3.__main__",
        "string.templatelib",
        "sysconfig.__main__",
        "tkinter.tix",
        "wsgiref.types",
        "zipfile.__main__",
        "zipfile._path",
        "zipfile._path.glob",
    }
)
INCOMPATIBLE_SUBMODULES_PY310 = frozenset(
    {
        "asyncio.graph",
        "asyncio.taskgroups",
        "asyncio.timeouts",
        "asyncio.tools",
        "concurrent.futures.interpreter",
        "concurrent.interpreters",
        "concurrent.interpreters._crossinterp",
        "concurrent.interpreters._queues",
        "ctypes._layout",
        "dbm.sqlite3",
        "encodings._win_cp_codecs",
        "ensurepip._bundled",
        "importlib._adapters",
        "importlib._common",
        "importlib.metadata.diagnose",
        "importlib.resources._adapters",
        "importlib.resources._common",
        "importlib.resources._functional",
        "importlib.resources._itertools",
        "importlib.resources._legacy",
        "importlib.resources.abc",
        "importlib.resources.readers",
        "importlib.resources.simple",
        "importlib.simple",
        "json.__main__",
        "pathlib._abc",
        "pathlib._local",
        "pathlib._os",
        "pathlib.types",
        "pydoc_data.module_docs",
        "re._casefix",
        "re._compiler",
        "re._constants",
        "re._parser",
        "sqlite3.__main__",
        "string.templatelib",
        "sysconfig.__main__",
        "tkinter.tix",
        "wsgiref.types",
        "zipfile.__main__",
        "zipfile._path",
        "zipfile._path.glob",
    }
)
INCOMPATIBLE_SUBMODULES_CURRENT = frozenset(
    {
        "ensurepip._bundled",
        "importlib._adapters",
        "importlib._common",
        "importlib.resources._legacy",
        "pathlib._abc",
        "tkinter.tix",
    }
)


def script_import_findings(root: Path) -> list[str]:
    """Report imports outside the stdlib or a script's own sibling modules."""
    paths = sorted(root.glob("scripts/*.py")) + sorted(
        path
        for path in root.glob(".agents/skills/*/scripts/**/*.py")
        if "tests" not in path.relative_to(root / ".agents/skills").parts[2:]
    )
    findings: list[str] = []
    for path in paths:
        siblings = {sibling.stem for sibling in path.parent.glob("*.py")}
        relative = path.relative_to(root)
        if relative.parts[0] == ".agents":
            stdlib = STDLIB_PY39 & sys.stdlib_module_names
            incompatible = INCOMPATIBLE_SUBMODULES_PY39
        elif relative == Path("scripts/check_staged.py"):
            stdlib = STDLIB_PY310 & sys.stdlib_module_names
            incompatible = INCOMPATIBLE_SUBMODULES_PY310
        else:
            stdlib = sys.stdlib_module_names
            incompatible = INCOMPATIBLE_SUBMODULES_CURRENT
        allowed = (stdlib - HOST_SPECIFIC_MODULES) | {"__future__"} | siblings
        unavailable = BUILD_OPTIONAL_MODULES | incompatible
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    findings.append(
                        f"{path.relative_to(root)}:{node.lineno}: relative import"
                    )
                    continue
                modules = [node.module] if node.module else []
                # A from-import can name either a member or an optional module.
                modules.extend(
                    f"{node.module}.{alias.name}"
                    for alias in node.names
                    if node.module not in unavailable
                    and f"{node.module}.{alias.name}" in unavailable
                )
            else:
                continue
            findings.extend(
                f"{path.relative_to(root)}:{node.lineno}: {module}"
                for module in modules
                if module.split(".")[0] not in allowed
                or any(
                    module == optional or module.startswith(optional + ".")
                    for optional in unavailable
                )
            )
    return findings


def test_script_imports_repository_uses_only_stdlib_and_siblings() -> None:
    assert script_import_findings(REPO_ROOT) == []


@pytest.mark.parametrize("directory", ["scripts", ".agents/skills/sample/scripts"])
@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import yaml", id="import"),
        pytest.param("from yaml import safe_load", id="from-import"),
        pytest.param("def main():\n    import yaml", id="function-import"),
        pytest.param("if False:\n    import yaml", id="conditional-import"),
        pytest.param("from ..sibling import run", id="relative-escape"),
        pytest.param("from .sibling import run", id="relative-sibling"),
        pytest.param("from . import sibling", id="relative-module"),
    ],
)
def test_script_imports_third_party_or_relative_escape_is_rejected(
    tmp_path: Path, directory: str, source: str
) -> None:
    scripts = tmp_path / directory
    scripts.mkdir(parents=True)
    (scripts / "sibling.py").write_text("", encoding="utf-8")
    (scripts / "probe.py").write_text(source, encoding="utf-8")
    assert len(script_import_findings(tmp_path)) == 1


@pytest.mark.parametrize("directory", ["scripts", ".agents/skills/sample/scripts"])
def test_script_imports_stdlib_and_siblings_are_allowed(
    tmp_path: Path, directory: str
) -> None:
    scripts = tmp_path / directory
    scripts.mkdir(parents=True)
    (scripts / "sibling.py").write_text("", encoding="utf-8")
    (scripts / "probe.py").write_text(
        "from __future__ import annotations\nimport json\n"
        "from pathlib import Path\nimport sibling\nfrom sibling import run\n",
        encoding="utf-8",
    )
    assert script_import_findings(tmp_path) == []


def test_script_imports_skill_test_dependencies_are_excluded(tmp_path: Path) -> None:
    tests = tmp_path / ".agents/skills/sample/scripts/tests"
    tests.mkdir(parents=True)
    (tests / "test_probe.py").write_text("import yaml", encoding="utf-8")
    assert script_import_findings(tmp_path) == []


@pytest.mark.parametrize(
    "script", ["scripts/check_staged.py", ".agents/skills/sample/scripts/probe.py"]
)
@pytest.mark.parametrize(
    "module", ["tomllib", "annotationlib", "compression", "_typing"]
)
def test_script_imports_newer_stdlib_is_rejected(
    tmp_path: Path, script: str, module: str
) -> None:
    path = tmp_path / script
    path.parent.mkdir(parents=True)
    path.write_text(f"def main():\n    import {module}\n", encoding="utf-8")
    assert len(script_import_findings(tmp_path)) == 1


@pytest.mark.parametrize(
    "script", ["scripts/check_staged.py", ".agents/skills/sample/scripts/probe.py"]
)
@pytest.mark.parametrize("module", ["formatter", "parser", "cgi"])
def test_script_imports_removed_stdlib_is_rejected(
    tmp_path: Path, script: str, module: str
) -> None:
    path = tmp_path / script
    path.parent.mkdir(parents=True)
    path.write_text(f"import {module}\n", encoding="utf-8")
    assert len(script_import_findings(tmp_path)) == 1


def test_script_imports_project_scripts_allow_current_stdlib(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "probe.py").write_text("import tomllib\n", encoding="utf-8")
    assert script_import_findings(tmp_path) == []


@pytest.mark.parametrize(
    "script", ["scripts/check_staged.py", ".agents/skills/sample/scripts/probe.py"]
)
def test_script_imports_shared_older_stdlib_is_allowed(
    tmp_path: Path, script: str
) -> None:
    path = tmp_path / script
    path.parent.mkdir(parents=True)
    path.write_text(
        "import json, pathlib, graphlib, zoneinfo, _ast\n", encoding="utf-8"
    )
    assert script_import_findings(tmp_path) == []


@pytest.mark.parametrize(
    "script",
    [
        "scripts/probe.py",
        "scripts/check_staged.py",
        ".agents/skills/sample/scripts/probe.py",
    ],
)
@pytest.mark.parametrize(
    "module",
    [
        "winreg",
        "msvcrt",
        "winsound",
        "_winapi",
        "_overlapped",
        "_msi",
        "nt",
        "_scproxy",
    ],
)
@pytest.mark.parametrize(
    "form",
    [
        "import {module}",
        "from {module} import value",
        "def main():\n    import {module}",
    ],
)
def test_script_imports_host_specific_modules_are_rejected(
    tmp_path: Path, script: str, module: str, form: str
) -> None:
    path = tmp_path / script
    path.parent.mkdir(parents=True)
    path.write_text(form.format(module=module), encoding="utf-8")
    assert len(script_import_findings(tmp_path)) == 1


@pytest.mark.parametrize(
    "script",
    [
        "scripts/probe.py",
        "scripts/check_staged.py",
        ".agents/skills/sample/scripts/probe.py",
    ],
)
@pytest.mark.parametrize(
    "module",
    [
        "_gdbm",
        "_dbm",
        "dbm.gnu",
        "dbm.ndbm",
        "dbm.sqlite3",
        "bz2",
        "_bz2",
        "lzma",
        "_lzma",
        "_zstd",
        "compression.zstd",
        "ctypes",
        "_ctypes",
        "curses",
        "_curses",
        "_curses_panel",
        "readline",
        "rlcompleter",
        "sqlite3",
        "_sqlite3",
        "ssl",
        "_ssl",
        "_hashlib",
        "tkinter",
        "_tkinter",
        "idlelib",
        "turtle",
        "turtledemo",
        "_uuid",
        "zlib",
        "gzip",
        "compression.bz2",
        "compression.gzip",
        "compression.lzma",
        "compression.zlib",
        "multiprocessing.sharedctypes",
    ],
)
@pytest.mark.parametrize(
    "form",
    [
        "import {module}",
        "from {module} import value",
        "def main():\n    import {module}",
    ],
)
def test_script_imports_external_build_modules_are_rejected(
    tmp_path: Path, script: str, module: str, form: str
) -> None:
    path = tmp_path / script
    path.parent.mkdir(parents=True)
    path.write_text(form.format(module=module), encoding="utf-8")
    assert len(script_import_findings(tmp_path)) == 1


@pytest.mark.parametrize(
    "source",
    ["from dbm import gnu", "from dbm import ndbm", "from compression import zstd"],
)
def test_script_imports_optional_submodule_from_parent_is_rejected(
    tmp_path: Path, source: str
) -> None:
    path = tmp_path / "scripts/probe.py"
    path.parent.mkdir()
    path.write_text(source, encoding="utf-8")
    assert len(script_import_findings(tmp_path)) == 1


def test_script_imports_modules_with_bundled_fallbacks_are_allowed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "scripts/probe.py"
    path.parent.mkdir()
    path.write_text(
        "import hashlib, decimal, uuid\nimport dbm.dumb\n", encoding="utf-8"
    )
    assert script_import_findings(tmp_path) == []


@pytest.mark.parametrize(
    "script", ["scripts/check_staged.py", ".agents/skills/sample/scripts/probe.py"]
)
@pytest.mark.parametrize(
    "source",
    [
        "import concurrent.interpreters",
        "from concurrent import interpreters",
        "def main():\n    import concurrent.interpreters",
        "def main():\n    from concurrent import interpreters",
        "import concurrent.futures.interpreter",
        "from concurrent.futures import interpreter",
        "import asyncio.taskgroups",
        "from asyncio import taskgroups",
        "import importlib.resources.abc",
        "from importlib.resources import abc",
        "import string.templatelib",
        "from string import templatelib",
        "import importlib._adapters",
        "from importlib import _adapters",
    ],
)
def test_script_imports_incompatible_submodules_are_rejected(
    tmp_path: Path, script: str, source: str
) -> None:
    path = tmp_path / script
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert len(script_import_findings(tmp_path)) == 1


@pytest.mark.parametrize(
    "script",
    [
        "scripts/probe.py",
        "scripts/check_staged.py",
        ".agents/skills/sample/scripts/probe.py",
    ],
)
def test_script_imports_shared_submodules_and_members_are_allowed(
    tmp_path: Path, script: str
) -> None:
    path = tmp_path / script
    path.parent.mkdir(parents=True)
    path.write_text(
        "import concurrent.futures, os.path, collections.abc\n"
        "from concurrent import futures\nfrom datetime import datetime\n"
        "from importlib.resources import files\n",
        encoding="utf-8",
    )
    assert script_import_findings(tmp_path) == []


def test_script_imports_project_allows_current_submodules(tmp_path: Path) -> None:
    path = tmp_path / "scripts/probe.py"
    path.parent.mkdir()
    path.write_text(
        "import concurrent.interpreters\nfrom concurrent import interpreters\n"
        "import asyncio.taskgroups\nfrom string import templatelib\n",
        encoding="utf-8",
    )
    assert script_import_findings(tmp_path) == []
