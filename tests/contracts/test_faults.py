"""Fault contract: selectors, effects, visibility ticks, and typed seed.

Traceability: Architecture "Frozen base-contract conventions" (trigger XOR of
positive call ordinal or preceding event kind; unique increasing integer
visibility ticks; tick ordering is a model-level rule) and the T002B matrix
"Fault contract" row. Negatives are driven through JSON so enum coercion mirrors
the artifact-loading path.
"""

from collections.abc import Callable
from json import dumps, loads

import pytest
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from side_effects_lab.models import (
    CommitPosition,
    FaultSpec,
    FaultTrigger,
    ResponseEffect,
    StateEffect,
    VisibilityStep,
)


def _fault_json(**overrides: object) -> str:
    payload: dict[str, object] = {
        "fault_id": "fault-vanished-receipt",
        "trigger": {
            "service": "dummy_github",
            "operation": "create_issue",
            "call_ordinal": 1,
        },
        "commit_position": "after_commit_before_response",
        "state_effect": "commit",
        "response_effect": "drop",
        "visibility_schedule": [{"tick": 1, "visible_revision": 0}],
        "required": True,
        "seed": 17,
    }
    payload.update(overrides)
    return dumps(payload)


def test_valid_fault_round_trips() -> None:
    fault = FaultSpec.model_validate_json(_fault_json())
    assert fault.commit_position is CommitPosition.AFTER_COMMIT_BEFORE_RESPONSE
    assert fault.state_effect is StateEffect.COMMIT
    assert fault.response_effect is ResponseEffect.DROP
    assert FaultSpec.model_validate_json(fault.model_dump_json()) == fault


def test_event_kind_selector_form_round_trips() -> None:
    fault = FaultSpec.model_validate_json(
        _fault_json(
            trigger={
                "service": "dummy_github",
                "operation": "create_issue",
                "event_kind": "attempt_dispatched",
            }
        )
    )
    assert fault.trigger.event_kind is not None
    assert fault.trigger.call_ordinal is None


def test_neither_selector_is_rejected_at_trigger(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(
            _fault_json(
                trigger={"service": "dummy_github", "operation": "create_issue"}
            )
        )
    error = assert_error(exc_info, ("trigger",), "value_error")
    assert "exactly one" in error["msg"]


def test_both_selectors_are_rejected_at_trigger(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(
            _fault_json(
                trigger={
                    "service": "dummy_github",
                    "operation": "create_issue",
                    "call_ordinal": 1,
                    "event_kind": "attempt_dispatched",
                }
            )
        )
    assert_error(exc_info, ("trigger",), "value_error")


def test_null_selectors_are_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(
            _fault_json(
                trigger={
                    "service": "dummy_github",
                    "operation": "create_issue",
                    "call_ordinal": None,
                    "event_kind": None,
                }
            )
        )
    assert exc_info.value.errors()[0]["loc"][0] == "trigger"


def test_zero_call_ordinal_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(
            _fault_json(
                trigger={
                    "service": "dummy_github",
                    "operation": "create_issue",
                    "call_ordinal": 0,
                }
            )
        )
    assert_error(exc_info, ("trigger", "call_ordinal"), "greater_than")


@pytest.mark.parametrize(
    "field,value,loc",
    [
        ("commit_position", "whenever", ("commit_position",)),
        ("state_effect", "explode", ("state_effect",)),
        ("response_effect", "vanish", ("response_effect",)),
    ],
)
def test_unknown_effect_or_position_is_rejected(
    field: str,
    value: str,
    loc: tuple[object, ...],
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(_fault_json(**{field: value}))
    assert_error(exc_info, loc, "enum")


@pytest.mark.parametrize("bad_seed", [1.5, "17", None, True])
def test_non_integer_seed_is_rejected(
    bad_seed: object, assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(_fault_json(seed=bad_seed))
    assert_error(exc_info, ("seed",), "int_type")


def test_negative_seed_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(_fault_json(seed=-1))
    assert_error(exc_info, ("seed",), "greater_than_equal")


def test_missing_required_flag_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    data = loads(_fault_json())
    del data["required"]
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate(data)
    assert_error(exc_info, ("required",), "missing")


def test_descending_visibility_ticks_are_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(
            _fault_json(
                visibility_schedule=[
                    {"tick": 3, "visible_revision": 0},
                    {"tick": 1, "visible_revision": 1},
                ]
            )
        )
    error = assert_error(exc_info, ("visibility_schedule",), "value_error")
    assert "unique and increasing" in error["msg"]


def test_duplicate_visibility_ticks_are_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(
            _fault_json(
                visibility_schedule=[
                    {"tick": 2, "visible_revision": 0},
                    {"tick": 2, "visible_revision": 1},
                ]
            )
        )
    assert_error(exc_info, ("visibility_schedule",), "value_error")


def test_float_visibility_tick_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(
            _fault_json(visibility_schedule=[{"tick": 1.5, "visible_revision": 0}])
        )
    assert_error(exc_info, ("visibility_schedule", 0, "tick"), "int_type")


def test_empty_visibility_schedule_is_permitted() -> None:
    fault = FaultSpec.model_validate_json(_fault_json(visibility_schedule=[]))
    assert fault.visibility_schedule == ()


def test_strictly_increasing_multi_step_schedule_is_accepted() -> None:
    fault = FaultSpec.model_validate_json(
        _fault_json(
            visibility_schedule=[
                {"tick": 0, "visible_revision": 0},
                {"tick": 2, "visible_revision": 1},
                {"tick": 5, "visible_revision": 2},
            ]
        )
    )
    assert tuple(step.tick for step in fault.visibility_schedule) == (0, 2, 5)


def test_bad_fault_fixture_pins_missing_selector(
    fixture_text: Callable[[str], str], assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(fixture_text("bad_fault.json"))
    assert_error(exc_info, ("trigger",), "value_error")


def test_trigger_strict_python_requires_enum_instance() -> None:
    # Strict construction rejects a plain string where an EventKind is expected.
    with pytest.raises(ValidationError) as exc_info:
        FaultTrigger(
            service="dummy_github",
            operation="create_issue",
            event_kind="attempt_dispatched",  # type: ignore[arg-type]
        )
    assert exc_info.value.errors()[0]["loc"] == ("event_kind",)


def test_visibility_step_rejects_negative_revision(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        VisibilityStep(tick=0, visible_revision=-1)
    assert_error(exc_info, ("visible_revision",), "greater_than_equal")
