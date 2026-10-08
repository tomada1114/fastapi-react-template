"""The shared YAML boundary preserves Actions keys and rejects unreadable data."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from tests.harness import _yaml


def test_load_yaml_actions_words_preserve_strings(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("on: [yes, no, on, off, true, FALSE]\n", encoding="utf-8")

    assert _yaml.load_yaml(path) == {"on": ["yes", "no", "on", "off", True, False]}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-08", "2026-10-08"),
        ("2026-10-08T12:34:56Z", "2026-10-08T12:34:56Z"),
        ("12:34", "12:34"),
        ("010", 10),
        ("-010", -10),
        ("0o10", 8),
        ("0x10", 16),
        ("0b10", "0b10"),
        ("1_000", "1_000"),
        ("1e3", 1000.0),
        (".5", 0.5),
    ],
)
def test_load_yaml_core_scalars_match_actions(
    tmp_path: Path, text: str, expected: object
) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(f"value: {text}\n", encoding="utf-8")

    assert _yaml.load_yaml(path) == {"value": expected}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param("jobs: {a: {}, a: {}}\n", "duplicate key 'a'", id="duplicate"),
        pytest.param("jobs: [\n", "workflow.yml", id="syntax"),
        pytest.param("!!python/object:builtins.object {}", "workflow.yml", id="unsafe"),
    ],
)
def test_load_yaml_invalid_document_fails_closed(
    tmp_path: Path, text: str, message: str
) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(_yaml.UnreadableYamlError, match=message):
        _yaml.load_yaml(path)


@pytest.mark.parametrize(
    ("helper", "value", "expected"),
    [
        pytest.param("as_mapping", ["job"], "mapping", id="mapping"),
        pytest.param("as_mapping", {True: "job"}, "mapping", id="mapping-keys"),
        pytest.param("as_sequence", "job", "sequence", id="sequence"),
        pytest.param("as_str", False, "string", id="string"),
    ],
)
def test_yaml_narrowing_wrong_shape_names_location(
    helper: str, value: object, expected: str
) -> None:
    with pytest.raises(
        _yaml.UnreadableYamlError,
        match=rf"workflow.yml: jobs.build: expected {expected}",
    ):
        getattr(_yaml, helper)(value, "workflow.yml: jobs.build")


def test_yaml_narrowing_valid_shapes_return_values() -> None:
    assert _yaml.as_mapping({"job": ["a"]}, "jobs") == {"job": ["a"]}
    assert _yaml.as_sequence(["a", 2], "matrix") == ["a", 2]
    assert _yaml.as_str("a", "name") == "a"


def test_load_yaml_merge_override_preserves_explicit_value(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "defaults: &defaults {timeout: 10, enabled: true}\njob: {<<: *defaults, timeout: 20}\n",
        encoding="utf-8",
    )
    assert _yaml.load_yaml(path) == {
        "defaults": {"timeout": 10, "enabled": True},
        "job": {"timeout": 20, "enabled": True},
    }


@pytest.mark.parametrize("comment", ["", " # v5"])
def test_load_yaml_scalar_alias_comment_belongs_to_occurrence(
    tmp_path: Path, comment: str
) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        f"name: &pin owner/action@{'a' * 40} # v4\nuses: *pin{comment}\n",
        encoding="utf-8",
    )
    document = _yaml.as_mapping(_yaml.load_yaml(path), str(path))

    assert document["name"] == document["uses"]
    assert _yaml.source_comment(document["name"]) == "# v4"
    assert _yaml.source_comment(document["uses"]) == (comment.strip() or None)
