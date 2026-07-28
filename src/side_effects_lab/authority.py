"""Deterministic, side-effect-free authority checks for one immutable grant."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import TypeAdapter

from side_effects_lab.canonical import canonical_digest, canonical_json_bytes
from side_effects_lab.models import (
    ActionId,
    AuthorityGrant,
    AuthorityId,
    CanonicalValue,
    Digest,
    EvidenceMap,
    FrozenMap,
    OperationKey,
    SemanticIntent,
    SubjectId,
)
from side_effects_lab.state_machine import (
    OperationIdentity,
    OperationState,
    TransitionCause,
)

_ACTION_ID_ADAPTER: TypeAdapter[ActionId] = TypeAdapter(ActionId)
_AUTHORITY_ID_ADAPTER: TypeAdapter[AuthorityId] = TypeAdapter(AuthorityId)
_DIGEST_ADAPTER: TypeAdapter[Digest] = TypeAdapter(Digest)
_OPERATION_KEY_ADAPTER: TypeAdapter[OperationKey] = TypeAdapter(OperationKey)
_SUBJECT_ID_ADAPTER: TypeAdapter[SubjectId] = TypeAdapter(SubjectId)
_EVIDENCE_ADAPTER: TypeAdapter[EvidenceMap] = TypeAdapter(EvidenceMap)


class CheckKind(StrEnum):
    AUTHORIZE = "authorize"
    PASSIVE_PRE_DISPATCH = "passive_pre_dispatch"
    PRE_DISPATCH_WRITE = "pre_dispatch_write"
    REDISPATCH = "redispatch"
    READ_ONLY = "read_only"


class AuthorityDisposition(StrEnum):
    ALLOW = "ALLOW"
    SAFE_STOP = "SAFE_STOP"
    VIOLATION = "VIOLATION"


class AuthorityReason(StrEnum):
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    AUTHORITY_ID_MISMATCH = "AUTHORITY_ID_MISMATCH"
    SUBJECT_MISMATCH = "SUBJECT_MISMATCH"
    SERVICE_MISMATCH = "SERVICE_MISMATCH"
    OPERATION_MISMATCH = "OPERATION_MISMATCH"
    INTENT_DIGEST_MISMATCH = "INTENT_DIGEST_MISMATCH"
    PARAMETERS_MISMATCH = "PARAMETERS_MISMATCH"
    COMPENSATION_NOT_AUTHORIZED = "COMPENSATION_NOT_AUTHORIZED"
    CARDINALITY_EXCEEDED = "CARDINALITY_EXCEEDED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    AUTHORIZED = "AUTHORIZED"
    REVALIDATED = "REVALIDATED"
    READ_ONLY_ALLOWED = "READ_ONLY_ALLOWED"


# Frozen total order for the winning attempted-write reason. Every defect in a
# request still yields a VIOLATION disposition; only the reported reason obeys
# this precedence, and any non-expiry defect outranks AUTH_EXPIRED so a passive
# safe stop occurs only when expiry is the sole surviving defect class.
REASON_PRECEDENCE: tuple[AuthorityReason, ...] = (
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

_ALLOW_REASONS = frozenset(
    {
        AuthorityReason.AUTHORIZED,
        AuthorityReason.REVALIDATED,
        AuthorityReason.READ_ONLY_ALLOWED,
    }
)
_PERMITTED_TRANSITIONS = frozenset(
    {
        (OperationState.AUTHORIZED, TransitionCause.AUTHORITY_CONFIRMED),
        (OperationState.SAFE_STOP, TransitionCause.SAFE_STOP_SELECTED),
        (OperationState.VIOLATION, TransitionCause.INVARIANT_VIOLATION),
    }
)

# Exact authority-evidence contract. FrozenMap's constructor validates nothing
# and does not deep-freeze, so AuthorityDecision must reject any key or value
# outside this schema and rebuild the evidence through strict validation.
_EVIDENCE_KEYS: tuple[str, ...] = (
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
_EVIDENCE_STRING_ADAPTERS: dict[str, TypeAdapter[str]] = {
    "action_id": _ACTION_ID_ADAPTER,
    "operation_key": _OPERATION_KEY_ADAPTER,
    "authority_id": _AUTHORITY_ID_ADAPTER,
    "grant_authority_id": _AUTHORITY_ID_ADAPTER,
    "candidate_intent_digest": _DIGEST_ADAPTER,
    "grant_intent_digest": _DIGEST_ADAPTER,
    "recomputed_intent_digest": _DIGEST_ADAPTER,
}
_EVIDENCE_VOCABULARIES: dict[str, frozenset[str]] = {
    "check_kind": frozenset(kind.value for kind in CheckKind),
    "disposition": frozenset(item.value for item in AuthorityDisposition),
    "reason": frozenset(item.value for item in AuthorityReason),
}
_EVIDENCE_COUNT_KEYS = frozenset(
    {"checked_tick", "committed_effect_count", "expires_at_tick", "max_effects"}
)
_EVIDENCE_BOOL_KEYS = frozenset(
    {
        "authority_id_match",
        "cardinality_valid",
        "compensation_claimed",
        "identity_confirmed",
        "intent_digest_match",
        "operation_match",
        "parameters_match",
        "service_match",
        "subject_match",
        "tick_valid",
    }
)


def _validated_count(name: str, value: object) -> int:
    # bool is an int subclass; an exact type check rejects it without coercion.
    if type(value) is not int:
        raise TypeError(f"{name} must be a strict non-negative integer")
    if value < 0:
        raise ValueError(f"{name} must be a strict non-negative integer")
    return value


def _validated_evidence_field(key: str, value: object) -> CanonicalValue:
    # Every allowed key carries an exact type and vocabulary so prose, URLs,
    # or nested structures cannot be smuggled through a permitted string key.
    adapter = _EVIDENCE_STRING_ADAPTERS.get(key)
    if adapter is not None:
        if type(value) is not str:
            raise TypeError(f"evidence {key} must be a canonical identifier string")
        return adapter.validate_python(value)
    vocabulary = _EVIDENCE_VOCABULARIES.get(key)
    if vocabulary is not None:
        if type(value) is not str:
            raise ValueError(f"evidence {key} must use its frozen vocabulary")
        if value not in vocabulary:
            raise ValueError(f"evidence {key} must use its frozen vocabulary")
        return value
    if key in _EVIDENCE_COUNT_KEYS:
        count = _validated_count(f"evidence {key}", value)
        if key == "max_effects" and count == 0:
            raise ValueError("evidence max_effects must be positive")
        return count
    if key in _EVIDENCE_BOOL_KEYS:
        if type(value) is not bool:
            raise TypeError(f"evidence {key} must be a strict boolean")
        return value
    if value is None:
        return None
    if type(value) is not bool:
        raise TypeError("evidence compensation_authorized must be a boolean or null")
    return value


@dataclass(frozen=True, slots=True)
class AuthorityCheck:
    """One immutable authority question about one semantic action."""

    kind: CheckKind
    candidate: OperationIdentity
    confirmed: OperationIdentity
    subject_id: SubjectId
    intent: SemanticIntent
    current_tick: int
    committed_effect_count: int
    is_compensation: bool = False
    original_grant: AuthorityGrant | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CheckKind):
            raise TypeError("kind must be a CheckKind")
        if type(self.candidate) is not OperationIdentity:
            raise TypeError("candidate must be an OperationIdentity")
        if type(self.confirmed) is not OperationIdentity:
            raise TypeError("confirmed must be an OperationIdentity")
        object.__setattr__(
            self,
            "subject_id",
            _SUBJECT_ID_ADAPTER.validate_python(self.subject_id),
        )
        if type(self.intent) is not SemanticIntent:
            raise TypeError("intent must be a SemanticIntent")
        _validated_count("current_tick", self.current_tick)
        _validated_count("committed_effect_count", self.committed_effect_count)
        if type(self.is_compensation) is not bool:
            raise TypeError("is_compensation must be a strict boolean")
        if self.original_grant is not None:
            if type(self.original_grant) is not AuthorityGrant:
                raise TypeError("original_grant must be an AuthorityGrant or None")
            if not self.is_compensation:
                raise ValueError(
                    "an original grant is valid only when compensation is claimed"
                )
        if self.kind is CheckKind.READ_ONLY and (
            self.is_compensation or self.original_grant is not None
        ):
            raise ValueError("a read_only check cannot claim compensation")


@dataclass(frozen=True, slots=True)
class AuthorityDecision:
    """One immutable disposition with deterministic sanitized evidence."""

    disposition: AuthorityDisposition
    reason: AuthorityReason
    evidence: EvidenceMap
    target: OperationState | None = None
    cause: TransitionCause | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, AuthorityDisposition):
            raise TypeError("disposition must be an AuthorityDisposition")
        if not isinstance(self.reason, AuthorityReason):
            raise TypeError("reason must be an AuthorityReason")
        if type(self.evidence) is not FrozenMap:
            raise TypeError("evidence must be a recursively frozen FrozenMap")
        pair: tuple[OperationState, TransitionCause] | None
        if self.target is None and self.cause is None:
            pair = None
        elif self.target is not None and self.cause is not None:
            pair = (self.target, self.cause)
            if pair not in _PERMITTED_TRANSITIONS:
                raise ValueError("target and cause must form a permitted pair")
        else:
            raise ValueError("target and cause must be null together")
        self._require_matrix_row(pair)
        object.__setattr__(self, "evidence", self._validated_evidence())

    def _validated_evidence(self) -> EvidenceMap:
        # Direct construction must fail as closed as check_authority does: the
        # incoming FrozenMap is unvalidated, so the exact key set and every
        # value are checked and the evidence is replaced with a strictly
        # revalidated, recursively frozen copy.
        if set(self.evidence.keys()) != set(_EVIDENCE_KEYS):
            raise ValueError(
                "evidence keys must match the authority evidence contract exactly"
            )
        payload: dict[str, CanonicalValue] = {
            key: _validated_evidence_field(key, self.evidence[key])
            for key in _EVIDENCE_KEYS
        }
        if payload["disposition"] != self.disposition.value:
            raise ValueError("evidence disposition must match the decision")
        if payload["reason"] != self.reason.value:
            raise ValueError("evidence reason must match the decision")
        return _EVIDENCE_ADAPTER.validate_python(payload, strict=True)

    def _require_matrix_row(
        self, pair: tuple[OperationState, TransitionCause] | None
    ) -> None:
        # Only initial authorization moves the state machine on ALLOW; the
        # revalidation and read-only rows deliberately return no transition.
        expected: tuple[OperationState, TransitionCause] | None
        if self.disposition is AuthorityDisposition.ALLOW:
            if self.reason not in _ALLOW_REASONS:
                raise ValueError("an ALLOW decision requires an allow reason")
            expected = (
                (OperationState.AUTHORIZED, TransitionCause.AUTHORITY_CONFIRMED)
                if self.reason is AuthorityReason.AUTHORIZED
                else None
            )
        elif self.disposition is AuthorityDisposition.SAFE_STOP:
            if self.reason is not AuthorityReason.AUTH_EXPIRED:
                raise ValueError("a SAFE_STOP decision requires AUTH_EXPIRED")
            expected = (OperationState.SAFE_STOP, TransitionCause.SAFE_STOP_SELECTED)
        else:
            if self.reason not in REASON_PRECEDENCE:
                raise ValueError("a VIOLATION decision requires a defect reason")
            expected = (OperationState.VIOLATION, TransitionCause.INVARIANT_VIOLATION)
        if pair != expected:
            raise ValueError("decision transition does not match its disposition")


def _revalidated_identity(identity: OperationIdentity) -> OperationIdentity:
    if type(identity) is not OperationIdentity:
        raise TypeError("identity must be an OperationIdentity")
    return OperationIdentity(
        action_id=identity.action_id,
        operation_key=identity.operation_key,
        intent_digest=identity.intent_digest,
        authority_id=identity.authority_id,
    )


def _revalidated_grant(grant: AuthorityGrant) -> AuthorityGrant:
    # Field values are revalidated directly instead of being serialized, so a
    # bypass-constructed grant raises a ValidationError without ever entering
    # the pydantic serializer.
    if type(grant) is not AuthorityGrant:
        raise TypeError("grant must be an AuthorityGrant")
    return AuthorityGrant.model_validate(
        {name: getattr(grant, name) for name in AuthorityGrant.model_fields}
    )


def _revalidated_request(request: AuthorityCheck) -> AuthorityCheck:
    if type(request) is not AuthorityCheck:
        raise TypeError("request must be an AuthorityCheck")
    if type(request.intent) is not SemanticIntent:
        raise TypeError("intent must be a SemanticIntent")
    original = request.original_grant
    return AuthorityCheck(
        kind=request.kind,
        candidate=_revalidated_identity(request.candidate),
        confirmed=_revalidated_identity(request.confirmed),
        subject_id=request.subject_id,
        intent=SemanticIntent.model_validate(
            {
                name: getattr(request.intent, name)
                for name in SemanticIntent.model_fields
            }
        ),
        current_tick=request.current_tick,
        committed_effect_count=request.committed_effect_count,
        is_compensation=request.is_compensation,
        original_grant=None if original is None else _revalidated_grant(original),
    )


def check_authority(
    grant: AuthorityGrant,
    request: AuthorityCheck,
) -> AuthorityDecision:
    """Decide one authority check deterministically and without side effects."""
    # Fail closed on bypass-constructed or tampered contracts: every contract
    # value is strictly revalidated before any comparison uses it.
    checked_grant = _revalidated_grant(grant)
    checked = _revalidated_request(request)
    candidate = checked.candidate
    confirmed = checked.confirmed
    intent = checked.intent

    recomputed_digest = canonical_digest(intent)
    identity_confirmed = (
        candidate.action_id == confirmed.action_id
        and candidate.operation_key == confirmed.operation_key
        and candidate.intent_digest == confirmed.intent_digest
        and candidate.authority_id == confirmed.authority_id
    )
    authority_id_match = candidate.authority_id == checked_grant.authority_id
    subject_match = checked.subject_id == checked_grant.subject_id
    service_match = intent.service == checked_grant.service
    operation_match = intent.operation == checked_grant.operation
    intent_digest_match = (
        recomputed_digest == candidate.intent_digest
        and recomputed_digest == checked_grant.semantic_intent_digest
    )
    # Canonical-byte equality keeps bool and int distinct at every nesting
    # depth and makes mapping insertion order irrelevant.
    parameters_match = canonical_json_bytes(intent.parameters) == canonical_json_bytes(
        checked_grant.allowed_parameters
    )
    tick_valid = checked.current_tick <= checked_grant.expires_at_tick
    cardinality_valid = checked.committed_effect_count < checked_grant.max_effects
    compensation_claimed = checked.is_compensation
    original = checked.original_grant
    compensation_authorized: bool | None = None
    if compensation_claimed:
        # Only the compensation naming in the original grant matters here; its
        # expiry is not rechecked, and the current grant must be separate.
        compensation_authorized = (
            original is not None
            and original.allowed_compensation == candidate.action_id
            and original.authority_id != checked_grant.authority_id
        )

    # A read_only check is exempt from cardinality and expiry so an earlier
    # committed effect stays observable; passive_pre_dispatch is write-capable.
    write_capable = checked.kind is not CheckKind.READ_ONLY
    defects: dict[AuthorityReason, bool] = {
        AuthorityReason.IDENTITY_MISMATCH: not identity_confirmed,
        AuthorityReason.AUTHORITY_ID_MISMATCH: not authority_id_match,
        AuthorityReason.SUBJECT_MISMATCH: not subject_match,
        AuthorityReason.SERVICE_MISMATCH: not service_match,
        AuthorityReason.OPERATION_MISMATCH: not operation_match,
        AuthorityReason.INTENT_DIGEST_MISMATCH: not intent_digest_match,
        AuthorityReason.PARAMETERS_MISMATCH: not parameters_match,
        AuthorityReason.COMPENSATION_NOT_AUTHORIZED: bool(
            compensation_claimed and not compensation_authorized
        ),
        AuthorityReason.CARDINALITY_EXCEEDED: write_capable and not cardinality_valid,
        AuthorityReason.AUTH_EXPIRED: write_capable and not tick_valid,
    }
    winning = next((reason for reason in REASON_PRECEDENCE if defects[reason]), None)

    target: OperationState | None
    cause: TransitionCause | None
    if winning is None:
        disposition = AuthorityDisposition.ALLOW
        if checked.kind is CheckKind.AUTHORIZE:
            reason = AuthorityReason.AUTHORIZED
            target = OperationState.AUTHORIZED
            cause = TransitionCause.AUTHORITY_CONFIRMED
        elif checked.kind is CheckKind.READ_ONLY:
            reason = AuthorityReason.READ_ONLY_ALLOWED
            target = None
            cause = None
        else:
            reason = AuthorityReason.REVALIDATED
            target = None
            cause = None
    elif (
        winning is AuthorityReason.AUTH_EXPIRED
        and checked.kind is CheckKind.PASSIVE_PRE_DISPATCH
    ):
        # Passive discovery of expiry before preparation is the only safe-stop
        # row; an actual attempted write under the same expiry is a violation.
        disposition = AuthorityDisposition.SAFE_STOP
        reason = AuthorityReason.AUTH_EXPIRED
        target = OperationState.SAFE_STOP
        cause = TransitionCause.SAFE_STOP_SELECTED
    else:
        disposition = AuthorityDisposition.VIOLATION
        reason = winning
        target = OperationState.VIOLATION
        cause = TransitionCause.INVARIANT_VIOLATION

    payload: dict[str, CanonicalValue] = {
        "action_id": candidate.action_id,
        "operation_key": candidate.operation_key,
        "authority_id": candidate.authority_id,
        "grant_authority_id": checked_grant.authority_id,
        "check_kind": checked.kind.value,
        "disposition": disposition.value,
        "reason": reason.value,
        "checked_tick": checked.current_tick,
        "expires_at_tick": checked_grant.expires_at_tick,
        "tick_valid": tick_valid,
        "candidate_intent_digest": candidate.intent_digest,
        "grant_intent_digest": checked_grant.semantic_intent_digest,
        "recomputed_intent_digest": recomputed_digest,
        "committed_effect_count": checked.committed_effect_count,
        "max_effects": checked_grant.max_effects,
        "cardinality_valid": cardinality_valid,
        "identity_confirmed": identity_confirmed,
        "authority_id_match": authority_id_match,
        "subject_match": subject_match,
        "service_match": service_match,
        "operation_match": operation_match,
        "intent_digest_match": intent_digest_match,
        "parameters_match": parameters_match,
        "compensation_claimed": compensation_claimed,
        "compensation_authorized": compensation_authorized,
    }
    evidence = _EVIDENCE_ADAPTER.validate_python(payload, strict=True)
    return AuthorityDecision(
        disposition=disposition,
        reason=reason,
        evidence=evidence,
        target=target,
        cause=cause,
    )


__all__ = [
    "REASON_PRECEDENCE",
    "AuthorityCheck",
    "AuthorityDecision",
    "AuthorityDisposition",
    "AuthorityReason",
    "CheckKind",
    "check_authority",
]
