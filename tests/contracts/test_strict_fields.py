"""Every T002A model forbids unknown fields at the top level and when nested.

Traceability: Architecture scenario loader / minimal artifact schema
(``extra="forbid"``) and the T002B matrix "Unknown fields" row.
"""

from collections.abc import Callable
from json import dumps
from typing import cast

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from side_effects_lab.models import (
    ActionClaim,
    AuthorityGrant,
    FaultSpec,
    LabEvent,
    SemanticIntent,
)

_DIGEST = "sha256:015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"

VALID_PAYLOADS: dict[str, tuple[type[BaseModel], dict[str, object]]] = {
    "SemanticIntent": (
        SemanticIntent,
        {"service": "dummy_github", "operation": "create_issue", "parameters": {}},
    ),
    "AuthorityGrant": (
        AuthorityGrant,
        {
            "authority_id": "auth-x",
            "subject_id": "reconcile-first",
            "service": "dummy_github",
            "operation": "create_issue",
            "semantic_intent_digest": _DIGEST,
            "allowed_parameters": {},
            "expires_at_tick": 1,
            "max_effects": 1,
        },
    ),
    "FaultSpec": (
        FaultSpec,
        {
            "fault_id": "fault-x",
            "trigger": {
                "service": "dummy_github",
                "operation": "create_issue",
                "call_ordinal": 1,
            },
            "commit_position": "before_commit",
            "state_effect": "commit",
            "response_effect": "return",
            "visibility_schedule": [],
            "required": True,
            "seed": 1,
        },
    ),
    "LabEvent": (
        LabEvent,
        {"seq": 1, "tick": 0, "kind": "read_observed", "evidence": {}},
    ),
    "ActionClaim": (
        ActionClaim,
        {"action_id": "action-x", "status": "complete"},
    ),
}

_IDS = list(VALID_PAYLOADS)


def _validate(model: type[BaseModel], payload: dict[str, object]) -> BaseModel:
    # Strict models coerce enum strings and JSON arrays only through the JSON
    # path, which is the real artifact-loading path these primitives serve.
    return model.model_validate_json(dumps(payload))


@pytest.mark.parametrize("name", _IDS)
def test_valid_payload_is_accepted(name: str) -> None:
    model, payload = VALID_PAYLOADS[name]
    assert isinstance(_validate(model, payload), model)


@pytest.mark.parametrize("name", _IDS)
def test_extra_top_level_field_is_rejected(
    name: str, assert_error: Callable[..., ErrorDetails]
) -> None:
    model, payload = VALID_PAYLOADS[name]
    poisoned = {**payload, "unexpected_field": "x"}
    with pytest.raises(ValidationError) as exc_info:
        _validate(model, poisoned)
    assert_error(exc_info, ("unexpected_field",), "extra_forbidden")


def test_unknown_field_fixture_is_rejected(
    fixture_text: Callable[[str], str], assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        SemanticIntent.model_validate_json(fixture_text("unknown_field.json"))
    assert_error(exc_info, ("extra_field",), "extra_forbidden")


def test_nested_trigger_forbids_extra_field(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    _model, payload = VALID_PAYLOADS["FaultSpec"]
    trigger = dict(cast("dict[str, object]", payload["trigger"]))
    trigger["surprise"] = 1
    poisoned = {**payload, "trigger": trigger}
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(dumps(poisoned))
    assert_error(exc_info, ("trigger", "surprise"), "extra_forbidden")


def test_nested_visibility_step_forbids_extra_field(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    _model, payload = VALID_PAYLOADS["FaultSpec"]
    poisoned = {
        **payload,
        "visibility_schedule": [{"tick": 1, "visible_revision": 0, "extra": 1}],
    }
    with pytest.raises(ValidationError) as exc_info:
        FaultSpec.model_validate_json(dumps(poisoned))
    assert_error(exc_info, ("visibility_schedule", 0, "extra"), "extra_forbidden")
