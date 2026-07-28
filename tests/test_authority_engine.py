"""Unit tests for deterministic authority checks.

Traceability: the T007 decision matrix, reason precedence, and evidence
contract over the frozen contracts in `models.py` and the canonical state
machine in `state_machine.py`.
"""

from dataclasses import FrozenInstanceError, asdict, replace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from side_effects_lab.authority import (
    REASON_PRECEDENCE,
    AuthorityCheck,
    AuthorityDecision,
    AuthorityDisposition,
    AuthorityReason,
    CheckKind,
    check_authority,
)
from side_effects_lab.canonical import canonical_digest
from side_effects_lab.models import (
    AuthorityGrant,
    CanonicalValue,
    FrozenMap,
    SemanticIntent,
)
from side_effects_lab.state_machine import (
    NORMATIVE_TRANSITIONS,
    InvalidTransitionError,
    OperationIdentity,
    OperationState,
    OperationStateMachine,
    TransitionCause,
    TransitionEvidence,
)

_PARAMETERS: dict[str, CanonicalValue] = {
    "title": "Update docs",
    "labels": ["docs", "safety"],
    "meta": {"priority": 2, "urgent": True},
}
_WRONG_DIGEST = "sha256:" + "9" * 64


def _intent(
    *,
    service: str = "dummy_github",
    operation: str = "create_issue",
    parameters: dict[str, CanonicalValue] | None = None,
) -> SemanticIntent:
    return SemanticIntent.model_validate(
        {
            "service": service,
            "operation": operation,
            "parameters": _PARAMETERS if parameters is None else parameters,
        }
    )


_INTENT = _intent()
_INTENT_DIGEST = canonical_digest(_INTENT)
_IDENTITY = OperationIdentity(
    action_id="action-create-issue",
    operation_key="op-sel001",
    intent_digest=_INTENT_DIGEST,
    authority_id="auth-create-issue",
)
_WRITE_KINDS = (
    CheckKind.AUTHORIZE,
    CheckKind.PASSIVE_PRE_DISPATCH,
    CheckKind.PRE_DISPATCH_WRITE,
    CheckKind.REDISPATCH,
)
_EXPECTED_EVIDENCE_KEYS = (
    "action_id",
    "authority_id",
    "authority_id_match",
    "candidate_intent_digest",
    "cardinality_valid",
    "check_kind",
    "checked_tick",
    "committed_effect_count",
    "compensation_authorized",
    "compensation_claimed",
    "disposition",
    "expires_at_tick",
    "grant_authority_id",
    "grant_intent_digest",
    "identity_confirmed",
    "intent_digest_match",
    "max_effects",
    "operation_key",
    "operation_match",
    "parameters_match",
    "reason",
    "recomputed_intent_digest",
    "service_match",
    "subject_match",
    "tick_valid",
)


def _grant(**overrides: object) -> AuthorityGrant:
    payload: dict[str, object] = {
        "authority_id": "auth-create-issue",
        "subject_id": "reconcile-first",
        "service": "dummy_github",
        "operation": "create_issue",
        "semantic_intent_digest": _INTENT_DIGEST,
        "allowed_parameters": _PARAMETERS,
        "expires_at_tick": 12,
        "max_effects": 1,
    }
    payload.update(overrides)
    return AuthorityGrant.model_validate(payload)


def _original_grant(**overrides: object) -> AuthorityGrant:
    payload: dict[str, object] = {
        "authority_id": "auth-original-effect",
        "subject_id": "reconcile-first",
        "service": "dummy_github",
        "operation": "create_issue",
        "semantic_intent_digest": "sha256:" + "3" * 64,
        "allowed_parameters": {},
        "expires_at_tick": 2,
        "max_effects": 1,
        "allowed_compensation": "action-create-issue",
    }
    payload.update(overrides)
    return AuthorityGrant.model_validate(payload)


def _check(
    kind: CheckKind = CheckKind.PRE_DISPATCH_WRITE,
    *,
    candidate: OperationIdentity = _IDENTITY,
    confirmed: OperationIdentity | None = None,
    subject_id: str = "reconcile-first",
    intent: SemanticIntent = _INTENT,
    current_tick: int = 5,
    committed_effect_count: int = 0,
    is_compensation: bool = False,
    original_grant: AuthorityGrant | None = None,
) -> AuthorityCheck:
    return AuthorityCheck(
        kind=kind,
        candidate=candidate,
        confirmed=candidate if confirmed is None else confirmed,
        subject_id=subject_id,
        intent=intent,
        current_tick=current_tick,
        committed_effect_count=committed_effect_count,
        is_compensation=is_compensation,
        original_grant=original_grant,
    )


