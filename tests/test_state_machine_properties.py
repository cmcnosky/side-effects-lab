"""Property tests for the canonical operation state machine.

A test-only reference model mirrors the frozen ``OperationStateMachine``:
true commit count, authority validity, the ordered tuple of claim
classifications, and the ordered command trace. True side effects change
only through explicit, replayable ``effect_committed`` model commands;
success receipts and exact-effect discovery are observations and never
mutate the modeled effect count. These facts exercise only the
state-machine boundary defined in ``src/side_effects_lab/state_machine.py``;
they do not implement T007 authority enforcement, T012 oracle verdicts, or
any service behavior.
"""

from dataclasses import dataclass, fields, replace
from itertools import combinations, pairwise, product
from re import fullmatch
from typing import Literal

import pytest
from hypothesis import Phase, currently_in_test_context, note, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

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

_DETERMINISTIC_SETTINGS = settings(
    max_examples=200,
    stateful_step_count=30,
    deadline=None,
    derandomize=True,
    database=None,
    phases=(Phase.generate, Phase.shrink),
    print_blob=True,
)

_INTENT_DIGEST = "sha256:" + "0" * 64
_BASE_IDENTITY = OperationIdentity(
    action_id="action-base",
    operation_key="op-base",
    intent_digest=_INTENT_DIGEST,
    authority_id="auth-base",
)

_MAX_EFFECTS = 1
_MALFORMED_ATTEMPT_IDS: tuple[str, ...] = (
    "ATTEMPT-1",
    "attempt",
    "not-an-attempt",
    "",
)

_REFERENCE_TRANSITIONS: dict[tuple[OperationState, OperationState], TransitionCause] = {
    (OperationState.PROPOSED, OperationState.AUTHORIZED): (
        TransitionCause.AUTHORITY_CONFIRMED
    ),
    (OperationState.PROPOSED, OperationState.VIOLATION): (
        TransitionCause.INVARIANT_VIOLATION
    ),
    (OperationState.AUTHORIZED, OperationState.PREPARED): (
        TransitionCause.PREPARATION_DURABLE
    ),
    (OperationState.AUTHORIZED, OperationState.SAFE_STOP): (
        TransitionCause.SAFE_STOP_SELECTED
    ),
    (OperationState.PREPARED, OperationState.IN_FLIGHT): (
        TransitionCause.ATTEMPT_DELIVERED
    ),
    (OperationState.IN_FLIGHT, OperationState.VERIFYING): (
        TransitionCause.SUCCESS_RECEIPT
    ),
    (OperationState.IN_FLIGHT, OperationState.RETRYABLE): (
        TransitionCause.PRECOMMIT_REJECTION
    ),
    (OperationState.IN_FLIGHT, OperationState.INDETERMINATE): (
        TransitionCause.AMBIGUOUS_OUTCOME
    ),
    (OperationState.INDETERMINATE, OperationState.RECONCILING): (
        TransitionCause.RECONCILIATION_STARTED
    ),
    (OperationState.RECONCILING, OperationState.VERIFYING): (
        TransitionCause.EXACT_EFFECT_FOUND
    ),
    (OperationState.RECONCILING, OperationState.RETRYABLE): (
        TransitionCause.CONCLUSIVE_ABSENCE
    ),
    (OperationState.RECONCILING, OperationState.SAFE_STOP): (
        TransitionCause.RECONCILIATION_INCONCLUSIVE
    ),
    (OperationState.RETRYABLE, OperationState.IN_FLIGHT): (
        TransitionCause.REDISPATCH_AUTHORIZED
    ),
    (OperationState.RETRYABLE, OperationState.SAFE_STOP): (
        TransitionCause.SAFE_STOP_SELECTED
    ),
    (OperationState.VERIFYING, OperationState.COMPLETE): (
        TransitionCause.FRESH_POSTCONDITION
    ),
    (OperationState.VERIFYING, OperationState.RECONCILING): (
        TransitionCause.VERIFICATION_INCOMPLETE
    ),
    (OperationState.VERIFYING, OperationState.SAFE_STOP): (
        TransitionCause.POSTCONDITION_FAILED
    ),
}


def _evidence(
    cause: TransitionCause,
    evidence_id: str,
    *,
    fresh: bool = False,
    authoritative: bool = False,
    exact_identity: bool = False,
    postcondition_verified: bool = False,
    cardinality_valid: bool = False,
) -> TransitionEvidence:
    return TransitionEvidence(
        evidence_id=evidence_id,
        cause=cause,
        fresh=fresh,
        authoritative=authoritative,
        exact_identity=exact_identity,
        postcondition_verified=postcondition_verified,
        cardinality_valid=cardinality_valid,
    )


def _build_to(
    machine: OperationStateMachine, state: OperationState, *, attempt_id: str
) -> None:
    """Drive a fresh machine to ``state`` using only legal transitions."""
    if state is OperationState.PROPOSED:
        return
    machine.transition(
        OperationState.AUTHORIZED,
        evidence=_evidence(TransitionCause.AUTHORITY_CONFIRMED, "e-authorized"),
        identity=_BASE_IDENTITY,
    )
    if state is OperationState.AUTHORIZED:
        return
    if state is OperationState.SAFE_STOP:
        machine.transition(
            OperationState.SAFE_STOP,
            evidence=_evidence(TransitionCause.SAFE_STOP_SELECTED, "e-safe-stop"),
            identity=_BASE_IDENTITY,
        )
        return
    machine.transition(
        OperationState.PREPARED,
        evidence=_evidence(TransitionCause.PREPARATION_DURABLE, "e-prepared"),
        identity=_BASE_IDENTITY,
    )
    if state is OperationState.PREPARED:
        return
    machine.transition(
        OperationState.IN_FLIGHT,
        evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED, "e-dispatched"),
        identity=_BASE_IDENTITY,
        attempt_id=attempt_id,
    )
    if state is OperationState.IN_FLIGHT:
        return
    if state is OperationState.RETRYABLE:
        machine.transition(
            OperationState.RETRYABLE,
            evidence=_evidence(TransitionCause.PRECOMMIT_REJECTION, "e-rejected"),
            identity=_BASE_IDENTITY,
        )
        return
    if state is OperationState.VERIFYING or state is OperationState.COMPLETE:
        machine.transition(
            OperationState.VERIFYING,
            evidence=_evidence(TransitionCause.SUCCESS_RECEIPT, "e-succeeded"),
            identity=_BASE_IDENTITY,
        )
        if state is OperationState.VERIFYING:
            return
        machine.transition(
            OperationState.COMPLETE,
            evidence=_evidence(
                TransitionCause.FRESH_POSTCONDITION,
                "e-completed",
                fresh=True,
                authoritative=True,
                postcondition_verified=True,
                cardinality_valid=True,
            ),
            identity=_BASE_IDENTITY,
        )
        return
    machine.transition(
        OperationState.INDETERMINATE,
        evidence=_evidence(TransitionCause.AMBIGUOUS_OUTCOME, "e-ambiguous"),
        identity=_BASE_IDENTITY,
    )
    if state is OperationState.INDETERMINATE:
        return
    machine.transition(
        OperationState.RECONCILING,
        evidence=_evidence(TransitionCause.RECONCILIATION_STARTED, "e-reconciling"),
        identity=_BASE_IDENTITY,
    )
    if state is OperationState.RECONCILING:
        return
    raise AssertionError(f"no builder path defined for {state.value}")


_REACHABLE_SOURCES: tuple[OperationState, ...] = (
    OperationState.PROPOSED,
    OperationState.AUTHORIZED,
    OperationState.PREPARED,
    OperationState.IN_FLIGHT,
    OperationState.INDETERMINATE,
    OperationState.RECONCILING,
    OperationState.RETRYABLE,
    OperationState.VERIFYING,
    OperationState.COMPLETE,
    OperationState.SAFE_STOP,
)

# Ordered tuple: strategy inputs must never come from sets or unordered
# mappings. Enum iteration order is definition order, so this is stable.
_ILLEGAL_PAIRS: tuple[tuple[OperationState, OperationState], ...] = tuple(
    (source, target)
    for source in _REACHABLE_SOURCES
    for target in OperationState
    if target is not OperationState.VIOLATION
    and (source, target) not in _REFERENCE_TRANSITIONS
)


_WRONG_CAUSE_CASES: tuple[
    tuple[OperationState, OperationState, TransitionCause], ...
] = tuple(
    (source, target, candidate)
    for (source, target), required in _REFERENCE_TRANSITIONS.items()
    for candidate in TransitionCause
    if candidate is not required
)


# ---------------------------------------------------------------------------
# Explicit boolean-combination coverage for reconciliation and completion.
# ---------------------------------------------------------------------------


def test_production_transition_map_matches_frozen_reference() -> None:
    assert dict(NORMATIVE_TRANSITIONS) == _REFERENCE_TRANSITIONS


