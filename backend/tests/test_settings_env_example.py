from __future__ import annotations

from pydantic import AliasChoices, AliasPath

from my_app.settings import ENV_FILE, ENV_PREFIX, Settings
from tests.settings_env import settings_from_env_file

EXAMPLE = ENV_FILE.with_name(".env.example")


def _environment_names() -> set[str]:
    """Derive input names using the same aliases as settings_env's isolation."""
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias or field.alias
        if isinstance(alias, str):
            names.add(alias.upper())
        elif isinstance(alias, (AliasChoices, AliasPath)):
            paths = (
                alias.convert_to_aliases()
                if isinstance(alias, AliasChoices)
                else [alias.convert_to_aliases()]
            )
            names.update(path[0].upper() for path in paths if isinstance(path[0], str))
        else:
            names.add(f"{ENV_PREFIX}{name.upper()}")
    return names


def test_settings_env_example_lists_exactly_every_setting_with_empty_values():
    assignments = [
        line.split("=", 1)
        for line in EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert {name for name, _ in assignments} == _environment_names()
    assert len(assignments) == len(_environment_names())
    assert all(
        name.startswith(ENV_PREFIX) and value == "" for name, value in assignments
    )


def test_settings_env_example_loads_all_defaults():
    assert EXAMPLE.is_file()
    assert (
        settings_from_env_file(EXAMPLE).model_dump()
        == settings_from_env_file(None).model_dump()
    )
