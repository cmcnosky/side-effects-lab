"""T002-owned primitives round-trip inside one minimal composite sample.

Traceability: Architecture minimal artifact schema and the T002B matrix
"Artifact-facing primitives" row. T002A owns the primitives, not the artifact
envelope (that is T013), so the "minimal sample" is a composite of each frozen
primitive validated through its own model. Missing/extra/embedded-float
mutations are rejected at the owning primitive.
"""

from collections.abc import Callable
from json import dumps, loads
from typing import cast

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from side_effects_lab.canonical import canonical_digest
from side_effects_lab.models import (
    ActionClaim,
    AuthorityGrant,
    FaultSpec,
    LabEvent,
    SemanticIntent,
)

PRIMITIVES: dict[str, type[BaseModel]] = {
    "semantic_intent": SemanticIntent,
    "authority_grant": AuthorityGrant,
    "fault_spec": FaultSpec,
    "event": LabEvent,
    "action_claim": ActionClaim,
}


def _sample(fixture_json: Callable[[str], object]) -> dict[str, object]:
    document = fixture_json("valid_contract_sample.json")
    assert isinstance(document, dict)
    return document


def test_sample_covers_every_owned_primitive(
    fixture_json: Callable[[str], object],
) -> None:
    assert set(_sample(fixture_json)) == set(PRIMITIVES)


@pytest.mark.parametrize("key", list(PRIMITIVES))
def test_each_primitive_round_trips(
    key: str, fixture_json: Callable[[str], object]
) -> None:
    model = PRIMITIVES[key]
    section = _sample(fixture_json)[key]
    parsed = model.model_validate_json(dumps(section))
    reparsed = model.model_validate_json(parsed.model_dump_json())
    assert reparsed == parsed
    # Every primitive is canonicalizable and digests stably.
    assert canonical_digest(parsed) == canonical_digest(reparsed)


@pytest.mark.parametrize(
    "key,required_field",
    [
        ("semantic_intent", "operation"),
        ("authority_grant", "semantic_intent_digest"),
        ("fault_spec", "trigger"),
        ("event", "kind"),
        ("action_claim", "action_id"),
    ],
)
def test_missing_required_primitive_field_is_rejected(
    key: str,
    required_field: str,
    fixture_json: Callable[[str], object],
    assert_error: Callable[..., ErrorDetails],
) -> None:
    section = dict(cast("dict[str, object]", _sample(fixture_json)[key]))
    section.pop(required_field)
    with pytest.raises(ValidationError) as exc_info:
        PRIMITIVES[key].model_validate_json(dumps(section))
    assert_error(exc_info, (required_field,), "missing")


@pytest.mark.parametrize("key", list(PRIMITIVES))
def test_extra_field_on_primitive_is_rejected(
    key: str,
    fixture_json: Callable[[str], object],
    assert_error: Callable[..., ErrorDetails],
) -> None:
    section = dict(cast("dict[str, object]", _sample(fixture_json)[key]))
    section["injected"] = "x"
    with pytest.raises(ValidationError) as exc_info:
        PRIMITIVES[key].model_validate_json(dumps(section))
    assert_error(exc_info, ("injected",), "extra_forbidden")


def test_embedded_float_in_sample_intent_is_rejected(
    fixture_json: Callable[[str], object],
) -> None:
    section = dict(cast("dict[str, object]", _sample(fixture_json)["semantic_intent"]))
    section["parameters"] = {"weight": 2.5}
    with pytest.raises(ValidationError) as exc_info:
        SemanticIntent.model_validate_json(dumps(section))
    assert exc_info.value.errors()[0]["loc"][:2] == ("parameters", "weight")


def test_sample_bytes_are_canonicalizable_end_to_end(
    fixture_text: Callable[[str], str],
) -> None:
    document = loads(fixture_text("valid_contract_sample.json"))
    # A digest of the whole minimal sample is stable and float-free.
    assert canonical_digest(document).startswith("sha256:")
