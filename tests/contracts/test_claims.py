"""Action-claim boundaries: status vocabulary and required action identity.

Traceability: Architecture claims and mechanical verdicts; the T002B matrix
"Claim primitive" row.
"""

from collections.abc import Callable
from json import dumps, loads

import pytest
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from side_effects_lab.models import ActionClaim, ClaimStatus


@pytest.mark.parametrize("status", ["complete", "blocked", "partial"])
def test_every_status_round_trips(status: str) -> None:
    claim = ActionClaim.model_validate_json(
        dumps({"action_id": "action-create-issue", "status": status})
    )
    assert claim.status is ClaimStatus(status)
    assert claim.effect_id is None
    assert ActionClaim.model_validate_json(claim.model_dump_json()) == claim


def test_claim_with_effect_id_round_trips() -> None:
    claim = ActionClaim.model_validate_json(
        dumps(
            {
                "action_id": "action-create-issue",
                "status": "complete",
                "effect_id": "issue-1",
            }
        )
    )
    assert claim.effect_id == "issue-1"


def test_unknown_status_is_rejected(
    fixture_text: Callable[[str], str], assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ActionClaim.model_validate_json(fixture_text("bad_enum.json"))
    assert_error(exc_info, ("status",), "enum")


def test_missing_action_identity_is_rejected(
    fixture_text: Callable[[str], str], assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ActionClaim.model_validate_json(fixture_text("bad_claim.json"))
    assert_error(exc_info, ("action_id",), "missing")


def test_wrong_action_prefix_is_rejected(
    fixture_text: Callable[[str], str], assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ActionClaim.model_validate_json(fixture_text("bad_identifier.json"))
    assert_error(exc_info, ("action_id",), "string_pattern_mismatch")


def test_extra_field_is_rejected(assert_error: Callable[..., ErrorDetails]) -> None:
    data = loads(dumps({"action_id": "action-create-issue", "status": "complete"}))
    data["confidence"] = "high"
    with pytest.raises(ValidationError) as exc_info:
        ActionClaim.model_validate(data)
    assert_error(exc_info, ("confidence",), "extra_forbidden")


def test_wrong_effect_id_grammar_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ActionClaim.model_validate_json(
            dumps(
                {"action_id": "action-x", "status": "complete", "effect_id": "1issue"}
            )
        )
    assert_error(exc_info, ("effect_id",), "string_pattern_mismatch")
