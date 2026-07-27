"""Execute every generated schema with a real Draft 2020-12 validator.

Traceability: Architecture minimal artifact schema (compact, key-sorted Draft
2020-12 JSON rendered from the model registry) and the T002B matrix determinism
checks that schemas must be valid, forbid additional properties, and expose the
same required fields and enum members as the models. The fault trigger XOR is
checked for schema/model agreement; visibility monotonicity is asserted to be a
model-only rule the schema deliberately does not encode.
"""

from json import loads
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from side_effects_lab.canonical import canonical_json_bytes
from side_effects_lab.models import (
    ActionClaim,
    AuthorityGrant,
    ClaimStatus,
    CommitPosition,
    EventKind,
    FaultSpec,
    FaultTrigger,
    LabEvent,
    ResponseEffect,
    SemanticIntent,
    StateEffect,
    VisibilityStep,
)
from side_effects_lab.schema_generation import expected_schemas

_DIGEST = "sha256:015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"

VALID_INSTANCES: dict[str, BaseModel] = {
    "action-claim.schema.json": ActionClaim(
        action_id="action-create-issue",
        status=ClaimStatus.COMPLETE,
        effect_id="issue-1",
    ),
    "authority-grant.schema.json": AuthorityGrant(
        authority_id="auth-create-issue",
        subject_id="reconcile-first",
        service="dummy_github",
        operation="create_issue",
        semantic_intent_digest=_DIGEST,
        allowed_parameters={"title": "Update docs"},
        expires_at_tick=12,
        max_effects=1,
    ),
    "event.schema.json": LabEvent(
        seq=1,
        tick=0,
        kind=EventKind.EFFECT_COMMITTED,
        action_id="action-create-issue",
        operation_key="op-sel001",
        effect_id="issue-1",
        evidence={"revision": 1},
    ),
    "fault-spec.schema.json": FaultSpec(
        fault_id="fault-vanished-receipt",
        trigger=FaultTrigger(
            service="dummy_github", operation="create_issue", call_ordinal=1
        ),
        commit_position=CommitPosition.AFTER_COMMIT_BEFORE_RESPONSE,
        state_effect=StateEffect.COMMIT,
        response_effect=ResponseEffect.DROP,
        visibility_schedule=(VisibilityStep(tick=1, visible_revision=0),),
        required=True,
        seed=17,
    ),
    "semantic-intent.schema.json": SemanticIntent(
        service="dummy_github",
        operation="create_issue",
        parameters={"title": "Update docs", "labels": ["docs"]},
    ),
}

_SCHEMA_IDS = list(VALID_INSTANCES)


def _schema(name: str) -> dict[str, object]:
    return cast(dict[str, object], loads(expected_schemas()[name]))


@pytest.mark.parametrize("name", _SCHEMA_IDS)
def test_generated_schema_is_valid_draft_2020_12(name: str) -> None:
    document = _schema(name)
    Draft202012Validator.check_schema(document)
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert document["x-side-effects-lab-schema-version"] == "0.1"


@pytest.mark.parametrize("name", _SCHEMA_IDS)
def test_schema_accepts_the_model_dump(name: str) -> None:
    validator = Draft202012Validator(_schema(name))
    validator.validate(VALID_INSTANCES[name].model_dump(mode="json"))


@pytest.mark.parametrize("name", _SCHEMA_IDS)
def test_schema_forbids_additional_properties(name: str) -> None:
    document = _schema(name)
    assert document["additionalProperties"] is False
    validator = Draft202012Validator(document)
    payload = VALID_INSTANCES[name].model_dump(mode="json")
    payload["injected_field"] = "x"
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(payload)


@pytest.mark.parametrize("name", _SCHEMA_IDS)
def test_schema_required_matches_model(name: str) -> None:
    document = _schema(name)
    model = type(VALID_INSTANCES[name])
    model_required = {
        field for field, info in model.model_fields.items() if info.is_required()
    }
    assert set(cast(list[str], document["required"])) == model_required


