"""Canonical per-action operation state machine."""

from dataclasses import dataclass, fields
from enum import StrEnum
from re import compile as compile_pattern
from types import MappingProxyType
from typing import NoReturn

from pydantic import TypeAdapter, ValidationError

from side_effects_lab.models import (
    ActionId,
    AttemptId,
    AuthorityId,
    Digest,
    OperationKey,
)

_ACTION_ID_ADAPTER: TypeAdapter[ActionId] = TypeAdapter(ActionId)
_ATTEMPT_ID_ADAPTER: TypeAdapter[AttemptId] = TypeAdapter(AttemptId)
_AUTHORITY_ID_ADAPTER: TypeAdapter[AuthorityId] = TypeAdapter(AuthorityId)
_DIGEST_ADAPTER: TypeAdapter[Digest] = TypeAdapter(Digest)
_OPERATION_KEY_ADAPTER: TypeAdapter[OperationKey] = TypeAdapter(OperationKey)
_EVIDENCE_ID_PATTERN = compile_pattern(r"^[a-z][a-z0-9-]{0,127}$")


class OperationState(StrEnum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    PREPARED = "PREPARED"
    IN_FLIGHT = "IN_FLIGHT"
    INDETERMINATE = "INDETERMINATE"
    RECONCILING = "RECONCILING"
    RETRYABLE = "RETRYABLE"
    VERIFYING = "VERIFYING"
    COMPLETE = "COMPLETE"
    SAFE_STOP = "SAFE_STOP"
    VIOLATION = "VIOLATION"


class TransitionCause(StrEnum):
    AUTHORITY_CONFIRMED = "authority_confirmed"
    INVARIANT_VIOLATION = "invariant_violation"
    PREPARATION_DURABLE = "preparation_durable"
    SAFE_STOP_SELECTED = "safe_stop_selected"
    ATTEMPT_DELIVERED = "attempt_delivered"
    SUCCESS_RECEIPT = "success_receipt"
    PRECOMMIT_REJECTION = "precommit_rejection"
    AMBIGUOUS_OUTCOME = "ambiguous_outcome"
    RECONCILIATION_STARTED = "reconciliation_started"
    EXACT_EFFECT_FOUND = "exact_effect_found"
    CONCLUSIVE_ABSENCE = "conclusive_absence"
    RECONCILIATION_INCONCLUSIVE = "reconciliation_inconclusive"
    REDISPATCH_AUTHORIZED = "redispatch_authorized"
    FRESH_POSTCONDITION = "fresh_postcondition"
    VERIFICATION_INCOMPLETE = "verification_incomplete"
    POSTCONDITION_FAILED = "postcondition_failed"


NORMATIVE_TRANSITIONS = MappingProxyType(
    {
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
)


@dataclass(frozen=True, slots=True)
class OperationIdentity:
    action_id: ActionId
    operation_key: OperationKey
    intent_digest: Digest
    authority_id: AuthorityId

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action_id", _ACTION_ID_ADAPTER.validate_python(self.action_id)
        )
        object.__setattr__(
            self,
            "operation_key",
            _OPERATION_KEY_ADAPTER.validate_python(self.operation_key),
        )
        object.__setattr__(
            self, "intent_digest", _DIGEST_ADAPTER.validate_python(self.intent_digest)
        )
        object.__setattr__(
            self,
            "authority_id",
            _AUTHORITY_ID_ADAPTER.validate_python(self.authority_id),
        )


@dataclass(frozen=True, slots=True)
class TransitionEvidence:
    evidence_id: str
    cause: TransitionCause
    fresh: bool = False
    authoritative: bool = False
    exact_identity: bool = False
    postcondition_verified: bool = False
    cardinality_valid: bool = False

    def __post_init__(self) -> None:
        if type(self.evidence_id) is not str or not _EVIDENCE_ID_PATTERN.fullmatch(
            self.evidence_id
        ):
            raise ValueError(
                "evidence_id must be a 1-128 character lowercase ASCII token"
            )
        if not isinstance(self.cause, TransitionCause):
            raise TypeError("cause must be a TransitionCause")
        for field in fields(self):
            if field.name in {"evidence_id", "cause"}:
                continue
            value = getattr(self, field.name)
            if type(value) is not bool:
                raise TypeError(f"{field.name} must be a boolean")


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    source_state: OperationState
    attempted_state: OperationState
    resulting_state: OperationState
    evidence_id: str
    cause: TransitionCause
    attempt_id: AttemptId | None = None
    violation_reason: str | None = None

    def canonical_value(self) -> dict[str, str | None]:
        return {
            "attempt_id": self.attempt_id,
            "attempted_state": self.attempted_state.value,
            "cause": self.cause.value,
            "evidence_id": self.evidence_id,
            "resulting_state": self.resulting_state.value,
            "source_state": self.source_state.value,
            "violation_reason": self.violation_reason,
        }


class InvalidTransitionError(RuntimeError):
    """Raised after a forbidden transition records a violation."""

    def __init__(self, record: TransitionRecord) -> None:
        self.record = record
        reason = record.violation_reason or "unspecified violation"
        super().__init__(
            "invalid transition: "
            f"state={record.source_state.value} "
            f"attempted={record.attempted_state.value} "
            f"evidence_id={record.evidence_id} "
            f"reason={reason}"
        )


class OperationStateMachine:
    """Enforce the normative state graph for one immutable semantic action."""

    __slots__ = ("_attempt_ids", "_history", "_identity", "_state")

    def __init__(self, identity: OperationIdentity) -> None:
        if not isinstance(identity, OperationIdentity):
            raise TypeError("identity must be an OperationIdentity")
        self._identity = identity
        self._state = OperationState.PROPOSED
        self._attempt_ids: list[AttemptId] = []
        self._history: list[TransitionRecord] = []

    @property
    def identity(self) -> OperationIdentity:
        return self._identity

    @property
    def state(self) -> OperationState:
        return self._state

    @property
    def attempt_ids(self) -> tuple[AttemptId, ...]:
        return tuple(self._attempt_ids)

    @property
    def history(self) -> tuple[TransitionRecord, ...]:
        return tuple(self._history)

    def transition(
        self,
        target: OperationState,
        *,
        evidence: TransitionEvidence,
        identity: OperationIdentity,
        attempt_id: AttemptId | None = None,
    ) -> TransitionRecord:
        if not isinstance(target, OperationState):
            raise TypeError("target must be an OperationState")
        if not isinstance(evidence, TransitionEvidence):
            raise TypeError("evidence must be TransitionEvidence")
        if not isinstance(identity, OperationIdentity):
            raise TypeError("identity must be OperationIdentity")

        source = self._state
        if source is OperationState.VIOLATION:
            record = TransitionRecord(
                source_state=source,
                attempted_state=target,
                resulting_state=source,
                evidence_id=evidence.evidence_id,
                cause=evidence.cause,
                attempt_id=self._attempt_for_record(attempt_id),
                violation_reason="VIOLATION is terminal",
            )
            raise InvalidTransitionError(record)

        changed_fields = self._changed_identity_fields(identity)
        if changed_fields:
            self._fail(
                target,
                evidence,
                attempt_id,
                reason="immutable identity changed: " + ", ".join(changed_fields),
            )

        validated_attempt_id = self._validate_attempt_for_target(
            target, evidence, attempt_id
        )

        if (
            target is OperationState.VIOLATION
            and evidence.cause is TransitionCause.INVARIANT_VIOLATION
        ):
            return self._record_transition(
                target,
                evidence,
                validated_attempt_id,
                violation_reason="invariant violation reported",
            )

        expected_cause = NORMATIVE_TRANSITIONS.get((source, target))
        if expected_cause is None:
            self._fail(
                target,
                evidence,
                validated_attempt_id,
                reason="transition is not allowed",
            )
        if evidence.cause is not expected_cause:
            self._fail(
                target,
                evidence,
                validated_attempt_id,
                reason=(
                    f"evidence cause {evidence.cause.value} does not match "
                    f"required {expected_cause.value}"
                ),
            )

        guard_failure = self._guard_failure(source, target, evidence)
        if guard_failure is not None:
            self._fail(
                target,
                evidence,
                validated_attempt_id,
                reason=guard_failure,
            )

        record = self._record_transition(target, evidence, validated_attempt_id)
        if validated_attempt_id is not None:
            self._attempt_ids.append(validated_attempt_id)
        return record

    def _changed_identity_fields(self, candidate: OperationIdentity) -> list[str]:
        return [
            field.name
            for field in fields(self._identity)
            if getattr(candidate, field.name) != getattr(self._identity, field.name)
        ]

    def _validate_attempt_for_target(
        self,
        target: OperationState,
        evidence: TransitionEvidence,
        attempt_id: AttemptId | None,
    ) -> AttemptId | None:
        if target is not OperationState.IN_FLIGHT:
            if attempt_id is not None:
                self._fail(
                    target,
                    evidence,
                    attempt_id,
                    reason="attempt_id is only valid when entering IN_FLIGHT",
                )
            return None
        if attempt_id is None:
            self._fail(
                target,
                evidence,
                attempt_id,
                reason="entering IN_FLIGHT requires a new attempt_id",
            )
        try:
            validated = _ATTEMPT_ID_ADAPTER.validate_python(attempt_id)
        except ValidationError:
            self._fail(
                target,
                evidence,
                attempt_id,
                reason="attempt_id is invalid",
            )
        if validated in self._attempt_ids:
            self._fail(
                target,
                evidence,
                validated,
                reason="attempt_id was already used",
            )
        return validated

    @staticmethod
    def _attempt_for_record(attempt_id: object) -> AttemptId | None:
        if attempt_id is None:
            return None
        try:
            return _ATTEMPT_ID_ADAPTER.validate_python(attempt_id)
        except ValidationError:
            return None

    @staticmethod
    def _guard_failure(
        source: OperationState,
        target: OperationState,
        evidence: TransitionEvidence,
    ) -> str | None:
        if source is OperationState.RECONCILING and target in {
            OperationState.VERIFYING,
            OperationState.RETRYABLE,
        }:
            required = {
                "fresh": evidence.fresh,
                "authoritative": evidence.authoritative,
                "exact_identity": evidence.exact_identity,
            }
            missing = [name for name, present in required.items() if not present]
            if missing:
                return "reconciliation evidence lacks " + ", ".join(missing)
        if (
            source is OperationState.RECONCILING
            and target is OperationState.SAFE_STOP
            and not evidence.exact_identity
        ):
            return "safe stop requires an attempted exact-identity lookup"
        if source is OperationState.VERIFYING and target is OperationState.COMPLETE:
            required = {
                "fresh": evidence.fresh,
                "authoritative": evidence.authoritative,
                "postcondition_verified": evidence.postcondition_verified,
                "cardinality_valid": evidence.cardinality_valid,
            }
            missing = [name for name, present in required.items() if not present]
            if missing:
                return "completion evidence lacks " + ", ".join(missing)
        return None

    def _record_transition(
        self,
        target: OperationState,
        evidence: TransitionEvidence,
        attempt_id: AttemptId | None,
        *,
        violation_reason: str | None = None,
    ) -> TransitionRecord:
        record = TransitionRecord(
            source_state=self._state,
            attempted_state=target,
            resulting_state=target,
            evidence_id=evidence.evidence_id,
            cause=evidence.cause,
            attempt_id=attempt_id,
            violation_reason=violation_reason,
        )
        self._state = target
        self._history.append(record)
        return record

    def _fail(
        self,
        target: OperationState,
        evidence: TransitionEvidence,
        attempt_id: object,
        *,
        reason: str,
    ) -> NoReturn:
        record = TransitionRecord(
            source_state=self._state,
            attempted_state=target,
            resulting_state=OperationState.VIOLATION,
            evidence_id=evidence.evidence_id,
            cause=evidence.cause,
            attempt_id=self._attempt_for_record(attempt_id),
            violation_reason=reason,
        )
        self._state = OperationState.VIOLATION
        self._history.append(record)
        raise InvalidTransitionError(record)


__all__ = [
    "NORMATIVE_TRANSITIONS",
    "InvalidTransitionError",
    "OperationIdentity",
    "OperationState",
    "OperationStateMachine",
    "TransitionCause",
    "TransitionEvidence",
    "TransitionRecord",
]
