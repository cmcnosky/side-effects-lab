"""Semantic-intent round trips and intent-difference digest behavior.

Traceability: Architecture "Frozen base-contract conventions" (semantic intent
is the strict object service/operation/normalized parameters, wire-independent)
and the T002B matrix "Semantic intent" row.
"""

from collections.abc import Callable
from json import loads

import pytest
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from side_effects_lab.canonical import canonical_digest, canonical_json_bytes
from side_effects_lab.models import CanonicalValue, SemanticIntent


def _extract(raw: str, key: str) -> object:
    document = loads(raw)
    assert isinstance(document, dict)
    return document[key]


def _intent(
    service: str, operation: str, parameters: dict[str, CanonicalValue]
) -> SemanticIntent:
    return SemanticIntent(service=service, operation=operation, parameters=parameters)


def test_intent_round_trips_through_strict_json(
    fixture_text: Callable[[str], str],
) -> None:
    raw = fixture_text("valid_contract_sample.json")
    intent = SemanticIntent.model_validate_json(
        canonical_json_bytes(_extract(raw, "semantic_intent"))
    )
    reparsed = SemanticIntent.model_validate_json(intent.model_dump_json())
    assert reparsed == intent
    assert canonical_digest(reparsed) == canonical_digest(intent)


def test_intent_is_wire_independent_and_order_stable() -> None:
    forward = _intent("dummy_github", "create_issue", {"title": "T", "body": "B"})
    reversed_order = _intent(
        "dummy_github", "create_issue", {"body": "B", "title": "T"}
    )
    assert canonical_digest(forward) == canonical_digest(reversed_order)


def test_changed_service_operation_or_parameters_change_the_digest() -> None:
    base = _intent("dummy_github", "create_issue", {"title": "T"})
    base_digest = canonical_digest(base)

    assert (
        canonical_digest(_intent("dummy_gitlab", "create_issue", {"title": "T"}))
        != base_digest
    )
    assert (
        canonical_digest(_intent("dummy_github", "close_issue", {"title": "T"}))
        != base_digest
    )
    assert (
        canonical_digest(_intent("dummy_github", "create_issue", {"title": "X"}))
        != base_digest
    )
    assert (
        canonical_digest(_intent("dummy_github", "create_issue", {"label": "T"}))
        != base_digest
    )


@pytest.mark.parametrize(
    "bad_service",
    ["Dummy", "dummy-github", "1service", "dummy github", "dummy.github"],
)
def test_intent_rejects_non_grammar_service(
    bad_service: str, assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _intent(bad_service, "create_issue", {})
    assert_error(exc_info, ("service",), "string_pattern_mismatch")


def test_intent_rejects_non_grammar_parameter_key(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _intent("dummy_github", "create_issue", {"Bad-Key": 1})
    error = assert_error(exc_info, ("parameters", "Bad-Key"), "string_pattern_mismatch")
    assert error["loc"][-1] == "[key]"


def test_nested_canonical_values_round_trip() -> None:
    intent = _intent(
        "dummy_github",
        "create_issue",
        {"nested": {"flags": [True, False], "count": 3, "note": None}},
    )
    dumped = intent.model_dump(mode="json")
    assert dumped["parameters"] == {
        "nested": {"flags": [True, False], "count": 3, "note": None}
    }
    assert SemanticIntent.model_validate(dumped) == intent
