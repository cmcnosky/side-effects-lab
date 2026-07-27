"""Unit tests for the canonical per-action operation state machine."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from side_effects_lab.canonical import canonical_digest
from side_effects_lab.state_machine import (
    NORMATIVE_TRANSITIONS,
    InvalidTransitionError,
    OperationIdentity,
    OperationState,
    OperationStateMachine,
    TransitionCause,
    TransitionEvidence,
    TransitionRecord,
)

_INTENT_DIGEST = "sha256:" + "1" * 64
_IDENTITY = OperationIdentity(
    action_id="action-create-issue",
    operation_key="op-sel001",
    intent_digest=_INTENT_DIGEST,
    authority_id="auth-create-issue",
)


class _DeceptiveString(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


def _evidence(
    cause: TransitionCause,
    *,
    evidence_id: str | None = None,
    **overrides: bool,
) -> TransitionEvidence:
    facts: dict[str, bool] = {
        "fresh": False,
        "authoritative": False,
        "exact_identity": False,
        "postcondition_verified": False,
        "cardinality_valid": False,
    }
    if cause in {
        TransitionCause.EXACT_EFFECT_FOUND,
        TransitionCause.CONCLUSIVE_ABSENCE,
    }:
        facts.update(fresh=True, authoritative=True, exact_identity=True)
    if cause is TransitionCause.FRESH_POSTCONDITION:
        facts.update(
            fresh=True,
            authoritative=True,
            postcondition_verified=True,
            cardinality_valid=True,
        )
    if cause is TransitionCause.RECONCILIATION_INCONCLUSIVE:
        facts.update(exact_identity=True)
    facts.update(overrides)
    return TransitionEvidence(
        evidence_id=evidence_id or f"evidence-{cause.value.replace('_', '-')}",
        cause=cause,
        **facts,
    )


def _transition(
    machine: OperationStateMachine,
    target: OperationState,
    cause: TransitionCause,
    *,
    identity: OperationIdentity = _IDENTITY,
    attempt_id: str | None = None,
    evidence_id: str | None = None,
    **facts: bool,
) -> TransitionRecord:
    return machine.transition(
        target,
        evidence=_evidence(cause, evidence_id=evidence_id, **facts),
        identity=identity,
        attempt_id=cast(Any, attempt_id),
    )


def _authorized(machine: OperationStateMachine) -> None:
    _transition(
        machine,
        OperationState.AUTHORIZED,
        TransitionCause.AUTHORITY_CONFIRMED,
    )


def _prepared(machine: OperationStateMachine) -> None:
    _authorized(machine)
    _transition(
        machine,
        OperationState.PREPARED,
        TransitionCause.PREPARATION_DURABLE,
    )


def _in_flight(machine: OperationStateMachine) -> None:
    _prepared(machine)
    _transition(
        machine,
        OperationState.IN_FLIGHT,
        TransitionCause.ATTEMPT_DELIVERED,
        attempt_id="attempt-1",
    )


def _indeterminate(machine: OperationStateMachine) -> None:
    _in_flight(machine)
    _transition(
        machine,
        OperationState.INDETERMINATE,
        TransitionCause.AMBIGUOUS_OUTCOME,
    )


def _reconciling(machine: OperationStateMachine) -> None:
    _indeterminate(machine)
    _transition(
        machine,
        OperationState.RECONCILING,
        TransitionCause.RECONCILIATION_STARTED,
    )


def _retryable(machine: OperationStateMachine) -> None:
    _in_flight(machine)
    _transition(
        machine,
        OperationState.RETRYABLE,
        TransitionCause.PRECOMMIT_REJECTION,
    )


def _verifying(machine: OperationStateMachine) -> None:
    _in_flight(machine)
    _transition(
        machine,
        OperationState.VERIFYING,
        TransitionCause.SUCCESS_RECEIPT,
    )


_SOURCE_BUILDERS: dict[OperationState, Callable[[OperationStateMachine], None]] = {
    OperationState.PROPOSED: lambda machine: None,
    OperationState.AUTHORIZED: _authorized,
    OperationState.PREPARED: _prepared,
    OperationState.IN_FLIGHT: _in_flight,
    OperationState.INDETERMINATE: _indeterminate,
    OperationState.RECONCILING: _reconciling,
    OperationState.RETRYABLE: _retryable,
    OperationState.VERIFYING: _verifying,
}


def test_operation_state_values_are_exactly_normative() -> None:
    assert [state.value for state in OperationState] == [
        "PROPOSED",
        "AUTHORIZED",
        "PREPARED",
        "IN_FLIGHT",
        "INDETERMINATE",
        "RECONCILING",
        "RETRYABLE",
        "VERIFYING",
        "COMPLETE",
        "SAFE_STOP",
        "VIOLATION",
    ]


def test_normative_transition_set_is_exact() -> None:
    expected = {
        (OperationState.PROPOSED, OperationState.AUTHORIZED),
        (OperationState.PROPOSED, OperationState.VIOLATION),
        (OperationState.AUTHORIZED, OperationState.PREPARED),
        (OperationState.AUTHORIZED, OperationState.SAFE_STOP),
        (OperationState.PREPARED, OperationState.IN_FLIGHT),
        (OperationState.IN_FLIGHT, OperationState.VERIFYING),
        (OperationState.IN_FLIGHT, OperationState.RETRYABLE),
        (OperationState.IN_FLIGHT, OperationState.INDETERMINATE),
        (OperationState.INDETERMINATE, OperationState.RECONCILING),
        (OperationState.RECONCILING, OperationState.VERIFYING),
        (OperationState.RECONCILING, OperationState.RETRYABLE),
        (OperationState.RECONCILING, OperationState.SAFE_STOP),
        (OperationState.RETRYABLE, OperationState.IN_FLIGHT),
        (OperationState.RETRYABLE, OperationState.SAFE_STOP),
        (OperationState.VERIFYING, OperationState.COMPLETE),
        (OperationState.VERIFYING, OperationState.RECONCILING),
        (OperationState.VERIFYING, OperationState.SAFE_STOP),
    }
    assert set(NORMATIVE_TRANSITIONS) == expected

    with pytest.raises(TypeError):
        NORMATIVE_TRANSITIONS[  # type: ignore[index]
            (OperationState.COMPLETE, OperationState.PROPOSED)
        ] = TransitionCause.INVARIANT_VIOLATION


@pytest.mark.parametrize(
    ("source", "target", "cause"),
    [
        (source, target, cause)
        for (source, target), cause in NORMATIVE_TRANSITIONS.items()
    ],
)
def test_every_normative_transition_executes(
    source: OperationState,
    target: OperationState,
    cause: TransitionCause,
) -> None:
    machine = OperationStateMachine(_IDENTITY)
    _SOURCE_BUILDERS[source](machine)
    attempt_id = (
        f"attempt-{len(machine.attempt_ids) + 1}"
        if target is OperationState.IN_FLIGHT
        else None
    )

    record = _transition(machine, target, cause, attempt_id=attempt_id)

    assert record.source_state is source
    assert record.attempted_state is target
    assert record.resulting_state is target
    assert record.violation_reason == (
        "invariant violation reported" if target is OperationState.VIOLATION else None
    )
    assert machine.state is target


def test_identity_and_evidence_values_are_frozen_and_strict() -> None:
    evidence = _evidence(TransitionCause.AUTHORITY_CONFIRMED)

    with pytest.raises(FrozenInstanceError):
        evidence.fresh = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _IDENTITY.action_id = "action-other"  # type: ignore[misc]
    with pytest.raises(ValueError, match="evidence_id"):
        TransitionEvidence("Evidence:external", TransitionCause.AUTHORITY_CONFIRMED)
    with pytest.raises(TypeError, match="cause"):
        TransitionEvidence("evidence-1", cast(Any, "authority_confirmed"))
    with pytest.raises(TypeError, match="fresh"):
        TransitionEvidence(
            "evidence-1",
            TransitionCause.AUTHORITY_CONFIRMED,
            fresh=cast(Any, 1),
        )
    with pytest.raises(ValidationError):
        OperationIdentity(
            action_id=cast(Any, "wrong-prefix"),
            operation_key="op-sel001",
            intent_digest=_INTENT_DIGEST,
            authority_id="auth-create-issue",
        )


def test_direct_completion_is_a_recorded_violation_with_context() -> None:
    machine = OperationStateMachine(_IDENTITY)

    with pytest.raises(InvalidTransitionError) as exc_info:
        _transition(
            machine,
            OperationState.COMPLETE,
            TransitionCause.FRESH_POSTCONDITION,
            evidence_id="evidence-direct-complete",
        )

    assert machine.state is OperationState.VIOLATION
    assert len(machine.history) == 1
    record = exc_info.value.record
    assert record.source_state is OperationState.PROPOSED
    assert record.attempted_state is OperationState.COMPLETE
    assert record.resulting_state is OperationState.VIOLATION
    assert "transition is not allowed" in cast(str, record.violation_reason)
    assert "state=PROPOSED" in str(exc_info.value)
    assert "attempted=COMPLETE" in str(exc_info.value)
    assert "evidence_id=evidence-direct-complete" in str(exc_info.value)


@pytest.mark.parametrize(
    ("target", "cause", "attempt_id"),
    [
        (
            OperationState.IN_FLIGHT,
            TransitionCause.REDISPATCH_AUTHORIZED,
            "attempt-2",
        ),
        (
            OperationState.SAFE_STOP,
            TransitionCause.SAFE_STOP_SELECTED,
            None,
        ),
    ],
)
def test_indeterminate_cannot_skip_reconciliation(
    target: OperationState,
    cause: TransitionCause,
    attempt_id: str | None,
) -> None:
    machine = OperationStateMachine(_IDENTITY)
    _indeterminate(machine)

    with pytest.raises(InvalidTransitionError, match="state=INDETERMINATE"):
        _transition(machine, target, cause, attempt_id=attempt_id)

    assert machine.state is OperationState.VIOLATION


def test_wrong_evidence_cause_reaches_violation() -> None:
    machine = OperationStateMachine(_IDENTITY)

    with pytest.raises(InvalidTransitionError, match="does not match required"):
        _transition(
            machine,
            OperationState.AUTHORIZED,
            TransitionCause.AMBIGUOUS_OUTCOME,
        )

    assert machine.state is OperationState.VIOLATION


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("action_id", "action-other"),
        ("operation_key", "op-other"),
        ("intent_digest", "sha256:" + "2" * 64),
        ("authority_id", "auth-other"),
    ],
)
def test_changed_identity_reaches_violation(
    field_name: str,
    replacement: str,
) -> None:
    machine = OperationStateMachine(_IDENTITY)
    changed = replace(_IDENTITY, **{field_name: replacement})

    with pytest.raises(InvalidTransitionError) as exc_info:
        _transition(
            machine,
            OperationState.AUTHORIZED,
            TransitionCause.AUTHORITY_CONFIRMED,
            identity=changed,
        )

    assert machine.state is OperationState.VIOLATION
    assert f"immutable identity changed: {field_name}" in str(exc_info.value)


def test_identity_aliases_are_normalized_before_immutable_comparison() -> None:
    machine = OperationStateMachine(_IDENTITY)
    deceptive = OperationIdentity(
        action_id=cast(Any, _DeceptiveString("action-other")),
        operation_key="op-sel001",
        intent_digest=_INTENT_DIGEST,
        authority_id="auth-create-issue",
    )

    assert type(deceptive.action_id) is str
    with pytest.raises(InvalidTransitionError, match="action_id"):
        _transition(
            machine,
            OperationState.AUTHORIZED,
            TransitionCause.AUTHORITY_CONFIRMED,
            identity=deceptive,
        )

    assert machine.state is OperationState.VIOLATION


@pytest.mark.parametrize(
    ("attempt_id", "reason"),
    [
        (None, "requires a new attempt_id"),
        ("not-an-attempt", "attempt_id is invalid"),
    ],
)
def test_entering_in_flight_requires_a_valid_attempt_id(
    attempt_id: str | None,
    reason: str,
) -> None:
    machine = OperationStateMachine(_IDENTITY)
    _prepared(machine)

    with pytest.raises(InvalidTransitionError, match=reason):
        _transition(
            machine,
            OperationState.IN_FLIGHT,
            TransitionCause.ATTEMPT_DELIVERED,
            attempt_id=attempt_id,
        )

    assert machine.state is OperationState.VIOLATION


@pytest.mark.parametrize(
    "malformed_attempt_id",
    [{"bad": "id"}, ["attempt-1"], True, 1],
    ids=["mapping", "list", "boolean", "integer"],
)
def test_malformed_attempt_never_enters_canonical_violation_history(
    malformed_attempt_id: object,
) -> None:
    machine = OperationStateMachine(_IDENTITY)
    _prepared(machine)

    with pytest.raises(InvalidTransitionError) as exc_info:
        machine.transition(
            OperationState.IN_FLIGHT,
            evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED),
            identity=_IDENTITY,
            attempt_id=cast(Any, malformed_attempt_id),
        )

    assert exc_info.value.record.attempt_id is None
    assert machine.history[-1].canonical_value()["attempt_id"] is None


def test_changed_identity_path_also_sanitizes_a_malformed_attempt() -> None:
    machine = OperationStateMachine(_IDENTITY)
    changed = replace(_IDENTITY, action_id="action-other")

    with pytest.raises(InvalidTransitionError) as exc_info:
        machine.transition(
            OperationState.AUTHORIZED,
            evidence=_evidence(TransitionCause.AUTHORITY_CONFIRMED),
            identity=changed,
            attempt_id=cast(Any, {"bad": "id"}),
        )

    assert exc_info.value.record.attempt_id is None
    assert machine.history[-1].canonical_value()["attempt_id"] is None


def test_attempt_id_is_rejected_on_non_dispatch_transition() -> None:
    machine = OperationStateMachine(_IDENTITY)

    with pytest.raises(InvalidTransitionError, match="only valid when entering"):
        _transition(
            machine,
            OperationState.AUTHORIZED,
            TransitionCause.AUTHORITY_CONFIRMED,
            attempt_id="attempt-1",
        )

    assert machine.state is OperationState.VIOLATION


def test_retry_requires_a_new_attempt_under_the_same_action() -> None:
    machine = OperationStateMachine(_IDENTITY)
    _retryable(machine)

    record = _transition(
        machine,
        OperationState.IN_FLIGHT,
        TransitionCause.REDISPATCH_AUTHORIZED,
        attempt_id="attempt-2",
    )

    assert machine.identity is _IDENTITY
    assert machine.attempt_ids == ("attempt-1", "attempt-2")
    assert record.attempt_id == "attempt-2"


def test_retry_reusing_an_attempt_id_reaches_violation() -> None:
    machine = OperationStateMachine(_IDENTITY)
    _retryable(machine)

    with pytest.raises(InvalidTransitionError, match="already used"):
        _transition(
            machine,
            OperationState.IN_FLIGHT,
            TransitionCause.REDISPATCH_AUTHORIZED,
            attempt_id="attempt-1",
        )

    assert machine.state is OperationState.VIOLATION
    assert machine.attempt_ids == ("attempt-1",)


@pytest.mark.parametrize(
    "missing_fact",
    ["fresh", "authoritative", "postcondition_verified", "cardinality_valid"],
)
def test_completion_requires_every_fresh_verification_fact(
    missing_fact: str,
) -> None:
    machine = OperationStateMachine(_IDENTITY)
    _verifying(machine)
    evidence = replace(
        _evidence(TransitionCause.FRESH_POSTCONDITION),
        **cast(Any, {missing_fact: False}),
    )

    with pytest.raises(InvalidTransitionError) as exc_info:
        machine.transition(
            OperationState.COMPLETE,
            evidence=evidence,
            identity=_IDENTITY,
        )

    assert machine.state is OperationState.VIOLATION
    assert f"completion evidence lacks {missing_fact}" in str(exc_info.value)


@pytest.mark.parametrize("missing_fact", ["fresh", "authoritative", "exact_identity"])
def test_incomplete_absence_never_reaches_retryable(missing_fact: str) -> None:
    machine = OperationStateMachine(_IDENTITY)
    _reconciling(machine)
    evidence = replace(
        _evidence(TransitionCause.CONCLUSIVE_ABSENCE),
        **cast(Any, {missing_fact: False}),
    )

    with pytest.raises(InvalidTransitionError) as exc_info:
        machine.transition(
            OperationState.RETRYABLE,
            evidence=evidence,
            identity=_IDENTITY,
        )

    assert machine.state is OperationState.VIOLATION
    assert f"reconciliation evidence lacks {missing_fact}" in str(exc_info.value)


def test_stale_effect_observation_never_reaches_verifying() -> None:
    machine = OperationStateMachine(_IDENTITY)
    _reconciling(machine)

    with pytest.raises(InvalidTransitionError, match="lacks fresh"):
        _transition(
            machine,
            OperationState.VERIFYING,
            TransitionCause.EXACT_EFFECT_FOUND,
            fresh=False,
        )

    assert machine.state is OperationState.VIOLATION


def test_reconciliation_cannot_stop_before_exact_identity_lookup() -> None:
    machine = OperationStateMachine(_IDENTITY)
    _reconciling(machine)

    with pytest.raises(InvalidTransitionError, match="attempted exact-identity"):
        _transition(
            machine,
            OperationState.SAFE_STOP,
            TransitionCause.RECONCILIATION_INCONCLUSIVE,
            exact_identity=False,
        )

    assert machine.state is OperationState.VIOLATION


def test_explicit_invariant_violation_is_recorded_from_active_state() -> None:
    machine = OperationStateMachine(_IDENTITY)
    _in_flight(machine)

    record = _transition(
        machine,
        OperationState.VIOLATION,
        TransitionCause.INVARIANT_VIOLATION,
        evidence_id="evidence-excess-effect",
    )

    assert record.source_state is OperationState.IN_FLIGHT
    assert record.resulting_state is OperationState.VIOLATION
    assert record.violation_reason == "invariant violation reported"
    assert machine.state is OperationState.VIOLATION


def test_violation_is_terminal_without_mutating_history_again() -> None:
    machine = OperationStateMachine(_IDENTITY)
    _transition(
        machine,
        OperationState.VIOLATION,
        TransitionCause.INVARIANT_VIOLATION,
        evidence_id="evidence-first-violation",
    )
    original_history = machine.history

    with pytest.raises(InvalidTransitionError) as exc_info:
        _transition(
            machine,
            OperationState.AUTHORIZED,
            TransitionCause.AUTHORITY_CONFIRMED,
            evidence_id="evidence-after-violation",
        )

    assert machine.state is OperationState.VIOLATION
    assert machine.history == original_history
    assert "state=VIOLATION" in str(exc_info.value)
    assert "evidence_id=evidence-after-violation" in str(exc_info.value)


def test_terminal_violation_error_sanitizes_a_malformed_attempt() -> None:
    machine = OperationStateMachine(_IDENTITY)
    _transition(
        machine,
        OperationState.VIOLATION,
        TransitionCause.INVARIANT_VIOLATION,
    )
    original_history = machine.history

    with pytest.raises(InvalidTransitionError) as exc_info:
        machine.transition(
            OperationState.AUTHORIZED,
            evidence=_evidence(TransitionCause.AUTHORITY_CONFIRMED),
            identity=_IDENTITY,
            attempt_id=cast(Any, {"bad": "id"}),
        )

    assert exc_info.value.record.attempt_id is None
    assert machine.history == original_history


@pytest.mark.parametrize(
    "terminal", [OperationState.COMPLETE, OperationState.SAFE_STOP]
)
def test_forbidden_action_after_safe_terminal_state_becomes_violation(
    terminal: OperationState,
) -> None:
    machine = OperationStateMachine(_IDENTITY)
    if terminal is OperationState.COMPLETE:
        _verifying(machine)
        _transition(
            machine,
            OperationState.COMPLETE,
            TransitionCause.FRESH_POSTCONDITION,
        )
    else:
        _authorized(machine)
        _transition(
            machine,
            OperationState.SAFE_STOP,
            TransitionCause.SAFE_STOP_SELECTED,
        )

    with pytest.raises(InvalidTransitionError):
        _transition(
            machine,
            OperationState.AUTHORIZED,
            TransitionCause.AUTHORITY_CONFIRMED,
            evidence_id="evidence-after-safe-terminal",
        )

    assert machine.state is OperationState.VIOLATION


def test_history_views_are_immutable_and_records_are_canonical() -> None:
    machine = OperationStateMachine(_IDENTITY)
    _in_flight(machine)
    history = machine.history
    attempts = machine.attempt_ids

    assert isinstance(history, tuple)
    assert isinstance(attempts, tuple)
    with pytest.raises(FrozenInstanceError):
        history[0].source_state = OperationState.VIOLATION  # type: ignore[misc]
    assert history[0].canonical_value() == {
        "attempt_id": None,
        "attempted_state": "AUTHORIZED",
        "cause": "authority_confirmed",
        "evidence_id": "evidence-authority-confirmed",
        "resulting_state": "AUTHORIZED",
        "source_state": "PROPOSED",
        "violation_reason": None,
    }


def test_identical_legal_sequences_have_identical_history_digests() -> None:
    def run() -> tuple[OperationState, str]:
        machine = OperationStateMachine(_IDENTITY)
        _reconciling(machine)
        _transition(
            machine,
            OperationState.VERIFYING,
            TransitionCause.EXACT_EFFECT_FOUND,
        )
        _transition(
            machine,
            OperationState.COMPLETE,
            TransitionCause.FRESH_POSTCONDITION,
        )
        normalized = [record.canonical_value() for record in machine.history]
        return machine.state, canonical_digest(normalized)

    assert run() == run()
