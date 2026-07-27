"""Event primitive boundaries: sequence, tick, kind, and optional identities.

Traceability: Architecture execution model and artifact schema; the base event
validates one record but not cross-record contiguity (that is T006's ledger
concern). Covers the T002B matrix "Event primitive" row.
"""

from collections.abc import Callable
from json import dumps, loads

import pytest
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from side_effects_lab.models import EventKind, LabEvent


def _event_json(**overrides: object) -> str:
    payload: dict[str, object] = {
        "seq": 1,
        "tick": 0,
        "kind": "attempt_dispatched",
        "action_id": "action-create-issue",
        "attempt_id": "attempt-1",
        "operation_key": "op-sel001",
        "authority_id": "auth-create-issue",
        "evidence": {"note": "dispatched"},
    }
    payload.update(overrides)
    return dumps(payload)


def test_valid_event_round_trips(fixture_text: Callable[[str], str]) -> None:
    event = LabEvent.model_validate_json(fixture_text("valid_event.json"))
    assert event.seq == 1
    assert event.tick == 0
    assert event.kind is EventKind.ATTEMPT_DISPATCHED
    assert LabEvent.model_validate_json(event.model_dump_json()) == event


def test_minimal_event_defaults_optional_identities_to_none() -> None:
    event = LabEvent.model_validate_json(
        dumps({"seq": 1, "tick": 0, "kind": "read_observed", "evidence": {}})
    )
    assert event.action_id is None
    assert event.attempt_id is None
    assert event.fault_id is None


@pytest.mark.parametrize("seq", [0, -1, -100])
def test_non_positive_sequence_is_rejected(
    seq: int, assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        LabEvent.model_validate_json(_event_json(seq=seq))
    assert_error(exc_info, ("seq",), "greater_than")


@pytest.mark.parametrize("seq", [1.0, 1.5, "1", True])
def test_non_integer_sequence_is_rejected(
    seq: object, assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        LabEvent.model_validate_json(_event_json(seq=seq))
    assert_error(exc_info, ("seq",), "int_type")


def test_float_tick_is_rejected(assert_error: Callable[..., ErrorDetails]) -> None:
    with pytest.raises(ValidationError) as exc_info:
        LabEvent.model_validate_json(_event_json(tick=1.5))
    assert_error(exc_info, ("tick",), "int_type")


def test_negative_tick_is_rejected(assert_error: Callable[..., ErrorDetails]) -> None:
    with pytest.raises(ValidationError) as exc_info:
        LabEvent.model_validate_json(_event_json(tick=-1))
    assert_error(exc_info, ("tick",), "greater_than_equal")


def test_unknown_kind_is_rejected(assert_error: Callable[..., ErrorDetails]) -> None:
    with pytest.raises(ValidationError) as exc_info:
        LabEvent.model_validate_json(_event_json(kind="teleported"))
    assert_error(exc_info, ("kind",), "enum")


def test_extra_field_is_rejected(assert_error: Callable[..., ErrorDetails]) -> None:
    data = loads(_event_json())
    data["surprise"] = 1
    with pytest.raises(ValidationError) as exc_info:
        LabEvent.model_validate(data)
    assert_error(exc_info, ("surprise",), "extra_forbidden")


def test_wrong_identity_prefix_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        LabEvent.model_validate_json(_event_json(operation_key="sel001"))
    assert_error(exc_info, ("operation_key",), "string_pattern_mismatch")


def test_bad_digest_intent_field_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        LabEvent.model_validate_json(_event_json(intent_digest="sha256:nope"))
    assert_error(exc_info, ("intent_digest",), "string_pattern_mismatch")


def test_bad_event_fixture_pins_non_positive_sequence(
    fixture_text: Callable[[str], str], assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        LabEvent.model_validate_json(fixture_text("bad_event.json"))
    assert_error(exc_info, ("seq",), "greater_than")