@pytest.mark.parametrize(
    ("fresh", "authoritative", "exact_identity"),
    list(product([False, True], repeat=3)),
)
def test_reconciliation_absence_covers_every_boolean_combination(
    fresh: bool, authoritative: bool, exact_identity: bool
) -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.RECONCILING, attempt_id="attempt-recon")
    evidence = _evidence(
        TransitionCause.CONCLUSIVE_ABSENCE,
        "e-absence",
        fresh=fresh,
        authoritative=authoritative,
        exact_identity=exact_identity,
    )
    should_succeed = fresh and authoritative and exact_identity
    if should_succeed:
        record = machine.transition(
            OperationState.RETRYABLE, evidence=evidence, identity=_BASE_IDENTITY
        )
        assert record.resulting_state is OperationState.RETRYABLE
    else:
        with pytest.raises(InvalidTransitionError):
            machine.transition(
                OperationState.RETRYABLE, evidence=evidence, identity=_BASE_IDENTITY
            )
        assert machine.state is OperationState.VIOLATION


@pytest.mark.parametrize(
    ("fresh", "authoritative", "exact_identity"),
    list(product([False, True], repeat=3)),
)
def test_reconciliation_exact_effect_covers_every_boolean_combination(
    fresh: bool, authoritative: bool, exact_identity: bool
) -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.RECONCILING, attempt_id="attempt-recon")
    evidence = _evidence(
        TransitionCause.EXACT_EFFECT_FOUND,
        "e-exact",
        fresh=fresh,
        authoritative=authoritative,
        exact_identity=exact_identity,
    )
    should_succeed = fresh and authoritative and exact_identity
    if should_succeed:
        record = machine.transition(
            OperationState.VERIFYING, evidence=evidence, identity=_BASE_IDENTITY
        )
        assert record.resulting_state is OperationState.VERIFYING
    else:
        with pytest.raises(InvalidTransitionError):
            machine.transition(
                OperationState.VERIFYING, evidence=evidence, identity=_BASE_IDENTITY
            )
        assert machine.state is OperationState.VIOLATION


@pytest.mark.parametrize(
    ("fresh", "authoritative", "exact_identity"),
    list(product([False, True], repeat=3)),
)
def test_reconciliation_safe_stop_covers_every_boolean_combination(
    fresh: bool, authoritative: bool, exact_identity: bool
) -> None:
    # Safe stop from RECONCILING requires only an attempted exact-identity
    # lookup; freshness and authority must be mechanically irrelevant.
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.RECONCILING, attempt_id="attempt-recon")
    evidence = _evidence(
        TransitionCause.RECONCILIATION_INCONCLUSIVE,
        "e-inconclusive",
        fresh=fresh,
        authoritative=authoritative,
        exact_identity=exact_identity,
    )
    if exact_identity:
        record = machine.transition(
            OperationState.SAFE_STOP, evidence=evidence, identity=_BASE_IDENTITY
        )
        assert record.resulting_state is OperationState.SAFE_STOP
    else:
        with pytest.raises(InvalidTransitionError):
            machine.transition(
                OperationState.SAFE_STOP, evidence=evidence, identity=_BASE_IDENTITY
            )
        assert machine.state is OperationState.VIOLATION


@pytest.mark.parametrize(
    ("fresh", "authoritative", "postcondition_verified", "cardinality_valid"),
    list(product([False, True], repeat=4)),
)
def test_completion_covers_every_boolean_combination(
    fresh: bool,
    authoritative: bool,
    postcondition_verified: bool,
    cardinality_valid: bool,
) -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.VERIFYING, attempt_id="attempt-verify")
    evidence = _evidence(
        TransitionCause.FRESH_POSTCONDITION,
        "e-complete",
        fresh=fresh,
        authoritative=authoritative,
        postcondition_verified=postcondition_verified,
        cardinality_valid=cardinality_valid,
    )
    should_succeed = (
        fresh and authoritative and postcondition_verified and cardinality_valid
    )
    if should_succeed:
        record = machine.transition(
            OperationState.COMPLETE, evidence=evidence, identity=_BASE_IDENTITY
        )
        assert record.resulting_state is OperationState.COMPLETE
    else:
        with pytest.raises(InvalidTransitionError):
            machine.transition(
                OperationState.COMPLETE, evidence=evidence, identity=_BASE_IDENTITY
            )
        assert machine.state is OperationState.VIOLATION


# ---------------------------------------------------------------------------
# Identity mutation: single fields alone and in every combination (invariant 6).
# ---------------------------------------------------------------------------

_IDENTITY_FIELDS: tuple[str, ...] = (
    "action_id",
    "operation_key",
    "intent_digest",
    "authority_id",
)
_ALT_VALUES: dict[str, str] = {
    "action_id": "action-alt-one",
    "operation_key": "op-alt-one",
    "intent_digest": "sha256:" + "1" * 64,
    "authority_id": "auth-alt-one",
}
_IDENTITY_MUTATION_COMBINATIONS: tuple[tuple[str, ...], ...] = tuple(
    combo
    for size in range(1, len(_IDENTITY_FIELDS) + 1)
    for combo in combinations(_IDENTITY_FIELDS, size)
)


@pytest.mark.parametrize(
    "changed_fields",
    _IDENTITY_MUTATION_COMBINATIONS,
)
def test_any_identity_field_mutation_reaches_violation(
    changed_fields: tuple[str, ...],
) -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    overrides = {field: _ALT_VALUES[field] for field in changed_fields}
    mutated = replace(_BASE_IDENTITY, **overrides)

    with pytest.raises(InvalidTransitionError) as exc_info:
        machine.transition(
            OperationState.AUTHORIZED,
            evidence=_evidence(TransitionCause.AUTHORITY_CONFIRMED, "e-mutated"),
            identity=mutated,
        )

    assert machine.state is OperationState.VIOLATION
    for field in changed_fields:
        assert field in str(exc_info.value)


# ---------------------------------------------------------------------------
# Attempt-ID generation: missing, reused, malformed, non-dispatch (invariant 2, 7).
# ---------------------------------------------------------------------------


def test_missing_attempt_id_reaches_violation() -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.PREPARED, attempt_id="unused")
    with pytest.raises(InvalidTransitionError, match="requires a new attempt_id"):
        machine.transition(
            OperationState.IN_FLIGHT,
            evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED, "e-missing"),
            identity=_BASE_IDENTITY,
            attempt_id=None,
        )
    assert machine.state is OperationState.VIOLATION


def test_reused_attempt_id_reaches_violation() -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.RETRYABLE, attempt_id="attempt-first")
    with pytest.raises(InvalidTransitionError, match="already used"):
        machine.transition(
            OperationState.IN_FLIGHT,
            evidence=_evidence(TransitionCause.REDISPATCH_AUTHORIZED, "e-reused"),
            identity=_BASE_IDENTITY,
            attempt_id="attempt-first",
        )
    assert machine.state is OperationState.VIOLATION


@pytest.mark.parametrize("malformed", _MALFORMED_ATTEMPT_IDS)
def test_malformed_attempt_id_reaches_violation(malformed: str) -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.PREPARED, attempt_id="unused")
    with pytest.raises(InvalidTransitionError, match="attempt_id is invalid"):
        machine.transition(
            OperationState.IN_FLIGHT,
            evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED, "e-malformed"),
            identity=_BASE_IDENTITY,
            attempt_id=malformed,
        )
    assert machine.state is OperationState.VIOLATION


def test_non_dispatch_attempt_id_reaches_violation() -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    with pytest.raises(InvalidTransitionError, match="only valid when entering"):
        machine.transition(
            OperationState.AUTHORIZED,
            evidence=_evidence(TransitionCause.AUTHORITY_CONFIRMED, "e-nondispatch"),
            identity=_BASE_IDENTITY,
            attempt_id="attempt-stray",
        )
    assert machine.state is OperationState.VIOLATION


# ---------------------------------------------------------------------------
# Illegal target/cause combinations from every reachable source (invariant 3).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("source", "target"), _ILLEGAL_PAIRS)
def test_illegal_target_from_reachable_state_reaches_violation(
    source: OperationState, target: OperationState
) -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, source, attempt_id="attempt-illegal")
    fallback_cause = next(iter(TransitionCause))
    cause = NORMATIVE_TRANSITIONS.get((source, target), fallback_cause)
    with pytest.raises(InvalidTransitionError):
        machine.transition(
            target,
            evidence=_evidence(cause, "e-illegal"),
            identity=_BASE_IDENTITY,
            attempt_id=(
                "attempt-illegal-2" if target is OperationState.IN_FLIGHT else None
            ),
        )
    assert machine.state is OperationState.VIOLATION


@pytest.mark.parametrize(("source", "target", "cause"), _WRONG_CAUSE_CASES)
def test_wrong_cause_for_legal_edge_reaches_violation(
    source: OperationState,
    target: OperationState,
    cause: TransitionCause,
) -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, source, attempt_id="attempt-wrong-cause")

    with pytest.raises(InvalidTransitionError):
        machine.transition(
            target,
            evidence=_evidence(cause, "e-wrong-cause"),
            identity=_BASE_IDENTITY,
            attempt_id=(
                "attempt-wrong-cause-2" if target is OperationState.IN_FLIGHT else None
            ),
        )

    assert machine.state is OperationState.VIOLATION


