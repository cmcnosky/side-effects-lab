"""Supported vs unsupported schema, protocol, and semantic versions.

Traceability: Architecture "Frozen base-contract conventions" (two-part schema
and protocol versions; three-part semantic scenario/subject versions) and the
T002B matrix "Schema versions" row. T002A exposes these as constrained types,
not yet as artifact fields, so they are validated through ``TypeAdapter``.
"""

from collections.abc import Callable

import pytest
from pydantic import TypeAdapter, ValidationError

from side_effects_lab.models import (
    CURRENT_PROTOCOL_VERSION,
    CURRENT_SCHEMA_VERSION,
    ProtocolVersion,
    SchemaVersion,
    SemanticVersion,
)

_SCHEMA: TypeAdapter[str] = TypeAdapter(SchemaVersion)
_PROTOCOL: TypeAdapter[str] = TypeAdapter(ProtocolVersion)
_SEMANTIC: TypeAdapter[str] = TypeAdapter(SemanticVersion)


def test_current_constants_are_the_supported_literal() -> None:
    assert CURRENT_SCHEMA_VERSION == "0.1"
    assert CURRENT_PROTOCOL_VERSION == "0.1"
    assert _SCHEMA.validate_python(CURRENT_SCHEMA_VERSION) == "0.1"
    assert _PROTOCOL.validate_python(CURRENT_PROTOCOL_VERSION) == "0.1"


@pytest.mark.parametrize("adapter", [_SCHEMA, _PROTOCOL])
@pytest.mark.parametrize(
    "value",
    ["0.2", "1.0", "0.10", "0.1.0", "00.1", "0.1 ", " 0.1", "", "latest"],
)
def test_two_part_versions_reject_unsupported(
    adapter: TypeAdapter[str], value: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        adapter.validate_python(value)
    assert exc_info.value.errors()[0]["type"] == "literal_error"


@pytest.mark.parametrize("adapter", [_SCHEMA, _PROTOCOL])
@pytest.mark.parametrize("value", [1, 0.1, None, True, ["0.1"]])
def test_two_part_versions_reject_non_string(
    adapter: TypeAdapter[str], value: object
) -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python(value)


@pytest.mark.parametrize(
    "value",
    ["0.0.0", "1.2.3", "10.20.30", "1.0.0-rc.1", "1.0.0+build.5", "1.2.3-a.1+b.2"],
)
def test_semantic_version_accepts_three_part_forms(value: str) -> None:
    assert _SEMANTIC.validate_python(value) == value


@pytest.mark.parametrize(
    "value",
    ["1.2", "1.2.3.4", "01.2.3", "1.02.3", "v1.2.3", "1.2.3-", "", " 1.2.3", "1.2.x"],
)
def test_semantic_version_rejects_malformed(value: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _SEMANTIC.validate_python(value)
    assert exc_info.value.errors()[0]["type"] == "string_pattern_mismatch"


def test_semantic_version_enforces_length_bound() -> None:
    over_long = "1.0.0-" + "a" * 96
    with pytest.raises(ValidationError) as exc_info:
        _SEMANTIC.validate_python(over_long)
    assert exc_info.value.errors()[0]["type"] in {
        "string_too_long",
        "string_pattern_mismatch",
    }


def test_bad_version_fixture_is_rejected(
    fixture_json: Callable[[str], object],
) -> None:
    payload = fixture_json("bad_version.json")
    assert isinstance(payload, dict)
    with pytest.raises(ValidationError) as schema_exc:
        _SCHEMA.validate_python(payload["schema_version"])
    assert schema_exc.value.errors()[0]["type"] == "literal_error"
    with pytest.raises(ValidationError) as protocol_exc:
        _PROTOCOL.validate_python(payload["protocol_version"])
    assert protocol_exc.value.errors()[0]["type"] == "literal_error"
    with pytest.raises(ValidationError) as semantic_exc:
        _SEMANTIC.validate_python(payload["subject_version"])
    assert semantic_exc.value.errors()[0]["type"] == "string_pattern_mismatch"