def _authorized_machine() -> OperationStateMachine:
    machine = OperationStateMachine(_IDENTITY)
    machine.transition(
        OperationState.AUTHORIZED,
        evidence=TransitionEvidence(
            "evidence-initial-authorization",
            TransitionCause.AUTHORITY_CONFIRMED,
        ),
        identity=_IDENTITY,
    )
    return machine


def test_reason_vocabulary_and_precedence_are_pinned() -> None:
    assert REASON_PRECEDENCE == (
        AuthorityReason.IDENTITY_MISMATCH,
        AuthorityReason.AUTHORITY_ID_MISMATCH,
        AuthorityReason.SUBJECT_MISMATCH,
        AuthorityReason.SERVICE_MISMATCH,
        AuthorityReason.OPERATION_MISMATCH,
        AuthorityReason.INTENT_DIGEST_MISMATCH,
        AuthorityReason.PARAMETERS_MISMATCH,
        AuthorityReason.COMPENSATION_NOT_AUTHORIZED,
        AuthorityReason.CARDINALITY_EXCEEDED,
        AuthorityReason.AUTH_EXPIRED,
    )
    assert [reason.value for reason in AuthorityReason] == [
        "IDENTITY_MISMATCH",
        "AUTHORITY_ID_MISMATCH",
        "SUBJECT_MISMATCH",
        "SERVICE_MISMATCH",
        "OPERATION_MISMATCH",
        "INTENT_DIGEST_MISMATCH",
        "PARAMETERS_MISMATCH",
        "COMPENSATION_NOT_AUTHORIZED",
        "CARDINALITY_EXCEEDED",
        "AUTH_EXPIRED",
        "AUTHORIZED",
        "REVALIDATED",
        "READ_ONLY_ALLOWED",
    ]
    assert [kind.value for kind in CheckKind] == [
        "authorize",
        "passive_pre_dispatch",
        "pre_dispatch_write",
        "redispatch",
        "read_only",
    ]
    assert [disposition.value for disposition in AuthorityDisposition] == [
        "ALLOW",
        "SAFE_STOP",
        "VIOLATION",
    ]


def test_exact_authorize_allows_with_the_authorized_transition() -> None:
    decision = check_authority(_grant(), _check(CheckKind.AUTHORIZE))

    assert decision.disposition is AuthorityDisposition.ALLOW
    assert decision.reason is AuthorityReason.AUTHORIZED
    assert decision.target is OperationState.AUTHORIZED
    assert decision.cause is TransitionCause.AUTHORITY_CONFIRMED
    assert decision.evidence["disposition"] == "ALLOW"
    assert decision.evidence["reason"] == "AUTHORIZED"
    assert decision.evidence["tick_valid"] is True
    assert decision.evidence["cardinality_valid"] is True

    machine = OperationStateMachine(_IDENTITY)
    record = machine.transition(
        decision.target,
        evidence=TransitionEvidence("evidence-authority-check", decision.cause),
        identity=_IDENTITY,
    )
    assert record.resulting_state is OperationState.AUTHORIZED


@pytest.mark.parametrize(
    "kind",
    [
        CheckKind.PASSIVE_PRE_DISPATCH,
        CheckKind.PRE_DISPATCH_WRITE,
        CheckKind.REDISPATCH,
    ],
)
def test_exact_revalidation_allows_without_any_transition(kind: CheckKind) -> None:
    decision = check_authority(_grant(), _check(kind))

    assert decision.disposition is AuthorityDisposition.ALLOW
    assert decision.reason is AuthorityReason.REVALIDATED
    assert decision.target is None
    assert decision.cause is None


def test_redispatch_revalidation_never_advances_a_retry_by_itself() -> None:
    decision = check_authority(_grant(), _check(CheckKind.REDISPATCH))

    assert (decision.target, decision.cause) == (None, None)
    # Retry advancement and the no-valid-authority stop stay caller-owned in
    # the canonical machine; T007 neither performs nor redefines them.
    assert (
        NORMATIVE_TRANSITIONS[(OperationState.RETRYABLE, OperationState.IN_FLIGHT)]
        is TransitionCause.REDISPATCH_AUTHORIZED
    )
    assert (
        NORMATIVE_TRANSITIONS[(OperationState.RETRYABLE, OperationState.SAFE_STOP)]
        is TransitionCause.SAFE_STOP_SELECTED
    )


def test_expiry_boundary_is_inclusive() -> None:
    grant = _grant(expires_at_tick=12)

    at_boundary = check_authority(grant, _check(current_tick=12))
    assert at_boundary.disposition is AuthorityDisposition.ALLOW
    assert at_boundary.evidence["tick_valid"] is True

    past_boundary = check_authority(grant, _check(current_tick=13))
    assert past_boundary.disposition is AuthorityDisposition.VIOLATION
    assert past_boundary.reason is AuthorityReason.AUTH_EXPIRED
    assert past_boundary.evidence["tick_valid"] is False