def test_direct_redispatch_from_indeterminate_always_violates() -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.INDETERMINATE, attempt_id="attempt-indet")
    with pytest.raises(InvalidTransitionError, match="state=INDETERMINATE"):
        machine.transition(
            OperationState.IN_FLIGHT,
            evidence=_evidence(TransitionCause.REDISPATCH_AUTHORIZED, "e-skip"),
            identity=_BASE_IDENTITY,
            attempt_id="attempt-skip",
        )
    assert machine.state is OperationState.VIOLATION


# ---------------------------------------------------------------------------
# Required explicit deterministic traces.
# ---------------------------------------------------------------------------


def test_commit_response_loss_stale_absence_attempted_retry() -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.RECONCILING, attempt_id="attempt-1")
    with pytest.raises(InvalidTransitionError, match="lacks fresh"):
        machine.transition(
            OperationState.RETRYABLE,
            evidence=_evidence(
                TransitionCause.CONCLUSIVE_ABSENCE,
                "e-stale-absence",
                fresh=False,
                authoritative=True,
                exact_identity=True,
            ),
            identity=_BASE_IDENTITY,
        )
    assert machine.state is OperationState.VIOLATION


def test_precommit_rejection_same_identity_retry_with_new_attempt() -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.RETRYABLE, attempt_id="attempt-1")

    record = machine.transition(
        OperationState.IN_FLIGHT,
        evidence=_evidence(TransitionCause.REDISPATCH_AUTHORIZED, "e-retry"),
        identity=_BASE_IDENTITY,
        attempt_id="attempt-2",
    )

    assert machine.identity == _BASE_IDENTITY
    assert machine.attempt_ids == ("attempt-1", "attempt-2")
    assert record.resulting_state is OperationState.IN_FLIGHT


def test_commit_response_loss_exact_lookup_verification_completion() -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.RECONCILING, attempt_id="attempt-1")
    machine.transition(
        OperationState.VERIFYING,
        evidence=_evidence(
            TransitionCause.EXACT_EFFECT_FOUND,
            "e-exact",
            fresh=True,
            authoritative=True,
            exact_identity=True,
        ),
        identity=_BASE_IDENTITY,
    )
    record = machine.transition(
        OperationState.COMPLETE,
        evidence=_evidence(
            TransitionCause.FRESH_POSTCONDITION,
            "e-complete",
            fresh=True,
            authoritative=True,
            postcondition_verified=True,
            cardinality_valid=True,
        ),
        identity=_BASE_IDENTITY,
    )
    assert machine.state is OperationState.COMPLETE
    assert record.resulting_state is OperationState.COMPLETE


def test_expiry_before_retry() -> None:
    expired_machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(expired_machine, OperationState.RETRYABLE, attempt_id="attempt-1")
    record = expired_machine.transition(
        OperationState.VIOLATION,
        evidence=_evidence(TransitionCause.INVARIANT_VIOLATION, "e-authority-expired"),
        identity=_BASE_IDENTITY,
    )
    assert record.source_state is OperationState.RETRYABLE
    assert record.resulting_state is OperationState.VIOLATION
    assert expired_machine.state is OperationState.VIOLATION

    safe_stop_machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(safe_stop_machine, OperationState.RETRYABLE, attempt_id="attempt-1")
    safe_record = safe_stop_machine.transition(
        OperationState.SAFE_STOP,
        evidence=_evidence(TransitionCause.SAFE_STOP_SELECTED, "e-safe-stop"),
        identity=_BASE_IDENTITY,
    )
    assert safe_record.resulting_state is OperationState.SAFE_STOP


def test_premature_completion_claim_is_not_accepted() -> None:
    machine = OperationStateMachine(_BASE_IDENTITY)
    _build_to(machine, OperationState.VERIFYING, attempt_id="attempt-1")
    assert machine.state is not OperationState.COMPLETE
    assert _claim_accepted(machine.state, "complete") is False


def test_duplicate_modeled_commit_cannot_pass() -> None:
    # Both true effects are explicit replayable effect_committed commands in
    # the unified replay model: one committed by the in-flight attempt and a
    # distinct second commit from duplicate delivery. Nothing is inferred
    # from the receipt, and no raw counter is mutated outside the model.
    lane = _DeepTraceLane("duplicate-example")
    _authorize_prepare_dispatch(lane, attempt_id="attempt-duplicate-example-1")
    lane.model("effect_committed")
    assert isinstance(
        lane.run(OperationState.VERIFYING, TransitionCause.SUCCESS_RECEIPT),
        TransitionRecord,
    )
    lane.model("effect_committed")
    _complete(lane)
    lane.model("claim_complete")

    assert lane.machine.state is OperationState.COMPLETE
    assert lane.true_effect_count == 2
    assert lane.true_effect_count > _MAX_EFFECTS
    snapshot = lane.assert_unified_replay()
    assert snapshot.true_effect_count == 2
    assert (
        _is_passing_trace(
            state=lane.machine.state,
            honest_claim=True,
            true_effect_count=lane.true_effect_count,
        )
        is False
    )


def _claim_accepted(
    state: OperationState, status: Literal["complete", "blocked"]
) -> bool:
    if status == "complete":
        return state is OperationState.COMPLETE
    return state is OperationState.SAFE_STOP


def _is_passing_trace(
    *, state: OperationState, honest_claim: bool, true_effect_count: int
) -> bool:
    return (
        state in (OperationState.COMPLETE, OperationState.SAFE_STOP)
        and honest_claim
        and true_effect_count <= _MAX_EFFECTS
    )


# ---------------------------------------------------------------------------
# Stateful reference-model machine.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Command:
    """One canonical, replayable transition attempt."""

    step: int
    target: str
    cause: str
    evidence_id: str
    fresh: bool
    authoritative: bool
    exact_identity: bool
    postcondition_verified: bool
    cardinality_valid: bool
    attempt_id: str | None
    identity_overrides: tuple[tuple[str, str], ...]
    expected_success: bool


type ModelCommandKind = Literal[
    "authority_expired",
    "effect_committed",
    "claim_complete",
    "claim_blocked",
]


@dataclass(frozen=True, slots=True)
class ModelCommand:
    """One replayable update to the test-only reference model."""

    step: int
    kind: ModelCommandKind


type TraceEntry = Command | ModelCommand
type ClaimRecord = tuple[Literal["complete", "blocked"], bool, OperationState]


_RECONCILE_FACT_TUPLES: tuple[tuple[bool, bool, bool], ...] = tuple(
    (fresh, authoritative, exact_identity)
    for fresh in (False, True)
    for authoritative in (False, True)
    for exact_identity in (False, True)
)
_COMPLETION_FACT_TUPLES: tuple[tuple[bool, bool, bool, bool], ...] = tuple(
    (fresh, authoritative, postcondition_verified, cardinality_valid)
    for fresh in (False, True)
    for authoritative in (False, True)
    for postcondition_verified in (False, True)
    for cardinality_valid in (False, True)
)


def _reference_accepts(
    source: OperationState,
    expected_attempt_ids: list[str],
    target: OperationState,
    cause: TransitionCause,
    *,
    fresh: bool,
    authoritative: bool,
    exact_identity: bool,
    postcondition_verified: bool,
    cardinality_valid: bool,
    attempt_id: str | None,
    identity: OperationIdentity,
) -> bool:
    if source is OperationState.VIOLATION or identity != _BASE_IDENTITY:
        return False

    if target is OperationState.IN_FLIGHT:
        if (
            type(attempt_id) is not str
            or len(attempt_id) > 128
            or fullmatch(r"attempt-[a-z0-9][a-z0-9-]*", attempt_id) is None
            or attempt_id in expected_attempt_ids
        ):
            return False
    elif attempt_id is not None:
        return False

    if (
        target is OperationState.VIOLATION
        and cause is TransitionCause.INVARIANT_VIOLATION
    ):
        return True

    if _REFERENCE_TRANSITIONS.get((source, target)) is not cause:
        return False

    if source is OperationState.RECONCILING and target in {
        OperationState.VERIFYING,
        OperationState.RETRYABLE,
    }:
        return fresh and authoritative and exact_identity
    if source is OperationState.RECONCILING and target is OperationState.SAFE_STOP:
        return exact_identity
    if source is OperationState.VERIFYING and target is OperationState.COMPLETE:
        return fresh and authoritative and postcondition_verified and cardinality_valid
    return True


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    """Canonical outcome of replaying transition and model commands together."""

    state: OperationState
    attempt_ids: tuple[str, ...]
    true_effect_count: int
    authority_expired: bool
    claim_classifications: tuple[ClaimRecord, ...]
    history_digest: str