@pytest.mark.parametrize("name", _SCHEMA_IDS)
def test_schema_rejects_each_missing_required_field(name: str) -> None:
    document = _schema(name)
    validator = Draft202012Validator(document)
    base = VALID_INSTANCES[name].model_dump(mode="json")
    for field in cast(list[str], document["required"]):
        broken = {k: v for k, v in base.items() if k != field}
        with pytest.raises(JsonSchemaValidationError):
            validator.validate(broken)


def test_schema_enums_match_model_enums() -> None:
    claim_schema = _schema("action-claim.schema.json")
    status_def = cast(dict[str, object], claim_schema["$defs"])["ClaimStatus"]
    assert set(cast(dict[str, list[str]], status_def)["enum"]) == {
        member.value for member in ClaimStatus
    }

    fault_schema = _schema("fault-spec.schema.json")
    defs = cast(dict[str, object], fault_schema["$defs"])
    for enum_name, enum_cls in (
        ("CommitPosition", CommitPosition),
        ("StateEffect", StateEffect),
        ("ResponseEffect", ResponseEffect),
        ("EventKind", EventKind),
    ):
        enum_def = cast(dict[str, list[str]], defs[enum_name])
        assert set(enum_def["enum"]) == {member.value for member in enum_cls}


def test_schema_rejects_unknown_enum_member() -> None:
    validator = Draft202012Validator(_schema("action-claim.schema.json"))
    with pytest.raises(JsonSchemaValidationError):
        validator.validate({"action_id": "action-x", "status": "finished"})


def _fault_payload(trigger: dict[str, object]) -> dict[str, object]:
    return {
        "fault_id": "fault-schema-xor",
        "trigger": {"service": "dummy_github", "operation": "create_issue", **trigger},
        "commit_position": "after_commit_before_response",
        "state_effect": "commit",
        "response_effect": "drop",
        "visibility_schedule": [{"tick": 2, "visible_revision": 1}],
        "required": True,
        "seed": 17,
    }


def test_fault_selector_xor_agrees_between_schema_and_model() -> None:
    validator = Draft202012Validator(_schema("fault-spec.schema.json"))
    valid: list[dict[str, object]] = [
        {"call_ordinal": 1, "event_kind": None},
        {"call_ordinal": None, "event_kind": "attempt_dispatched"},
    ]
    for trigger in valid:
        model = FaultSpec.model_validate_json(
            canonical_json_bytes(_fault_payload(trigger))
        )
        validator.validate(model.model_dump(mode="json"))

    invalid: list[dict[str, object]] = [
        {},
        {"call_ordinal": None},
        {"event_kind": None},
        {"call_ordinal": None, "event_kind": None},
        {"call_ordinal": 1, "event_kind": "attempt_dispatched"},
    ]
    for trigger in invalid:
        with pytest.raises(JsonSchemaValidationError):
            validator.validate(_fault_payload(trigger))
        with pytest.raises(PydanticValidationError, match="exactly one"):
            FaultSpec.model_validate_json(canonical_json_bytes(_fault_payload(trigger)))


def test_visibility_monotonicity_is_model_only_not_schema() -> None:
    # A descending visibility schedule is schema-valid (JSON Schema cannot express
    # monotonic item order) but the model rejects it. This pins the rule as
    # model-level exactly as the architecture states.
    validator = Draft202012Validator(_schema("fault-spec.schema.json"))
    descending = _fault_payload({"call_ordinal": 1})
    descending["visibility_schedule"] = [
        {"tick": 3, "visible_revision": 0},
        {"tick": 1, "visible_revision": 1},
    ]
    validator.validate(descending)  # schema accepts it
    with pytest.raises(PydanticValidationError, match="unique and increasing"):
        FaultSpec.model_validate_json(canonical_json_bytes(descending))