def test_passive_expiry_safe_stops_from_authorized_without_attempts() -> None:
    decision = check_authority(
        _grant(), _check(CheckKind.PASSIVE_PRE_DISPATCH, current_tick=13)
    )

    assert decision.disposition is AuthorityDisposition.SAFE_STOP
    assert decision.reason is AuthorityReason.AUTH_EXPIRED
    assert decision.target is OperationState.SAFE_STOP
    assert decision.cause is TransitionCause.SAFE_STOP_SELECTED
    assert decision.evidence["reason"] == "AUTH_EXPIRED"

    machine = _authorized_machine()
    record = machine.transition(
        decision.target,
        evidence=TransitionEvidence("evidence-passive-expiry", decision.cause),
        identity=_IDENTITY,
    )
    assert record.resulting_state is OperationState.SAFE_STOP
    assert machine.attempt_ids == ()


@pytest.mark.parametrize("prepared", [False, True], ids=["proposed", "prepared"])
def test_passive_safe_stop_is_rejected_outside_authorized(prepared: bool) -> None:
    decision = check_authority(
        _grant(), _check(CheckKind.PASSIVE_PRE_DISPATCH, current_tick=13)
    )
    assert decision.target is OperationState.SAFE_STOP
    assert decision.cause is TransitionCause.SAFE_STOP_SELECTED

    machine = _authorized_machine() if prepared else OperationStateMachine(_IDENTITY)
    if prepared:
        machine.transition(
            OperationState.PREPARED,
            evidence=TransitionEvidence(
                "evidence-durable-preparation",
                TransitionCause.PREPARATION_DURABLE,
            ),
            identity=_IDENTITY,
        )

    with pytest.raises(InvalidTransitionError):
        machine.transition(
            decision.target,
            evidence=TransitionEvidence("evidence-passive-expiry", decision.cause),
            identity=_IDENTITY,
        )


@pytest.mark.parametrize(
    "kind",
    [CheckKind.AUTHORIZE, CheckKind.PRE_DISPATCH_WRITE, CheckKind.REDISPATCH],
)
def test_each_attempted_expired_write_kind_is_a_zero_effect_violation(
    kind: CheckKind,
) -> None:
    decision = check_authority(
        _grant(), _check(kind, current_tick=13, committed_effect_count=0)
    )

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.AUTH_EXPIRED
    assert decision.target is OperationState.VIOLATION
    assert decision.cause is TransitionCause.INVARIANT_VIOLATION
    assert decision.evidence["committed_effect_count"] == 0

    machine = OperationStateMachine(_IDENTITY)
    record = machine.transition(
        decision.target,
        evidence=TransitionEvidence("evidence-expired-write", decision.cause),
        identity=_IDENTITY,
    )
    assert record.resulting_state is OperationState.VIOLATION


def test_read_only_remains_allowed_after_expiry_and_never_renews() -> None:
    grant = _grant()
    baseline = grant.model_dump()

    read = check_authority(grant, _check(CheckKind.READ_ONLY, current_tick=13))
    assert read.disposition is AuthorityDisposition.ALLOW
    assert read.reason is AuthorityReason.READ_ONLY_ALLOWED
    assert (read.target, read.cause) == (None, None)
    assert read.evidence["tick_valid"] is False

    # The read renewed nothing: the same grant still blocks an actual write.
    assert grant.model_dump() == baseline
    retry = check_authority(
        grant, _check(CheckKind.PRE_DISPATCH_WRITE, current_tick=13)
    )
    assert retry.disposition is AuthorityDisposition.VIOLATION
    assert retry.reason is AuthorityReason.AUTH_EXPIRED


@pytest.mark.parametrize("committed", [1, 2], ids=["at_cap", "above_cap"])
def test_read_only_is_allowed_at_and_above_the_cardinality_cap(
    committed: int,
) -> None:
    decision = check_authority(
        _grant(max_effects=1),
        _check(CheckKind.READ_ONLY, committed_effect_count=committed),
    )

    assert decision.disposition is AuthorityDisposition.ALLOW
    assert decision.reason is AuthorityReason.READ_ONLY_ALLOWED
    assert (decision.target, decision.cause) == (None, None)
    assert decision.evidence["committed_effect_count"] == committed
    assert decision.evidence["max_effects"] == 1
    assert decision.evidence["cardinality_valid"] is False


def test_defective_read_only_is_a_structured_violation() -> None:
    stolen = replace(_IDENTITY, action_id="action-thief")
    decision = check_authority(_grant(), _check(CheckKind.READ_ONLY, confirmed=stolen))

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.IDENTITY_MISMATCH
    assert decision.target is OperationState.VIOLATION
    assert decision.cause is TransitionCause.INVARIANT_VIOLATION


