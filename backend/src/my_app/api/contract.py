"""Export the API contract without starting the server or reading runtime inputs.

Usage: python -m my_app.api.contract --output PATH [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from my_app.api.app import create_app
from my_app.composition import build_container
from my_app.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Write or check the committed contract independently of runtime settings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    # Explicit values override environment sources, and dotenv is disabled.
    # The Pydantic mypy plugin omits BaseSettings' supported _env_file argument.
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=None,
        cors_origins=[],
        log_level="INFO",
        log_format="text",
    )
    # A supplied, resource-free memory container avoids the factory's logging
    # configuration. Neither construction nor openapi() enters lifespan.
    app = create_app(settings, container=build_container(settings))
    document = (
        json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    output: Path = args.output
    try:
        if args.check:
            if output.read_bytes() != document.encode("utf-8"):
                sys.stderr.write(f"{output} is stale; run `just contract`\n")
                return 1
        else:
            output.write_text(document, encoding="utf-8", newline="\n")
    except OSError as error:
        sys.stderr.write(f"{output}: {error}; run `just contract`\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
