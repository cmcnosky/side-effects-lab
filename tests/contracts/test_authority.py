"""Authority-grant boundaries: identity, intent digest, bounds, cardinality.

Traceability: Architecture authority engine and the T002B matrix "Authority
grant" row. A grant binds one immutable semantic intent; scope creep, float
cardinality, and missing digests are rejected at the model boundary.
"""

from collections.abc import Callable

import pytest
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from side_effects_lab.models import AuthorityGrant

_DIGEST = "sha256:015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"


def _grant(**overrides: object) -> AuthorityGrant:
    payload: dict[str, object] = {
        "authority_id": "auth-create-issue",
        "subject_id": "reconcile-first",
        "service": "dummy_github",
        "operation": "create_issue",
        "semantic_intent_digest": _DIGEST,
        "allowed_parameters": {"title": "Update docs"},
        "expires_at_tick": 12,
        "max_effects": 1,
    }
    payload.update(overrides)
    return AuthorityGrant.model_validate(payload)


def test_valid_grant_from_fixture(fixture_text: Callable[[str], str]) -> None:
    grant = AuthorityGrant.model_validate_json(fixture_text("valid_authority.json"))
    assert grant.max_effects == 1
    assert grant.expires_at_tick == 12
    assert grant.allowed_compensation == "action-close-issue"
    assert AuthorityGrant.model_validate_json(grant.model_dump_json()) == grant


def test_optional_compensation_defaults_to_none() -> None:
    assert _grant().allowed_compensation is None


def test_missing_intent_digest_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    payload: dict[str, object] = {
        "authority_id": "auth-create-issue",
        "subject_id": "reconcile-first",
        "service": "dummy_github",
        "operation": "create_issue",
        "allowed_parameters": {},
        "expires_at_tick": 1,
        "max_effects": 1,
    }
    with pytest.raises(ValidationError) as exc_info:
        AuthorityGrant.model_validate(payload)
    assert_error(exc_info, ("semantic_intent_digest",), "missing")


def test_float_cardinality_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _grant(max_effects=1.5)
    assert_error(exc_info, ("max_effects",), "int_type")


def test_zero_cardinality_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _grant(max_effects=0)
    assert_error(exc_info, ("max_effects",), "greater_than")


def test_negative_expiry_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _grant(expires_at_tick=-1)
    assert_error(exc_info, ("expires_at_tick",), "greater_than_equal")


def test_zero_expiry_is_permitted() -> None:
    assert _grant(expires_at_tick=0).expires_at_tick == 0


def test_extra_scope_field_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _grant(scope="admin")
    assert_error(exc_info, ("scope",), "extra_forbidden")


def test_bad_digest_field_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _grant(semantic_intent_digest="sha256:" + "A" * 64)
    assert_error(exc_info, ("semantic_intent_digest",), "string_pattern_mismatch")


def test_bad_authority_fixture_pins_float_cardinality(
    fixture_text: Callable[[str], str], assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AuthorityGrant.model_validate_json(fixture_text("bad_authority.json"))
    assert_error(exc_info, ("max_effects",), "int_type")


def test_wrong_authority_id_prefix_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _grant(authority_id="grant-create-issue")
    assert_error(exc_info, ("authority_id",), "string_pattern_mismatch")


def test_wrong_compensation_prefix_is_rejected(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _grant(allowed_compensation="close-issue")
    assert_error(exc_info, ("allowed_compensation",), "string_pattern_mismatch")
