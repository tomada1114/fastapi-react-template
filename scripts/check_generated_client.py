"""Check generated-client drift and the approved TypeScript exception scope.

Usage: uv run --locked python scripts/check_generated_client.py [--scope-only]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED = Path("frontend/src/api/generated")
RUNTIME_PREFIXES = (GENERATED / "client", GENERATED / "core")
DIRECTIVE = re.compile(
    r"(?m)^[\s\ufeff]*(?://+|/\*+|\*)\s*(@ts-(?:nocheck|ignore|expect-error))\b",
    re.IGNORECASE,
)
TS_SUFFIXES = {".ts", ".tsx", ".mts", ".cts"}


class ContractCheckError(RuntimeError):
    """A failed generator or unsafe output cannot establish contract freshness."""


def _scope_findings(tree: Path, prefix: Path) -> list[str]:
    findings = []
    for directory, subdirectories, filenames in os.walk(tree):
        # Installed dependencies and build/coverage artifacts are not source.
        if Path(directory) == tree and prefix == Path("frontend"):
            subdirectories[:] = [
                name
                for name in subdirectories
                if name not in {"node_modules", "dist", "coverage"}
            ]
        for name in sorted(filenames):
            path = Path(directory) / name
            if path.suffix not in TS_SUFFIXES:
                continue
            display = prefix / path.relative_to(tree)
            runtime = any(display.is_relative_to(item) for item in RUNTIME_PREFIXES)
            for match in DIRECTIVE.finditer(path.read_text(encoding="utf-8")):
                directive = match.group(1).lower()
                if runtime and directive == "@ts-nocheck":
                    continue
                findings.append(f"{display}: {directive} is not an approved exception")
    return sorted(findings)


def _check_scope(tree: Path, prefix: Path) -> None:
    findings = _scope_findings(tree, prefix)
    if findings:
        raise ContractCheckError("\n".join(findings))


def _check_generated(root: Path) -> None:
    pnpm = shutil.which("pnpm")
    diff = shutil.which("diff")
    if pnpm is None or diff is None:
        msg = "pnpm and diff must be installed before checking generated files"
        raise ContractCheckError(msg)
    with TemporaryDirectory(prefix="api-contract-") as temporary:
        output = Path(temporary)
        generated = subprocess.run(  # noqa: S603 -- fixed local generator argv, no shell.
            [pnpm, "--dir", "frontend", "run", "api:generate"],
            cwd=root,
            env={**os.environ, "OPENAPI_TS_OUTPUT": str(output)},
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        if generated.returncode:
            msg = f"generator exited {generated.returncode}\n{generated.stdout}{generated.stderr}"
            raise ContractCheckError(msg)
        # Verify the actual newly generated tree as well as the checkout: a
        # changed generator must not silently widen the approved header scope.
        _check_scope(output, GENERATED)
        difference = subprocess.run(  # noqa: S603 -- fixed recursive diff argv, no shell.
            [diff, "-r", str(root / GENERATED), str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        if difference.returncode:
            raise ContractCheckError(difference.stdout + difference.stderr)


def main(argv: Sequence[str] | None = None, *, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        _check_scope(root / "frontend", Path("frontend"))
        if not args.scope_only:
            _check_generated(root)
    except (
        ContractCheckError,
        OSError,
        UnicodeError,
        subprocess.TimeoutExpired,
    ) as error:
        sys.stderr.write(
            f"ERR_CONTRACT_CHECK: {error}\n"
            "Expected: current generated files and runtime-only TypeScript exceptions.\n"
            "Next: remove unapproved directives and run `just contract`; "
            "run `just install` if generator dependencies are missing.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