@pytest.mark.parametrize("kind", list(_WRITE_KINDS))
def test_write_cardinality_below_at_and_above_the_cap(kind: CheckKind) -> None:
    grant = _grant(max_effects=2)

    below = check_authority(grant, _check(kind, committed_effect_count=1))
    assert below.disposition is AuthorityDisposition.ALLOW
    assert below.evidence["cardinality_valid"] is True

    for committed in (2, 3):
        blocked = check_authority(grant, _check(kind, committed_effect_count=committed))
        assert blocked.disposition is AuthorityDisposition.VIOLATION
        assert blocked.reason is AuthorityReason.CARDINALITY_EXCEEDED
        assert blocked.target is OperationState.VIOLATION
        assert blocked.evidence["cardinality_valid"] is False


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("action_id", "action-thief"),
        ("operation_key", "op-thief"),
        ("intent_digest", _WRONG_DIGEST),
        ("authority_id", "auth-thief"),
    ],
)
def test_confirmation_is_exact_and_nontransferable(
    field_name: str,
    replacement: str,
) -> None:
    stolen = replace(_IDENTITY, **{field_name: replacement})
    decision = check_authority(_grant(), _check(confirmed=stolen))

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.IDENTITY_MISMATCH
    assert decision.evidence["identity_confirmed"] is False


def test_grant_authority_id_must_match_the_candidate() -> None:
    other = replace(_IDENTITY, authority_id="auth-other")
    decision = check_authority(_grant(), _check(candidate=other))

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.AUTHORITY_ID_MISMATCH
    assert decision.evidence["identity_confirmed"] is True
    assert decision.evidence["authority_id_match"] is False


def test_subject_mismatch_is_a_violation() -> None:
    decision = check_authority(_grant(), _check(subject_id="intruder"))

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.SUBJECT_MISMATCH
    assert decision.evidence["subject_match"] is False


@pytest.mark.parametrize(
    ("intent_overrides", "expected_reason"),
    [
        ({"service": "dummy_email"}, AuthorityReason.SERVICE_MISMATCH),
        ({"operation": "delete_repo"}, AuthorityReason.OPERATION_MISMATCH),
    ],
    ids=["service", "operation"],
)
def test_service_and_operation_mismatches_are_isolated_violations(
    intent_overrides: dict[str, str],
    expected_reason: AuthorityReason,
) -> None:
    intent = _intent(**cast(dict[str, Any], intent_overrides))
    digest = canonical_digest(intent)
    candidate = replace(_IDENTITY, intent_digest=digest)
    # The digests are aligned to the submitted intent so only the service or
    # operation scope defect remains against the grant.
    decision = check_authority(
        _grant(semantic_intent_digest=digest),
        _check(candidate=candidate, intent=intent),
    )

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is expected_reason


def test_recomputed_digest_must_match_candidate_and_grant() -> None:
    forged_candidate = replace(_IDENTITY, intent_digest=_WRONG_DIGEST)
    candidate_defect = check_authority(_grant(), _check(candidate=forged_candidate))
    assert candidate_defect.disposition is AuthorityDisposition.VIOLATION
    assert candidate_defect.reason is AuthorityReason.INTENT_DIGEST_MISMATCH
    assert candidate_defect.evidence["recomputed_intent_digest"] == _INTENT_DIGEST

    grant_defect = check_authority(
        _grant(semantic_intent_digest=_WRONG_DIGEST), _check()
    )
    assert grant_defect.disposition is AuthorityDisposition.VIOLATION
    assert grant_defect.reason is AuthorityReason.INTENT_DIGEST_MISMATCH
    assert grant_defect.evidence["intent_digest_match"] is False


@pytest.mark.parametrize(
    "allowed_parameters",
    [
        {**_PARAMETERS, "assignee": "owner"},
        {key: value for key, value in _PARAMETERS.items() if key != "labels"},
        {**_PARAMETERS, "title": "Something else"},
        {**_PARAMETERS, "meta": {"priority": 3, "urgent": True}},
        {**_PARAMETERS, "labels": ["safety", "docs"]},
    ],
    ids=["added_key", "removed_key", "changed_value", "nested_change", "list_order"],
)
def test_parameter_scope_changes_are_violations(
    allowed_parameters: dict[str, CanonicalValue],
) -> None:
    decision = check_authority(_grant(allowed_parameters=allowed_parameters), _check())

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.PARAMETERS_MISMATCH
    assert decision.evidence["parameters_match"] is False