def _replay_trace(trace: list[TraceEntry]) -> ReplaySnapshot:
    replay = OperationStateMachine(_BASE_IDENTITY)
    replay_effect_count = 0
    replay_authority_expired = False
    replay_claim_classifications: tuple[ClaimRecord, ...] = ()

    for command in trace:
        if isinstance(command, ModelCommand):
            if command.kind == "authority_expired":
                replay_authority_expired = True
            elif command.kind == "effect_committed":
                replay_effect_count += 1
            elif command.kind == "claim_complete":
                replay_claim_classifications += (
                    (
                        "complete",
                        _claim_accepted(replay.state, "complete"),
                        replay.state,
                    ),
                )
            else:
                replay_claim_classifications += (
                    (
                        "blocked",
                        _claim_accepted(replay.state, "blocked"),
                        replay.state,
                    ),
                )
            continue

        identity = _BASE_IDENTITY
        if command.identity_overrides:
            identity = replace(_BASE_IDENTITY, **dict(command.identity_overrides))
        evidence = _evidence(
            TransitionCause(command.cause),
            command.evidence_id,
            fresh=command.fresh,
            authoritative=command.authoritative,
            exact_identity=command.exact_identity,
            postcondition_verified=command.postcondition_verified,
            cardinality_valid=command.cardinality_valid,
        )
        succeeded = False
        try:
            replay.transition(
                OperationState(command.target),
                evidence=evidence,
                identity=identity,
                attempt_id=command.attempt_id,
            )
        except InvalidTransitionError:
            pass
        else:
            succeeded = True
        assert succeeded is command.expected_success

    history_digest = canonical_digest(
        [record.canonical_value() for record in replay.history]
    )
    # Replay derives the effect count only from explicit commit commands;
    # replayed receipts and discovery leave it untouched.
    explicit_commits = sum(
        1
        for command in trace
        if isinstance(command, ModelCommand) and command.kind == "effect_committed"
    )
    assert replay_effect_count == explicit_commits
    return ReplaySnapshot(
        state=replay.state,
        attempt_ids=replay.attempt_ids,
        true_effect_count=replay_effect_count,
        authority_expired=replay_authority_expired,
        claim_classifications=replay_claim_classifications,
        history_digest=history_digest,
    )


def _note_command(label: str, command: TraceEntry) -> None:
    # note() requires an active Hypothesis context; the deterministic
    # example tests drive lanes outside one.
    if currently_in_test_context():
        note(f"deep lane {label}: {command}")


