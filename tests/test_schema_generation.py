"""Tests for deterministic checked-in JSON Schemas."""

from pathlib import Path

from side_effects_lab.schema_generation import (
    SCHEMA_MODELS,
    SCHEMA_ROOT,
    expected_schemas,
    schema_drift,
    write_schemas,
)


def test_checked_in_schemas_match_models() -> None:
    assert schema_drift() == []


def test_schema_generation_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_schemas(first)
    write_schemas(second)

    expected_names = set(SCHEMA_MODELS)
    assert {path.name for path in first.glob("*.json")} == expected_names
    assert {path.name for path in second.glob("*.json")} == expected_names
    for name, expected in expected_schemas().items():
        assert (first / name).read_bytes() == expected
        assert (second / name).read_bytes() == expected
        assert (SCHEMA_ROOT / name).read_bytes() == expected