def test_mapping_insertion_order_is_irrelevant() -> None:
    reordered: dict[str, CanonicalValue] = {
        "meta": {"urgent": True, "priority": 2},
        "labels": ["docs", "safety"],
        "title": "Update docs",
    }
    reordered_grant = check_authority(_grant(allowed_parameters=reordered), _check())
    assert reordered_grant.disposition is AuthorityDisposition.ALLOW

    reordered_intent = _intent(parameters=reordered)
    assert canonical_digest(reordered_intent) == _INTENT_DIGEST
    reordered_request = check_authority(_grant(), _check(intent=reordered_intent))
    assert reordered_request == reordered_grant


@pytest.mark.parametrize(
    ("granted", "requested"),
    [
        ({"flag": True}, {"flag": 1}),
        ({"flag": 0}, {"flag": False}),
        ({"meta": {"urgent": True}}, {"meta": {"urgent": 1}}),
        ({"labels": [True, "x"]}, {"labels": [1, "x"]}),
    ],
    ids=["top_level", "reversed", "nested_object", "nested_list"],
)
def test_bool_and_int_parameters_never_compare_equal(
    granted: dict[str, CanonicalValue],
    requested: dict[str, CanonicalValue],
) -> None:
    # Ordinary Python equality collapses these; canonical bytes must not.
    assert granted == requested
    intent = _intent(parameters=requested)
    digest = canonical_digest(intent)
    candidate = replace(_IDENTITY, intent_digest=digest)
    decision = check_authority(
        _grant(allowed_parameters=granted, semantic_intent_digest=digest),
        _check(candidate=candidate, intent=intent),
    )

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.PARAMETERS_MISMATCH


@pytest.mark.parametrize("field_name", ["current_tick", "committed_effect_count"])
@pytest.mark.parametrize(
    ("bad_value", "expected_error"),
    [
        (True, TypeError),
        (1.0, TypeError),
        ("3", TypeError),
        (-1, ValueError),
    ],
    ids=["bool", "float", "str", "negative"],
)
def test_strict_numeric_inputs_reject_coercion(
    field_name: str,
    bad_value: object,
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error):
        _check(**cast(dict[str, Any], {field_name: bad_value}))


def test_compensation_without_original_grant_is_not_authorized() -> None:
    decision = check_authority(_grant(), _check(is_compensation=True))

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.COMPENSATION_NOT_AUTHORIZED
    assert decision.evidence["compensation_claimed"] is True
    assert decision.evidence["compensation_authorized"] is False


@pytest.mark.parametrize(
    "original_overrides",
    [
        {"allowed_compensation": None},
        {"allowed_compensation": "action-other-cleanup"},
        {"authority_id": "auth-create-issue"},
    ],
    ids=["names_nothing", "names_other_action", "not_a_separate_grant"],
)
def test_compensation_failure_modes_are_violations(
    original_overrides: dict[str, object],
) -> None:
    decision = check_authority(
        _grant(),
        _check(
            is_compensation=True,
            original_grant=_original_grant(**original_overrides),
        ),
    )

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.COMPENSATION_NOT_AUTHORIZED
    assert decision.evidence["compensation_authorized"] is False


def test_exact_compensation_success_ignores_original_grant_expiry() -> None:
    decision = check_authority(
        _grant(),
        _check(
            is_compensation=True,
            original_grant=_original_grant(expires_at_tick=0),
            current_tick=5,
        ),
    )

    assert decision.disposition is AuthorityDisposition.ALLOW
    assert decision.reason is AuthorityReason.REVALIDATED
    assert decision.evidence["compensation_claimed"] is True
    assert decision.evidence["compensation_authorized"] is True


def test_compensation_still_requires_a_live_current_grant() -> None:
    decision = check_authority(
        _grant(),
        _check(is_compensation=True, original_grant=_original_grant(), current_tick=13),
    )

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.AUTH_EXPIRED
    assert decision.evidence["compensation_authorized"] is True


def test_original_grant_without_compensation_claim_is_invalid() -> None:
    with pytest.raises(ValueError, match="compensation is claimed"):
        _check(is_compensation=False, original_grant=_original_grant())


def test_read_only_cannot_claim_compensation() -> None:
    with pytest.raises(ValueError, match="read_only"):
        _check(CheckKind.READ_ONLY, is_compensation=True)
    with pytest.raises(ValueError):
        _check(
            CheckKind.READ_ONLY,
            is_compensation=True,
            original_grant=_original_grant(),
        )


def test_non_expiry_defect_outranks_expiry_for_passive_checks() -> None:
    scoped = check_authority(
        _grant(allowed_parameters={**_PARAMETERS, "title": "Something else"}),
        _check(CheckKind.PASSIVE_PRE_DISPATCH, current_tick=13),
    )
    assert scoped.disposition is AuthorityDisposition.VIOLATION
    assert scoped.reason is AuthorityReason.PARAMETERS_MISMATCH

    repaired = check_authority(
        _grant(), _check(CheckKind.PASSIVE_PRE_DISPATCH, current_tick=13)
    )
    assert repaired.disposition is AuthorityDisposition.SAFE_STOP
    assert repaired.reason is AuthorityReason.AUTH_EXPIRED


