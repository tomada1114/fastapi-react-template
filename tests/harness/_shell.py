"""Comment splitting for shell commands and justfile values, not YAML parsing."""

from __future__ import annotations


def split_comment(value: str) -> tuple[str, str | None]:
    """Keep hashes inside quoted shell values while removing trailing comments."""
    quote: str | None = None
    for index, char in enumerate(value):
        if quote is not None:
            quote = None if char == quote else quote
        elif char in {'"', "'"} and (index == 0 or value[index - 1].isspace()):
            quote = char
        elif char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip(), value[index:]
    return value.strip(), None
