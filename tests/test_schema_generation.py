"""Tests for deterministic checked-in JSON Schemas."""

from hashlib import sha256
from json import loads
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from side_effects_lab.canonical import canonical_json_bytes
from side_effects_lab.models import FaultSpec
from side_effects_lab.schema_generation import (
    SCHEMA_DIGEST_MANIFEST,
    SCHEMA_MODELS,
    SCHEMA_ROOT,
    expected_schema_digest_manifest,
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
    expected_manifest = expected_schema_digest_manifest()
    assert (first / SCHEMA_DIGEST_MANIFEST).read_bytes() == expected_manifest
    assert (second / SCHEMA_DIGEST_MANIFEST).read_bytes() == expected_manifest
    assert (SCHEMA_ROOT / SCHEMA_DIGEST_MANIFEST).read_bytes() == expected_manifest


def test_schema_digest_manifest_pins_every_schema() -> None:
    manifest = expected_schema_digest_manifest().decode("ascii").splitlines()
    assert len(manifest) == len(SCHEMA_MODELS)
    entries = [line.split("  ", 1) for line in manifest]
    assert [name for _, name in entries] == sorted(SCHEMA_MODELS)
    for digest, name in entries:
        assert digest == sha256(expected_schemas()[name]).hexdigest()
    assert (SCHEMA_ROOT / SCHEMA_DIGEST_MANIFEST).read_bytes() == (
        expected_schema_digest_manifest()
    )


def test_schema_drift_reports_missing_digest_manifest(tmp_path: Path) -> None:
    write_schemas(tmp_path)
    (tmp_path / SCHEMA_DIGEST_MANIFEST).unlink()
    assert schema_drift(tmp_path) == [
        f"missing schema digest manifest: {SCHEMA_DIGEST_MANIFEST}"
    ]


def test_schema_drift_reports_changed_digest_manifest(tmp_path: Path) -> None:
    write_schemas(tmp_path)
    (tmp_path / SCHEMA_DIGEST_MANIFEST).write_text("tampered\n", encoding="ascii")
    assert schema_drift(tmp_path) == [
        f"changed schema digest manifest: {SCHEMA_DIGEST_MANIFEST}"
    ]


def test_fault_trigger_schema_requires_exactly_one_selector() -> None:
    document = cast(
        dict[str, object],
        loads(expected_schemas()["fault-spec.schema.json"]),
    )
    definitions = cast(dict[str, object], document["$defs"])
    trigger = cast(dict[str, object], definitions["FaultTrigger"])

    assert trigger["oneOf"] == [
        {
            "properties": {
                "call_ordinal": {"not": {"type": "null"}},
                "event_kind": {"type": "null"},
            },
            "required": ["call_ordinal"],
        },
        {
            "properties": {
                "call_ordinal": {"type": "null"},
                "event_kind": {"not": {"type": "null"}},
            },
            "required": ["event_kind"],
        },
    ]


def _fault_payload(trigger: dict[str, object]) -> dict[str, object]:
    return {
        "fault_id": "fault-schema-xor",
        "trigger": {
            "service": "dummy_github",
            "operation": "create_issue",
            **trigger,
        },
        "commit_position": "after_commit_before_response",
        "state_effect": "commit",
        "response_effect": "drop",
        "visibility_schedule": [{"tick": 2, "visible_revision": 1}],
        "required": True,
        "seed": 17,
    }


def test_fault_schema_and_model_agree_on_selector_values() -> None:
    document = loads(expected_schemas()["fault-spec.schema.json"])
    Draft202012Validator.check_schema(document)
    validator = Draft202012Validator(document)

    valid_triggers: list[dict[str, object]] = [
        {"call_ordinal": 1, "event_kind": None},
        {"call_ordinal": None, "event_kind": "attempt_dispatched"},
    ]
    for trigger in valid_triggers:
        model = FaultSpec.model_validate_json(
            canonical_json_bytes(_fault_payload(trigger))
        )
        validator.validate(model.model_dump(mode="json"))

    invalid_triggers: list[dict[str, object]] = [
        {},
        {"call_ordinal": None},
        {"event_kind": None},
        {"call_ordinal": None, "event_kind": None},
        {"call_ordinal": 1, "event_kind": "attempt_dispatched"},
    ]
    for trigger in invalid_triggers:
        with pytest.raises(JsonSchemaValidationError):
            validator.validate(_fault_payload(trigger))
        with pytest.raises(PydanticValidationError, match="exactly one"):
            FaultSpec.model_validate_json(canonical_json_bytes(_fault_payload(trigger)))