def test_passive_cardinality_at_cap_is_a_violation_not_a_safe_stop() -> None:
    decision = check_authority(
        _grant(max_effects=1),
        _check(CheckKind.PASSIVE_PRE_DISPATCH, committed_effect_count=1),
    )

    assert decision.disposition is AuthorityDisposition.VIOLATION
    assert decision.reason is AuthorityReason.CARDINALITY_EXCEEDED


def _all_defects() -> dict[str, bool]:
    return {
        "identity": True,
        "authority": True,
        "subject": True,
        "service": True,
        "operation": True,
        "digest": True,
        "parameters": True,
        "compensation": True,
        "cardinality": True,
        "expiry": True,
    }


def _build_case(defects: dict[str, bool]) -> tuple[AuthorityGrant, AuthorityCheck]:
    intent = _intent(
        service="dummy_email" if defects["service"] else "dummy_github",
        operation="delete_repo" if defects["operation"] else "create_issue",
    )
    true_digest = canonical_digest(intent)
    candidate = OperationIdentity(
        action_id="action-create-issue",
        operation_key="op-sel001",
        intent_digest=_WRONG_DIGEST if defects["digest"] else true_digest,
        authority_id="auth-wrong" if defects["authority"] else "auth-create-issue",
    )
    confirmed = (
        replace(candidate, action_id="action-thief")
        if defects["identity"]
        else candidate
    )
    grant = _grant(
        semantic_intent_digest=_WRONG_DIGEST if defects["digest"] else true_digest,
        allowed_parameters=(
            {**_PARAMETERS, "title": "Something else"}
            if defects["parameters"]
            else _PARAMETERS
        ),
    )
    request = _check(
        CheckKind.PRE_DISPATCH_WRITE,
        candidate=candidate,
        confirmed=confirmed,
        subject_id="intruder" if defects["subject"] else "reconcile-first",
        intent=intent,
        current_tick=13 if defects["expiry"] else 5,
        committed_effect_count=1 if defects["cardinality"] else 0,
        is_compensation=True,
        original_grant=None if defects["compensation"] else _original_grant(),
    )
    return grant, request


def test_multi_defect_reason_precedence_via_progressive_repair() -> None:
    defects = _all_defects()
    repairs = (
        ("identity", AuthorityReason.IDENTITY_MISMATCH),
        ("authority", AuthorityReason.AUTHORITY_ID_MISMATCH),
        ("subject", AuthorityReason.SUBJECT_MISMATCH),
        ("service", AuthorityReason.SERVICE_MISMATCH),
        ("operation", AuthorityReason.OPERATION_MISMATCH),
        ("digest", AuthorityReason.INTENT_DIGEST_MISMATCH),
        ("parameters", AuthorityReason.PARAMETERS_MISMATCH),
        ("compensation", AuthorityReason.COMPENSATION_NOT_AUTHORIZED),
        ("cardinality", AuthorityReason.CARDINALITY_EXCEEDED),
        ("expiry", AuthorityReason.AUTH_EXPIRED),
    )

    for knob, expected_reason in repairs:
        grant, request = _build_case(defects)
        decision = check_authority(grant, request)
        assert decision.disposition is AuthorityDisposition.VIOLATION
        assert decision.reason is expected_reason
        assert decision.target is OperationState.VIOLATION
        defects[knob] = False

    grant, request = _build_case(defects)
    repaired = check_authority(grant, request)
    assert repaired.disposition is AuthorityDisposition.ALLOW
    assert repaired.reason is AuthorityReason.REVALIDATED
    assert (repaired.target, repaired.cause) == (None, None)


def test_all_defect_evidence_still_records_every_boolean() -> None:
    grant, request = _build_case(_all_defects())
    decision = check_authority(grant, request)

    assert decision.reason is AuthorityReason.IDENTITY_MISMATCH
    for key in (
        "identity_confirmed",
        "authority_id_match",
        "subject_match",
        "service_match",
        "operation_match",
        "intent_digest_match",
        "parameters_match",
        "tick_valid",
        "cardinality_valid",
    ):
        assert decision.evidence[key] is False
    assert decision.evidence["compensation_claimed"] is True
    assert decision.evidence["compensation_authorized"] is False


