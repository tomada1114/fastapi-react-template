"""One settings-environment boundary for the test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import AliasChoices, AliasPath

from my_app.settings import ENV_PREFIX, Settings

if TYPE_CHECKING:
    from collections.abc import Mapping


def without_settings_env(environment: Mapping[str, str]) -> dict[str, str]:
    """Keep unrelated process variables while removing every settings input."""
    aliases: set[str] = set()
    for field in Settings.model_fields.values():
        alias = field.validation_alias or field.alias
        if isinstance(alias, str):
            aliases.add(alias.casefold())
        elif isinstance(alias, (AliasChoices, AliasPath)):
            paths = (
                alias.convert_to_aliases()
                if isinstance(alias, AliasChoices)
                else [alias.convert_to_aliases()]
            )
            aliases.update(
                path[0].casefold() for path in paths if isinstance(path[0], str)
            )
    return {
        name: value
        for name, value in environment.items()
        if not name.casefold().startswith(ENV_PREFIX.casefold())
        and name.casefold() not in aliases
    }