class _DeepTraceLane:
    """Independent generated lane with the same predictor and replay vocabulary."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.machine = OperationStateMachine(_BASE_IDENTITY)
        self.expected_state = OperationState.PROPOSED
        self.expected_attempt_ids: list[str] = []
        self.trace: list[TraceEntry] = []
        self.step = 0
        self.true_effect_count = 0
        self.authority_expired = False
        self.claim_classifications: tuple[ClaimRecord, ...] = ()

    def run(
        self,
        target: OperationState,
        cause: TransitionCause,
        *,
        fresh: bool = False,
        authoritative: bool = False,
        exact_identity: bool = False,
        postcondition_verified: bool = False,
        cardinality_valid: bool = False,
        attempt_id: str | None = None,
    ) -> TransitionRecord | InvalidTransitionError:
        self.step += 1
        expected_success = _reference_accepts(
            self.expected_state,
            self.expected_attempt_ids,
            target,
            cause,
            fresh=fresh,
            authoritative=authoritative,
            exact_identity=exact_identity,
            postcondition_verified=postcondition_verified,
            cardinality_valid=cardinality_valid,
            attempt_id=attempt_id,
            identity=_BASE_IDENTITY,
        )
        command = Command(
            step=self.step,
            target=target.value,
            cause=cause.value,
            evidence_id=(f"e-{self.label}-{self.step}-{cause.value.replace('_', '-')}"),
            fresh=fresh,
            authoritative=authoritative,
            exact_identity=exact_identity,
            postcondition_verified=postcondition_verified,
            cardinality_valid=cardinality_valid,
            attempt_id=attempt_id,
            identity_overrides=(),
            expected_success=expected_success,
        )
        self.trace.append(command)
        _note_command(self.label, command)

        # Transitions consume observations; only an explicit effect_committed
        # model command may change the modeled true effect count.
        effect_count_before = self.true_effect_count
        try:
            record = self.machine.transition(
                target,
                evidence=_evidence(
                    cause,
                    command.evidence_id,
                    fresh=fresh,
                    authoritative=authoritative,
                    exact_identity=exact_identity,
                    postcondition_verified=postcondition_verified,
                    cardinality_valid=cardinality_valid,
                ),
                identity=_BASE_IDENTITY,
                attempt_id=attempt_id,
            )
        except InvalidTransitionError as error:
            assert not expected_success
            assert self.true_effect_count == effect_count_before
            self.expected_state = OperationState.VIOLATION
            return error

        assert expected_success
        assert self.true_effect_count == effect_count_before
        self.expected_state = target
        if target is OperationState.IN_FLIGHT:
            assert attempt_id is not None
            self.expected_attempt_ids.append(attempt_id)
        return record

    def model(self, kind: ModelCommandKind) -> None:
        self.step += 1
        command = ModelCommand(step=self.step, kind=kind)
        self.trace.append(command)
        _note_command(self.label, command)
        if kind == "authority_expired":
            self.authority_expired = True
        elif kind == "effect_committed":
            self.true_effect_count += 1
        elif kind == "claim_complete":
            self.claim_classifications += (
                (
                    "complete",
                    _claim_accepted(self.machine.state, "complete"),
                    self.machine.state,
                ),
            )
        else:
            self.claim_classifications += (
                (
                    "blocked",
                    _claim_accepted(self.machine.state, "blocked"),
                    self.machine.state,
                ),
            )

    def assert_unified_replay(self) -> ReplaySnapshot:
        # Note the trace before asserting so a replay failure still prints
        # the exact command sequence needed to reproduce it.
        if currently_in_test_context():
            note(f"deep lane {self.label} trace: {self.trace!r}")
        snapshot = _replay_trace(self.trace)
        original_digest = canonical_digest(
            [record.canonical_value() for record in self.machine.history]
        )
        explicit_commits = sum(
            1
            for command in self.trace
            if isinstance(command, ModelCommand) and command.kind == "effect_committed"
        )
        assert snapshot.state is self.machine.state is self.expected_state
        assert snapshot.attempt_ids == self.machine.attempt_ids
        assert snapshot.attempt_ids == tuple(self.expected_attempt_ids)
        assert snapshot.true_effect_count == self.true_effect_count
        assert snapshot.true_effect_count == explicit_commits
        assert snapshot.authority_expired is self.authority_expired
        assert snapshot.claim_classifications == self.claim_classifications
        assert snapshot.history_digest == original_digest
        return snapshot


def _authorize_prepare_dispatch(lane: _DeepTraceLane, *, attempt_id: str) -> None:
    assert isinstance(
        lane.run(OperationState.AUTHORIZED, TransitionCause.AUTHORITY_CONFIRMED),
        TransitionRecord,
    )
    assert isinstance(
        lane.run(OperationState.PREPARED, TransitionCause.PREPARATION_DURABLE),
        TransitionRecord,
    )
    assert isinstance(
        lane.run(
            OperationState.IN_FLIGHT,
            TransitionCause.ATTEMPT_DELIVERED,
            attempt_id=attempt_id,
        ),
        TransitionRecord,
    )


def _complete(lane: _DeepTraceLane) -> None:
    assert isinstance(
        lane.run(
            OperationState.COMPLETE,
            TransitionCause.FRESH_POSTCONDITION,
            fresh=True,
            authoritative=True,
            postcondition_verified=True,
            cardinality_valid=True,
        ),
        TransitionRecord,
    )


def _build_deep_recovery_lanes() -> tuple[_DeepTraceLane, ...]:
    success = _DeepTraceLane("success")
    _authorize_prepare_dispatch(success, attempt_id="attempt-success-1")
    # The true effect commits while the attempt is in flight; the later
    # receipt only observes it.
    success.model("effect_committed")
    assert isinstance(
        success.run(OperationState.VERIFYING, TransitionCause.SUCCESS_RECEIPT),
        TransitionRecord,
    )
    _complete(success)
    success.model("claim_complete")

    commit_loss_exact = _DeepTraceLane("commit-loss-exact")
    _authorize_prepare_dispatch(commit_loss_exact, attempt_id="attempt-exact-1")
    # The effect commits before the response is lost; discovery later
    # observes the same single effect.
    commit_loss_exact.model("effect_committed")
    assert isinstance(
        commit_loss_exact.run(
            OperationState.INDETERMINATE, TransitionCause.AMBIGUOUS_OUTCOME
        ),
        TransitionRecord,
    )
    assert isinstance(
        commit_loss_exact.run(
            OperationState.RECONCILING,
            TransitionCause.RECONCILIATION_STARTED,
        ),
        TransitionRecord,
    )
    assert isinstance(
        commit_loss_exact.run(
            OperationState.VERIFYING,
            TransitionCause.EXACT_EFFECT_FOUND,
            fresh=True,
            authoritative=True,
            exact_identity=True,
        ),
        TransitionRecord,
    )
    _complete(commit_loss_exact)

    absence_retry = _DeepTraceLane("absence-retry")
    _authorize_prepare_dispatch(absence_retry, attempt_id="attempt-absence-1")
    assert isinstance(
        absence_retry.run(
            OperationState.INDETERMINATE, TransitionCause.AMBIGUOUS_OUTCOME
        ),
        TransitionRecord,
    )
    assert isinstance(
        absence_retry.run(
            OperationState.RECONCILING,
            TransitionCause.RECONCILIATION_STARTED,
        ),
        TransitionRecord,
    )
    assert isinstance(
        absence_retry.run(
            OperationState.RETRYABLE,
            TransitionCause.CONCLUSIVE_ABSENCE,
            fresh=True,
            authoritative=True,
            exact_identity=True,
        ),
        TransitionRecord,
    )
    assert isinstance(
        absence_retry.run(
            OperationState.IN_FLIGHT,
            TransitionCause.REDISPATCH_AUTHORIZED,
            attempt_id="attempt-absence-2",
        ),
        TransitionRecord,
    )

    commit_loss_stale_absence = _DeepTraceLane("commit-loss-stale-absence")
    _authorize_prepare_dispatch(commit_loss_stale_absence, attempt_id="attempt-stale-1")
    # The effect committed before the response was lost, which is exactly
    # why the stale absence read below must not authorize a retry.
    commit_loss_stale_absence.model("effect_committed")
    assert isinstance(
        commit_loss_stale_absence.run(
            OperationState.INDETERMINATE, TransitionCause.AMBIGUOUS_OUTCOME
        ),
        TransitionRecord,
    )
    assert isinstance(
        commit_loss_stale_absence.run(
            OperationState.RECONCILING,
            TransitionCause.RECONCILIATION_STARTED,
        ),
        TransitionRecord,
    )
    assert isinstance(
        commit_loss_stale_absence.run(
            OperationState.RETRYABLE,
            TransitionCause.CONCLUSIVE_ABSENCE,
            fresh=False,
            authoritative=True,
            exact_identity=True,
        ),
        InvalidTransitionError,
    )

    rejection_retry = _DeepTraceLane("rejection-retry")
    _authorize_prepare_dispatch(rejection_retry, attempt_id="attempt-rejection-1")
    assert isinstance(
        rejection_retry.run(
            OperationState.RETRYABLE, TransitionCause.PRECOMMIT_REJECTION
        ),
        TransitionRecord,
    )
    assert isinstance(
        rejection_retry.run(
            OperationState.IN_FLIGHT,
            TransitionCause.REDISPATCH_AUTHORIZED,
            attempt_id="attempt-rejection-2",
        ),
        TransitionRecord,
    )

    verification_loop = _DeepTraceLane("verification-loop")
    _authorize_prepare_dispatch(verification_loop, attempt_id="attempt-loop-1")
    verification_loop.model("effect_committed")
    assert isinstance(
        verification_loop.run(
            OperationState.VERIFYING, TransitionCause.SUCCESS_RECEIPT
        ),
        TransitionRecord,
    )
    assert isinstance(
        verification_loop.run(
            OperationState.RECONCILING,
            TransitionCause.VERIFICATION_INCOMPLETE,
        ),
        TransitionRecord,
    )
    assert isinstance(
        verification_loop.run(
            OperationState.VERIFYING,
            TransitionCause.EXACT_EFFECT_FOUND,
            fresh=True,
            authoritative=True,
            exact_identity=True,
        ),
        TransitionRecord,
    )
    _complete(verification_loop)

    expiry = _DeepTraceLane("expiry")
    _authorize_prepare_dispatch(expiry, attempt_id="attempt-expiry-1")
    assert isinstance(
        expiry.run(OperationState.RETRYABLE, TransitionCause.PRECOMMIT_REJECTION),
        TransitionRecord,
    )
    expiry.model("authority_expired")
    assert isinstance(
        expiry.run(OperationState.VIOLATION, TransitionCause.INVARIANT_VIOLATION),
        TransitionRecord,
    )

    duplicate = _DeepTraceLane("duplicate")
    _authorize_prepare_dispatch(duplicate, attempt_id="attempt-duplicate-1")
    duplicate.model("effect_committed")
    assert isinstance(
        duplicate.run(OperationState.VERIFYING, TransitionCause.SUCCESS_RECEIPT),
        TransitionRecord,
    )
    # Duplicate delivery commits a distinct second effect; it is a second
    # explicit commit command, never inferred from the earlier receipt.
    duplicate.model("effect_committed")
    _complete(duplicate)
    duplicate.model("claim_complete")

    missing_attempt = _DeepTraceLane("missing-attempt")
    assert isinstance(
        missing_attempt.run(
            OperationState.AUTHORIZED, TransitionCause.AUTHORITY_CONFIRMED
        ),
        TransitionRecord,
    )
    assert isinstance(
        missing_attempt.run(
            OperationState.PREPARED, TransitionCause.PREPARATION_DURABLE
        ),
        TransitionRecord,
    )
    assert isinstance(
        missing_attempt.run(
            OperationState.IN_FLIGHT,
            TransitionCause.ATTEMPT_DELIVERED,
        ),
        InvalidTransitionError,
    )

    reused_attempt = _DeepTraceLane("reused-attempt")
    _authorize_prepare_dispatch(reused_attempt, attempt_id="attempt-reused-1")
    assert isinstance(
        reused_attempt.run(
            OperationState.RETRYABLE, TransitionCause.PRECOMMIT_REJECTION
        ),
        TransitionRecord,
    )
    assert isinstance(
        reused_attempt.run(
            OperationState.IN_FLIGHT,
            TransitionCause.REDISPATCH_AUTHORIZED,
            attempt_id="attempt-reused-1",
        ),
        InvalidTransitionError,
    )

    return (
        success,
        commit_loss_exact,
        absence_retry,
        commit_loss_stale_absence,
        rejection_retry,
        verification_loop,
        expiry,
        duplicate,
        missing_attempt,
        reused_attempt,
    )


def _cause_trace(lane: _DeepTraceLane) -> tuple[str, ...]:
    return tuple(
        command.cause for command in lane.trace if isinstance(command, Command)
    )


def _effect_commit_steps(lane: _DeepTraceLane) -> tuple[int, ...]:
    return tuple(
        command.step
        for command in lane.trace
        if isinstance(command, ModelCommand) and command.kind == "effect_committed"
    )


def _first_cause_step(lane: _DeepTraceLane, cause: TransitionCause) -> int:
    for command in lane.trace:
        if isinstance(command, Command) and command.cause == cause.value:
            return command.step
    raise AssertionError(f"lane {lane.label} never attempted cause {cause.value}")


def _assert_deep_recovery_coverage(lanes: tuple[_DeepTraceLane, ...]) -> None:
    by_label = {lane.label: lane for lane in lanes}
    assert tuple(by_label) == (
        "success",
        "commit-loss-exact",
        "absence-retry",
        "commit-loss-stale-absence",
        "rejection-retry",
        "verification-loop",
        "expiry",
        "duplicate",
        "missing-attempt",
        "reused-attempt",
    )

    assert _cause_trace(by_label["success"])[-2:] == (
        TransitionCause.SUCCESS_RECEIPT.value,
        TransitionCause.FRESH_POSTCONDITION.value,
    )
    assert _cause_trace(by_label["commit-loss-exact"])[-4:] == (
        TransitionCause.AMBIGUOUS_OUTCOME.value,
        TransitionCause.RECONCILIATION_STARTED.value,
        TransitionCause.EXACT_EFFECT_FOUND.value,
        TransitionCause.FRESH_POSTCONDITION.value,
    )
    assert _cause_trace(by_label["absence-retry"])[-4:] == (
        TransitionCause.AMBIGUOUS_OUTCOME.value,
        TransitionCause.RECONCILIATION_STARTED.value,
        TransitionCause.CONCLUSIVE_ABSENCE.value,
        TransitionCause.REDISPATCH_AUTHORIZED.value,
    )
    stale_command = by_label["commit-loss-stale-absence"].trace[-1]
    assert isinstance(stale_command, Command)
    assert stale_command.cause == TransitionCause.CONCLUSIVE_ABSENCE.value
    assert stale_command.fresh is False
    assert stale_command.expected_success is False
    assert _cause_trace(by_label["rejection-retry"])[-2:] == (
        TransitionCause.PRECOMMIT_REJECTION.value,
        TransitionCause.REDISPATCH_AUTHORIZED.value,
    )
    assert TransitionCause.VERIFICATION_INCOMPLETE.value in _cause_trace(
        by_label["verification-loop"]
    )
    assert any(
        isinstance(command, ModelCommand) and command.kind == "authority_expired"
        for command in by_label["expiry"].trace
    )

    # Every commit is an explicit command ordered before the observation
    # that reports it; receipts and discovery never create commits.
    for label in ("success", "verification-loop"):
        commit_steps = _effect_commit_steps(by_label[label])
        assert len(commit_steps) == 1
        assert commit_steps[0] < _first_cause_step(
            by_label[label], TransitionCause.SUCCESS_RECEIPT
        )
    for label in ("commit-loss-exact", "commit-loss-stale-absence"):
        commit_steps = _effect_commit_steps(by_label[label])
        assert len(commit_steps) == 1
        assert commit_steps[0] < _first_cause_step(
            by_label[label], TransitionCause.AMBIGUOUS_OUTCOME
        )
    assert _effect_commit_steps(by_label["absence-retry"]) == ()
    assert _effect_commit_steps(by_label["rejection-retry"]) == ()

    duplicate_commits = _effect_commit_steps(by_label["duplicate"])
    duplicate_receipt = _first_cause_step(
        by_label["duplicate"], TransitionCause.SUCCESS_RECEIPT
    )
    assert len(duplicate_commits) == 2
    assert duplicate_commits[0] < duplicate_receipt < duplicate_commits[1]

    missing_command = by_label["missing-attempt"].trace[-1]
    assert isinstance(missing_command, Command)
    assert missing_command.attempt_id is None
    assert missing_command.expected_success is False
    reused_command = by_label["reused-attempt"].trace[-1]
    assert isinstance(reused_command, Command)
    assert reused_command.attempt_id == "attempt-reused-1"
    assert reused_command.expected_success is False

    expected_states = (
        OperationState.COMPLETE,
        OperationState.COMPLETE,
        OperationState.IN_FLIGHT,
        OperationState.VIOLATION,
        OperationState.IN_FLIGHT,
        OperationState.COMPLETE,
        OperationState.VIOLATION,
        OperationState.COMPLETE,
        OperationState.VIOLATION,
        OperationState.VIOLATION,
    )
    assert tuple(lane.machine.state for lane in lanes) == expected_states
    expected_effect_counts = (1, 1, 0, 1, 0, 1, 0, 2, 0, 0)
    assert tuple(lane.true_effect_count for lane in lanes) == expected_effect_counts

    assert by_label["success"].claim_classifications == (
        ("complete", True, OperationState.COMPLETE),
    )
    assert _is_passing_trace(
        state=by_label["success"].machine.state,
        honest_claim=True,
        true_effect_count=by_label["success"].true_effect_count,
    )
    assert by_label["duplicate"].claim_classifications == (
        ("complete", True, OperationState.COMPLETE),
    )
    assert not _is_passing_trace(
        state=by_label["duplicate"].machine.state,
        honest_claim=True,
        true_effect_count=by_label["duplicate"].true_effect_count,
    )


# ---------------------------------------------------------------------------
# Receipts and discovery are observations; only effect_committed commits.
# ---------------------------------------------------------------------------


def test_success_receipt_leaves_effect_count_unchanged() -> None:
    lane = _DeepTraceLane("receipt-observation")
    _authorize_prepare_dispatch(lane, attempt_id="attempt-observe-1")
    assert lane.true_effect_count == 0
    assert isinstance(
        lane.run(OperationState.VERIFYING, TransitionCause.SUCCESS_RECEIPT),
        TransitionRecord,
    )
    assert lane.true_effect_count == 0
    assert lane.assert_unified_replay().true_effect_count == 0


def test_exact_effect_discovery_leaves_effect_count_unchanged() -> None:
    lane = _DeepTraceLane("discovery-observation")
    _authorize_prepare_dispatch(lane, attempt_id="attempt-observe-2")
    lane.model("effect_committed")
    assert lane.true_effect_count == 1
    assert isinstance(
        lane.run(OperationState.INDETERMINATE, TransitionCause.AMBIGUOUS_OUTCOME),
        TransitionRecord,
    )
    assert isinstance(
        lane.run(OperationState.RECONCILING, TransitionCause.RECONCILIATION_STARTED),
        TransitionRecord,
    )
    assert isinstance(
        lane.run(
            OperationState.VERIFYING,
            TransitionCause.EXACT_EFFECT_FOUND,
            fresh=True,
            authoritative=True,
            exact_identity=True,
        ),
        TransitionRecord,
    )
    assert lane.true_effect_count == 1
    assert lane.assert_unified_replay().true_effect_count == 1


def test_replay_preserves_explicit_effect_count() -> None:
    lane = _DeepTraceLane("replay-count")
    _authorize_prepare_dispatch(lane, attempt_id="attempt-replay-1")
    lane.model("effect_committed")
    assert isinstance(
        lane.run(OperationState.VERIFYING, TransitionCause.SUCCESS_RECEIPT),
        TransitionRecord,
    )
    lane.model("effect_committed")
    _complete(lane)
    lane.model("claim_complete")

    assert lane.true_effect_count == 2
    snapshot = lane.assert_unified_replay()
    assert snapshot.true_effect_count == 2
    commit_steps = _effect_commit_steps(lane)
    assert len(commit_steps) == 2
    assert commit_steps[0] < commit_steps[1]
    assert snapshot.claim_classifications == (
        ("complete", True, OperationState.COMPLETE),
    )
    assert not _is_passing_trace(
        state=snapshot.state,
        honest_claim=True,
        true_effect_count=snapshot.true_effect_count,
    )


_DEEP_LANE_INDEXES: tuple[int, ...] = tuple(range(10))


class DeepRecoveryStateMachineTrace(RuleBasedStateMachine):
    """Mechanically exercise deep legal/recovery lanes in every generated case."""

    def __init__(self) -> None:
        super().__init__()
        self.lanes: tuple[_DeepTraceLane, ...] = ()
        self.replay_checked = False

    @initialize()
    def generate_required_deep_paths(self) -> None:
        # Initializers run once in every RuleBasedStateMachine example. Keeping
        # each path in its own lane prevents one terminal path from starving the
        # other recovery vocabulary and makes coverage a per-example assertion.
        self.lanes = _build_deep_recovery_lanes()
        _assert_deep_recovery_coverage(self.lanes)
        for lane in self.lanes:
            lane.assert_unified_replay()
        self.replay_checked = True

    @rule(lane_index=st.sampled_from(_DEEP_LANE_INDEXES))
    def replay_generated_path(self, lane_index: int) -> None:
        assert self.lanes
        self.lanes[lane_index].assert_unified_replay()

    @invariant()
    def required_deep_paths_are_present_and_replayable(self) -> None:
        assert self.lanes
        _assert_deep_recovery_coverage(self.lanes)

    def teardown(self) -> None:
        assert self.replay_checked


class OperationStateMachineTrace(RuleBasedStateMachine):
    """Drives ``OperationStateMachine`` and checks the twelve invariants."""

    def __init__(self) -> None:
        super().__init__()
        self.machine = OperationStateMachine(_BASE_IDENTITY)
        self.expected_state = OperationState.PROPOSED
        self.expected_attempt_ids: list[str] = []
        self.trace: list[TraceEntry] = []
        self.step = 0
        self.attempt_counter = 0
        self.true_effect_count = 0
        self.authority_expired = False
        self.claim_classifications: tuple[ClaimRecord, ...] = ()

    def _next_attempt_id(self) -> str:
        self.attempt_counter += 1
        return f"attempt-{self.attempt_counter}"

    def _record_model_command(self, kind: ModelCommandKind) -> None:
        self.step += 1
        command = ModelCommand(step=self.step, kind=kind)
        self.trace.append(command)
        note(f"command: {command}")

    def _reference_accepts(
        self,
        target: OperationState,
        cause: TransitionCause,
        *,
        fresh: bool,
        authoritative: bool,
        exact_identity: bool,
        postcondition_verified: bool,
        cardinality_valid: bool,
        attempt_id: str | None,
        identity: OperationIdentity,
    ) -> bool:
        return _reference_accepts(
            self.expected_state,
            self.expected_attempt_ids,
            target,
            cause,
            fresh=fresh,
            authoritative=authoritative,
            exact_identity=exact_identity,
            postcondition_verified=postcondition_verified,
            cardinality_valid=cardinality_valid,
            attempt_id=attempt_id,
            identity=identity,
        )

    def _run(
        self,
        target: OperationState,
        cause: TransitionCause,
        *,
        evidence_id: str,
        fresh: bool = False,
        authoritative: bool = False,
        exact_identity: bool = False,
        postcondition_verified: bool = False,
        cardinality_valid: bool = False,
        attempt_id: str | None = None,
        identity: OperationIdentity = _BASE_IDENTITY,
    ) -> TransitionRecord | InvalidTransitionError:
        self.step += 1
        expected_success = self._reference_accepts(
            target,
            cause,
            fresh=fresh,
            authoritative=authoritative,
            exact_identity=exact_identity,
            postcondition_verified=postcondition_verified,
            cardinality_valid=cardinality_valid,
            attempt_id=attempt_id,
            identity=identity,
        )
        overrides = tuple(
            (field.name, getattr(identity, field.name))
            for field in fields(identity)
            if getattr(identity, field.name) != getattr(_BASE_IDENTITY, field.name)
        )
        command = Command(
            step=self.step,
            target=target.value,
            cause=cause.value,
            evidence_id=evidence_id,
            fresh=fresh,
            authoritative=authoritative,
            exact_identity=exact_identity,
            postcondition_verified=postcondition_verified,
            cardinality_valid=cardinality_valid,
            attempt_id=attempt_id,
            identity_overrides=overrides,
            expected_success=expected_success,
        )
        self.trace.append(command)
        note(f"command: {command}")

        evidence = _evidence(
            cause,
            evidence_id,
            fresh=fresh,
            authoritative=authoritative,
            exact_identity=exact_identity,
            postcondition_verified=postcondition_verified,
            cardinality_valid=cardinality_valid,
        )
        # Transitions consume observations; only an explicit effect_committed
        # model command may change the modeled true effect count. In
        # particular SUCCESS_RECEIPT and EXACT_EFFECT_FOUND never do.
        effect_count_before = self.true_effect_count
        try:
            record = self.machine.transition(
                target,
                evidence=evidence,
                identity=identity,
                attempt_id=attempt_id,
            )
        except InvalidTransitionError as error:
            assert not expected_success, (
                "reference model predicted success but implementation rejected "
                f"{command}"
            )
            assert self.true_effect_count == effect_count_before
            self.expected_state = OperationState.VIOLATION
            return error

        assert expected_success, (
            f"reference model predicted rejection but implementation accepted {command}"
        )
        assert self.true_effect_count == effect_count_before
        self.expected_state = target
        if target is OperationState.IN_FLIGHT:
            assert attempt_id is not None
            self.expected_attempt_ids.append(attempt_id)
        return record

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.PROPOSED)
    def authorize(self) -> None:
        result = self._run(
            OperationState.AUTHORIZED,
            TransitionCause.AUTHORITY_CONFIRMED,
            evidence_id=f"e-authorized-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.AUTHORIZED)
    def prepare(self) -> None:
        result = self._run(
            OperationState.PREPARED,
            TransitionCause.PREPARATION_DURABLE,
            evidence_id=f"e-prepared-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.AUTHORIZED)
    def safe_stop_before_dispatch(self) -> None:
        result = self._run(
            OperationState.SAFE_STOP,
            TransitionCause.SAFE_STOP_SELECTED,
            evidence_id=f"e-early-stop-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.PREPARED)
    def dispatch(self) -> None:
        attempt_id = self._next_attempt_id()
        result = self._run(
            OperationState.IN_FLIGHT,
            TransitionCause.ATTEMPT_DELIVERED,
            evidence_id=f"e-dispatch-{self.step}",
            attempt_id=attempt_id,
        )
        assert isinstance(result, TransitionRecord)

    @rule()
    @precondition(
        lambda self: (
            self.expected_state in {OperationState.PREPARED, OperationState.RETRYABLE}
        )
    )
    def missing_dispatch_attempt_id(self) -> None:
        cause = (
            TransitionCause.ATTEMPT_DELIVERED
            if self.expected_state is OperationState.PREPARED
            else TransitionCause.REDISPATCH_AUTHORIZED
        )
        result = self._run(
            OperationState.IN_FLIGHT,
            cause,
            evidence_id=f"e-missing-attempt-{self.step}",
        )
        assert isinstance(result, InvalidTransitionError)

    @rule(malformed=st.sampled_from(_MALFORMED_ATTEMPT_IDS))
    @precondition(
        lambda self: (
            self.expected_state in {OperationState.PREPARED, OperationState.RETRYABLE}
        )
    )
    def malformed_dispatch_attempt_id(self, malformed: str) -> None:
        cause = (
            TransitionCause.ATTEMPT_DELIVERED
            if self.expected_state is OperationState.PREPARED
            else TransitionCause.REDISPATCH_AUTHORIZED
        )
        result = self._run(
            OperationState.IN_FLIGHT,
            cause,
            evidence_id=f"e-malformed-attempt-{self.step}",
            attempt_id=malformed,
        )
        assert isinstance(result, InvalidTransitionError)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.RETRYABLE)
    def reused_dispatch_attempt_id(self) -> None:
        assert self.expected_attempt_ids
        result = self._run(
            OperationState.IN_FLIGHT,
            TransitionCause.REDISPATCH_AUTHORIZED,
            evidence_id=f"e-reused-attempt-{self.step}",
            attempt_id=self.expected_attempt_ids[0],
        )
        assert isinstance(result, InvalidTransitionError)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.PROPOSED)
    def non_dispatch_attempt_id(self) -> None:
        result = self._run(
            OperationState.AUTHORIZED,
            TransitionCause.AUTHORITY_CONFIRMED,
            evidence_id=f"e-nondispatch-attempt-{self.step}",
            attempt_id="attempt-stray",
        )
        assert isinstance(result, InvalidTransitionError)

    @rule(candidate=st.sampled_from(_ILLEGAL_PAIRS))
    def generated_illegal_target(
        self, candidate: tuple[OperationState, OperationState]
    ) -> None:
        source, target = candidate
        if self.expected_state is not source:
            return
        result = self._run(
            target,
            next(iter(TransitionCause)),
            evidence_id=f"e-generated-illegal-target-{self.step}",
            attempt_id=(
                self._next_attempt_id() if target is OperationState.IN_FLIGHT else None
            ),
        )
        assert isinstance(result, InvalidTransitionError)

    @rule(candidate=st.sampled_from(_WRONG_CAUSE_CASES))
    def generated_wrong_cause(
        self,
        candidate: tuple[OperationState, OperationState, TransitionCause],
    ) -> None:
        source, target, cause = candidate
        if self.expected_state is not source:
            return
        result = self._run(
            target,
            cause,
            evidence_id=f"e-generated-wrong-cause-{self.step}",
            attempt_id=(
                self._next_attempt_id() if target is OperationState.IN_FLIGHT else None
            ),
        )
        assert isinstance(result, InvalidTransitionError)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.IN_FLIGHT)
    def success_receipt(self) -> None:
        result = self._run(
            OperationState.VERIFYING,
            TransitionCause.SUCCESS_RECEIPT,
            evidence_id=f"e-success-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.IN_FLIGHT)
    def precommit_rejection(self) -> None:
        result = self._run(
            OperationState.RETRYABLE,
            TransitionCause.PRECOMMIT_REJECTION,
            evidence_id=f"e-rejected-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.IN_FLIGHT)
    def ambiguous_outcome(self) -> None:
        result = self._run(
            OperationState.INDETERMINATE,
            TransitionCause.AMBIGUOUS_OUTCOME,
            evidence_id=f"e-ambiguous-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.INDETERMINATE)
    def direct_redispatch_from_indeterminate(self) -> None:
        attempt_id = self._next_attempt_id()
        result = self._run(
            OperationState.IN_FLIGHT,
            TransitionCause.REDISPATCH_AUTHORIZED,
            evidence_id=f"e-skip-recon-{self.step}",
            attempt_id=attempt_id,
        )
        assert isinstance(result, InvalidTransitionError)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.INDETERMINATE)
    def start_reconciliation(self) -> None:
        result = self._run(
            OperationState.RECONCILING,
            TransitionCause.RECONCILIATION_STARTED,
            evidence_id=f"e-reconciling-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule(facts=st.sampled_from(_RECONCILE_FACT_TUPLES))
    @precondition(lambda self: self.expected_state is OperationState.RECONCILING)
    def reconciliation_absence(self, facts: tuple[bool, bool, bool]) -> None:
        fresh, authoritative, exact_identity = facts
        result = self._run(
            OperationState.RETRYABLE,
            TransitionCause.CONCLUSIVE_ABSENCE,
            evidence_id=f"e-absence-{self.step}",
            fresh=fresh,
            authoritative=authoritative,
            exact_identity=exact_identity,
        )
        if fresh and authoritative and exact_identity:
            assert isinstance(result, TransitionRecord)
        else:
            assert isinstance(result, InvalidTransitionError)

    @rule(facts=st.sampled_from(_RECONCILE_FACT_TUPLES))
    @precondition(lambda self: self.expected_state is OperationState.RECONCILING)
    def reconciliation_exact_effect(self, facts: tuple[bool, bool, bool]) -> None:
        fresh, authoritative, exact_identity = facts
        result = self._run(
            OperationState.VERIFYING,
            TransitionCause.EXACT_EFFECT_FOUND,
            evidence_id=f"e-exact-{self.step}",
            fresh=fresh,
            authoritative=authoritative,
            exact_identity=exact_identity,
        )
        if fresh and authoritative and exact_identity:
            assert isinstance(result, TransitionRecord)
        else:
            assert isinstance(result, InvalidTransitionError)

    @rule(facts=st.sampled_from(_RECONCILE_FACT_TUPLES))
    @precondition(lambda self: self.expected_state is OperationState.RECONCILING)
    def reconciliation_inconclusive(self, facts: tuple[bool, bool, bool]) -> None:
        fresh, authoritative, exact_identity = facts
        result = self._run(
            OperationState.SAFE_STOP,
            TransitionCause.RECONCILIATION_INCONCLUSIVE,
            evidence_id=f"e-inconclusive-{self.step}",
            fresh=fresh,
            authoritative=authoritative,
            exact_identity=exact_identity,
        )
        if exact_identity:
            assert isinstance(result, TransitionRecord)
        else:
            assert isinstance(result, InvalidTransitionError)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.RETRYABLE)
    def expire_authority(self) -> None:
        self._record_model_command("authority_expired")
        self.authority_expired = True

    @rule()
    @precondition(
        lambda self: (
            self.expected_state is OperationState.RETRYABLE and self.authority_expired
        )
    )
    def expired_redispatch_is_explicit_violation(self) -> None:
        result = self._run(
            OperationState.VIOLATION,
            TransitionCause.INVARIANT_VIOLATION,
            evidence_id=f"e-expired-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule()
    @precondition(
        lambda self: (
            self.expected_state is OperationState.RETRYABLE
            and not self.authority_expired
        )
    )
    def retry_with_new_attempt(self) -> None:
        attempt_id = self._next_attempt_id()
        result = self._run(
            OperationState.IN_FLIGHT,
            TransitionCause.REDISPATCH_AUTHORIZED,
            evidence_id=f"e-retry-{self.step}",
            attempt_id=attempt_id,
        )
        assert isinstance(result, TransitionRecord)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.RETRYABLE)
    def safe_stop_from_retryable(self) -> None:
        result = self._run(
            OperationState.SAFE_STOP,
            TransitionCause.SAFE_STOP_SELECTED,
            evidence_id=f"e-stop-retryable-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule(facts=st.sampled_from(_COMPLETION_FACT_TUPLES))
    @precondition(lambda self: self.expected_state is OperationState.VERIFYING)
    def complete(self, facts: tuple[bool, bool, bool, bool]) -> None:
        fresh, authoritative, postcondition_verified, cardinality_valid = facts
        result = self._run(
            OperationState.COMPLETE,
            TransitionCause.FRESH_POSTCONDITION,
            evidence_id=f"e-complete-{self.step}",
            fresh=fresh,
            authoritative=authoritative,
            postcondition_verified=postcondition_verified,
            cardinality_valid=cardinality_valid,
        )
        if fresh and authoritative and postcondition_verified and cardinality_valid:
            assert isinstance(result, TransitionRecord)
            if self.true_effect_count > _MAX_EFFECTS:
                assert not _is_passing_trace(
                    state=self.machine.state,
                    honest_claim=True,
                    true_effect_count=self.true_effect_count,
                )
        else:
            assert isinstance(result, InvalidTransitionError)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.VERIFYING)
    def verification_incomplete(self) -> None:
        result = self._run(
            OperationState.RECONCILING,
            TransitionCause.VERIFICATION_INCOMPLETE,
            evidence_id=f"e-verify-incomplete-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule()
    @precondition(lambda self: self.expected_state is OperationState.VERIFYING)
    def postcondition_failed(self) -> None:
        result = self._run(
            OperationState.SAFE_STOP,
            TransitionCause.POSTCONDITION_FAILED,
            evidence_id=f"e-postcondition-failed-{self.step}",
        )
        assert isinstance(result, TransitionRecord)

    @rule(changed_fields=st.sampled_from(_IDENTITY_MUTATION_COMBINATIONS))
    def mutate_identity(self, changed_fields: tuple[str, ...]) -> None:
        overrides = {field: _ALT_VALUES[field] for field in changed_fields}
        mutated = replace(_BASE_IDENTITY, **overrides)
        result = self._run(
            OperationState.AUTHORIZED,
            TransitionCause.AUTHORITY_CONFIRMED,
            evidence_id=f"e-mutate-identity-{self.step}",
            identity=mutated,
        )
        assert isinstance(result, InvalidTransitionError)

    @rule()
    @precondition(
        lambda self: (
            self.expected_state is OperationState.IN_FLIGHT
            and self.true_effect_count == 0
        )
    )
    def commit_first_effect(self) -> None:
        # The service commits the true side effect while an attempt is in
        # flight; the model records it explicitly instead of inferring it
        # from a later receipt or discovery.
        self._record_model_command("effect_committed")
        self.true_effect_count += 1

    @rule()
    @precondition(lambda self: self.true_effect_count == 1)
    def commit_duplicate_effect(self) -> None:
        # Duplicate delivery is a distinct second explicit commit; it can
        # land at any point after the first commit, independent of the
        # machine's evidence-driven view.
        self._record_model_command("effect_committed")
        self.true_effect_count += 1

    @rule()
    def claim_complete(self) -> None:
        self._record_model_command("claim_complete")
        self.claim_classifications += (
            (
                "complete",
                _claim_accepted(self.machine.state, "complete"),
                self.machine.state,
            ),
        )

    @rule()
    def claim_blocked(self) -> None:
        self._record_model_command("claim_blocked")
        self.claim_classifications += (
            (
                "blocked",
                _claim_accepted(self.machine.state, "blocked"),
                self.machine.state,
            ),
        )

    # -- invariants ---------------------------------------------------

    @invariant()
    def history_is_linear_and_matches_current_state(self) -> None:
        history = self.machine.history
        if history:
            assert history[-1].resulting_state is self.machine.state
        for earlier, later in pairwise(history):
            assert later.source_state is earlier.resulting_state
        assert self.machine.state is self.expected_state

    @invariant()
    def in_flight_entries_have_unique_matching_attempt_ids(self) -> None:
        in_flight_attempts = [
            record.attempt_id
            for record in self.machine.history
            if record.resulting_state is OperationState.IN_FLIGHT
            and record.violation_reason is None
        ]
        assert all(attempt_id is not None for attempt_id in in_flight_attempts)
        assert len(in_flight_attempts) == len(set(in_flight_attempts))
        assert tuple(in_flight_attempts) == self.machine.attempt_ids
        assert self.machine.attempt_ids == tuple(self.expected_attempt_ids)

    @invariant()
    def retry_preserves_identity_with_new_attempt(self) -> None:
        assert self.machine.identity == _BASE_IDENTITY

    @invariant()
    def violation_is_terminal_without_history_growth(self) -> None:
        if self.machine.state is OperationState.VIOLATION:
            history_length = len(self.machine.history)
            with pytest.raises(InvalidTransitionError):
                self.machine.transition(
                    OperationState.AUTHORIZED,
                    evidence=_evidence(
                        TransitionCause.AUTHORITY_CONFIRMED, "e-post-violation-probe"
                    ),
                    identity=_BASE_IDENTITY,
                )
            assert len(self.machine.history) == history_length
            assert self.machine.state is OperationState.VIOLATION

    @invariant()
    def claim_acceptance_matches_terminal_state(self) -> None:
        for status, accepted, state_at_claim in self.claim_classifications:
            assert accepted == _claim_accepted(state_at_claim, status)
            if self.true_effect_count > _MAX_EFFECTS:
                assert not _is_passing_trace(
                    state=state_at_claim,
                    honest_claim=True,
                    true_effect_count=self.true_effect_count,
                )

    @invariant()
    def effect_count_equals_explicit_commit_commands(self) -> None:
        explicit_commits = sum(
            1
            for command in self.trace
            if isinstance(command, ModelCommand) and command.kind == "effect_committed"
        )
        assert self.true_effect_count == explicit_commits

    @invariant()
    def replay_reproduces_state_history_attempts_and_effects(self) -> None:
        # Note the trace before asserting so a replay failure still prints
        # the exact command sequence needed to reproduce it.
        note(f"trace: {self.trace!r}")
        replay = _replay_trace(self.trace)
        note(f"replay digest: {replay.history_digest}")
        assert replay.state is self.machine.state
        assert replay.attempt_ids == self.machine.attempt_ids
        assert replay.true_effect_count == self.true_effect_count
        assert replay.authority_expired is self.authority_expired
        assert replay.claim_classifications == self.claim_classifications
        original_digest = canonical_digest(
            [record.canonical_value() for record in self.machine.history]
        )
        assert replay.history_digest == original_digest


DeepRecoveryStateMachineTrace.TestCase.settings = _DETERMINISTIC_SETTINGS
TestDeepRecoveryStateMachineTrace = DeepRecoveryStateMachineTrace.TestCase
OperationStateMachineTrace.TestCase.settings = _DETERMINISTIC_SETTINGS
TestOperationStateMachineTrace = OperationStateMachineTrace.TestCase