def test_evidence_is_flat_sanitized_and_exactly_whitelisted() -> None:
    decision = check_authority(_grant(), _check(CheckKind.AUTHORIZE))

    assert type(decision.evidence) is FrozenMap
    assert tuple(sorted(decision.evidence)) == _EXPECTED_EVIDENCE_KEYS
    for value in decision.evidence.values():
        assert value is None or type(value) in {bool, int, str}
    assert decision.evidence["check_kind"] == "authorize"
    assert type(decision.evidence["check_kind"]) is str
    assert type(decision.evidence["disposition"]) is str
    assert type(decision.evidence["reason"]) is str
    # No raw parameter names or values may leak into evidence.
    rendered = repr(dict(decision.evidence))
    assert "Update docs" not in rendered
    assert "title" not in rendered


def test_identical_inputs_produce_identical_decisions_and_digests() -> None:
    first = check_authority(_grant(), _check(CheckKind.AUTHORIZE))
    second = check_authority(_grant(), _check(CheckKind.AUTHORIZE))

    assert first == second
    assert canonical_digest(first.evidence) == canonical_digest(second.evidence)


def test_decision_request_and_evidence_are_immutable() -> None:
    decision = check_authority(_grant(), _check())
    request = _check()

    with pytest.raises(FrozenInstanceError):
        decision.disposition = AuthorityDisposition.ALLOW  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        request.current_tick = 7  # type: ignore[misc]
    with pytest.raises(TypeError):
        cast(Any, decision.evidence)["reason"] = "AUTHORIZED"
    with pytest.raises(TypeError):
        cast(Any, decision.evidence).data = {}


def test_decision_transition_pair_and_matrix_rows_are_enforced() -> None:
    evidence = check_authority(_grant(), _check()).evidence

    with pytest.raises(ValueError, match="null together"):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.AUTHORIZED,
            evidence=evidence,
            target=OperationState.AUTHORIZED,
            cause=None,
        )
    with pytest.raises(ValueError, match="permitted pair"):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.AUTHORIZED,
            evidence=evidence,
            target=OperationState.SAFE_STOP,
            cause=TransitionCause.AUTHORITY_CONFIRMED,
        )
    with pytest.raises(ValueError, match="does not match"):
        AuthorityDecision(
            disposition=AuthorityDisposition.SAFE_STOP,
            reason=AuthorityReason.AUTH_EXPIRED,
            evidence=evidence,
        )
    with pytest.raises(ValueError, match="allow reason"):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.AUTH_EXPIRED,
            evidence=evidence,
        )
    with pytest.raises(ValueError, match="defect reason"):
        AuthorityDecision(
            disposition=AuthorityDisposition.VIOLATION,
            reason=AuthorityReason.REVALIDATED,
            evidence=evidence,
            target=OperationState.VIOLATION,
            cause=TransitionCause.INVARIANT_VIOLATION,
        )
    with pytest.raises(TypeError, match="FrozenMap"):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.REVALIDATED,
            evidence=cast(Any, dict(evidence)),
        )


def _valid_evidence_payload() -> dict[str, CanonicalValue]:
    return dict(check_authority(_grant(), _check()).evidence)


def test_directly_constructed_evidence_cannot_smuggle_extra_content() -> None:
    # Reviewer reproduction: FrozenMap's constructor validates nothing, so a
    # direct exact-type FrozenMap can carry extra keys, URL or sensitive
    # strings, and mutable nested values unless the decision rejects them.
    payload = _valid_evidence_payload()
    smuggled = FrozenMap(
        cast(
            Any,
            {
                **payload,
                "exfil": "https://example.invalid/leak",
                "aws_secret_access_key": "prose that must never ride along",
                "nested": {"mutable": ["list"]},
            },
        )
    )
    with pytest.raises(ValueError, match="exactly"):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.REVALIDATED,
            evidence=cast(Any, smuggled),
        )

    non_string_key = FrozenMap(cast(Any, {**payload, 5: True}))
    with pytest.raises(ValueError, match="exactly"):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.REVALIDATED,
            evidence=cast(Any, non_string_key),
        )

    missing = dict(payload)
    missing.pop("tick_valid")
    with pytest.raises(ValueError, match="exactly"):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.REVALIDATED,
            evidence=cast(Any, FrozenMap(cast(Any, missing))),
        )


@pytest.mark.parametrize(
    ("key", "value", "expected_error"),
    [
        ("action_id", "action-ok followed by free prose", ValidationError),
        ("grant_authority_id", "not-an-authority-id", ValidationError),
        ("candidate_intent_digest", "sha256:" + "Z" * 64, ValidationError),
        ("reason", "PERFECTLY_SAFE_PROSE", ValueError),
        ("check_kind", "https://example.invalid/callback", ValueError),
    ],
    ids=["action_prose", "authority_shape", "digest_case", "reason_vocab", "kind_url"],
)
def test_allowed_evidence_keys_reject_value_smuggling(
    key: str,
    value: str,
    expected_error: type[Exception],
) -> None:
    payload = _valid_evidence_payload()
    payload[key] = value
    with pytest.raises(expected_error):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.REVALIDATED,
            evidence=cast(Any, FrozenMap(cast(Any, payload))),
        )


@pytest.mark.parametrize(
    ("key", "value", "expected_error"),
    [
        ("parameters_match", {"nested": ["mutable"]}, TypeError),
        ("checked_tick", True, TypeError),
        ("expires_at_tick", -1, ValueError),
        ("max_effects", 0, ValueError),
        ("compensation_authorized", "yes", TypeError),
    ],
    ids=["nested_shape", "bool_tick", "negative_tick", "zero_cap", "str_flag"],
)
def test_evidence_values_reject_mutable_or_invalid_shapes(
    key: str,
    value: object,
    expected_error: type[Exception],
) -> None:
    payload = _valid_evidence_payload()
    payload[key] = cast(Any, value)
    with pytest.raises(expected_error):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.REVALIDATED,
            evidence=cast(Any, FrozenMap(cast(Any, payload))),
        )


def test_evidence_disposition_and_reason_must_match_the_decision() -> None:
    evidence = check_authority(_grant(), _check()).evidence
    with pytest.raises(ValueError, match="reason must match the decision"):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.READ_ONLY_ALLOWED,
            evidence=evidence,
        )

    forged = FrozenMap(cast(Any, {**dict(evidence), "disposition": "SAFE_STOP"}))
    with pytest.raises(ValueError, match="disposition must match the decision"):
        AuthorityDecision(
            disposition=AuthorityDisposition.ALLOW,
            reason=AuthorityReason.REVALIDATED,
            evidence=cast(Any, forged),
        )


def test_decision_revalidates_and_replaces_untrusted_evidence() -> None:
    original = check_authority(_grant(), _check())
    manual = FrozenMap(cast(Any, dict(original.evidence)))

    accepted = AuthorityDecision(
        disposition=original.disposition,
        reason=original.reason,
        evidence=cast(Any, manual),
        target=original.target,
        cause=original.cause,
    )

    assert accepted == original
    assert type(accepted.evidence) is FrozenMap
    assert accepted.evidence is not manual
    for value in accepted.evidence.values():
        assert value is None or type(value) in {bool, int, str}


def test_mappings_never_masquerade_as_contracts() -> None:
    grant = _grant()
    request = _check()

    with pytest.raises(TypeError):
        check_authority(cast(Any, grant.model_dump()), request)
    with pytest.raises(TypeError):
        check_authority(grant, cast(Any, {"kind": "authorize"}))
    with pytest.raises(TypeError):
        _check(cast(Any, "authorize"))
    with pytest.raises(TypeError):
        _check(candidate=cast(Any, {"action_id": "action-create-issue"}))
    with pytest.raises(TypeError):
        _check(confirmed=cast(Any, asdict(_IDENTITY)))
    with pytest.raises(TypeError):
        _check(intent=cast(Any, _INTENT.model_dump()))
    with pytest.raises(TypeError):
        _check(
            is_compensation=True,
            original_grant=cast(Any, _original_grant().model_dump()),
        )


@pytest.mark.filterwarnings("error")
def test_bypass_constructed_grant_fails_closed() -> None:
    forged = AuthorityGrant.model_construct(
        authority_id="auth-create-issue",
        subject_id="reconcile-first",
        service="dummy_github",
        operation="create_issue",
        semantic_intent_digest=_INTENT_DIGEST,
        allowed_parameters={"weight": 1.5},
        expires_at_tick=12,
        max_effects=0,
    )

    with pytest.raises(ValidationError):
        check_authority(forged, _check())


@pytest.mark.filterwarnings("error")
def test_tampered_intent_fails_closed() -> None:
    forged = SemanticIntent.model_construct(
        service="dummy_github",
        operation="create_issue",
        parameters={"weight": 1.5},
    )

    with pytest.raises(ValidationError):
        check_authority(_grant(), _check(intent=forged))


def test_tampered_identity_fails_closed() -> None:
    forged = object.__new__(OperationIdentity)
    object.__setattr__(forged, "action_id", "ACTION-FORGED")
    object.__setattr__(forged, "operation_key", "op-sel001")
    object.__setattr__(forged, "intent_digest", _INTENT_DIGEST)
    object.__setattr__(forged, "authority_id", "auth-create-issue")

    with pytest.raises(ValidationError):
        check_authority(_grant(), _check(candidate=forged))


def test_tampered_request_scalars_fail_closed() -> None:
    negative_tick = _check()
    object.__setattr__(negative_tick, "current_tick", -3)
    with pytest.raises(ValueError, match="current_tick"):
        check_authority(_grant(), negative_tick)

    fake_flag = _check()
    object.__setattr__(fake_flag, "is_compensation", "yes")
    with pytest.raises(TypeError, match="is_compensation"):
        check_authority(_grant(), fake_flag)
