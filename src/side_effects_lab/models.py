"""Strict, versioned primitives shared by Side Effects Lab contracts."""

from collections.abc import Iterable
from enum import StrEnum
from re import compile as compile_pattern
from typing import (
    Annotated,
    Literal,
    NoReturn,
    Self,
    SupportsIndex,
    cast,
    overload,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

CURRENT_SCHEMA_VERSION = "0.1"
CURRENT_PROTOCOL_VERSION = "0.1"

type SchemaVersion = Literal["0.1"]
type ProtocolVersion = Literal["0.1"]
type SemanticVersion = Annotated[
    str,
    StringConstraints(
        max_length=96,
        pattern=(
            r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
            r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
            r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
        ),
    ),
]

type ScenarioId = Annotated[
    str, StringConstraints(max_length=7, pattern=r"^SEL-[0-9]{3}$")
]
type RunId = Annotated[
    str,
    StringConstraints(max_length=128, pattern=r"^run-[a-z0-9][a-z0-9-]*$"),
]
type SubjectId = Annotated[
    str, StringConstraints(max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
]
type ActionId = Annotated[
    str,
    StringConstraints(max_length=128, pattern=r"^action-[a-z0-9][a-z0-9-]*$"),
]
type OperationKey = Annotated[
    str, StringConstraints(max_length=128, pattern=r"^op-[a-z0-9][a-z0-9-]*$")
]
type AttemptId = Annotated[
    str,
    StringConstraints(max_length=128, pattern=r"^attempt-[a-z0-9][a-z0-9-]*$"),
]
type EffectId = Annotated[
    str, StringConstraints(max_length=128, pattern=r"^[a-z][a-z0-9-]*$")
]
type AuthorityId = Annotated[
    str,
    StringConstraints(max_length=128, pattern=r"^auth-[a-z0-9][a-z0-9-]*$"),
]
type WorkflowId = Annotated[
    str,
    StringConstraints(max_length=128, pattern=r"^workflow-[a-z0-9][a-z0-9-]*$"),
]
type FaultId = Annotated[
    str,
    StringConstraints(max_length=128, pattern=r"^fault-[a-z0-9][a-z0-9-]*$"),
]
type ServiceName = Annotated[
    str, StringConstraints(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
]
type OperationName = Annotated[
    str, StringConstraints(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
]
type ParameterName = Annotated[
    str, StringConstraints(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
]
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
type Digest = Annotated[str, StringConstraints(pattern=_DIGEST_PATTERN)]
type NonNegativeInt = Annotated[int, Field(ge=0)]
type PositiveInt = Annotated[int, Field(gt=0)]

type CanonicalValue = (
    StrictBool
    | StrictInt
    | StrictStr
    | list["CanonicalValue"]
    | dict[str, "CanonicalValue"]
    | None
)
type ParameterMap = dict[ParameterName, CanonicalValue]
type EvidenceMap = dict[ParameterName, CanonicalValue]

_URL_SCHEME_PREFIX = compile_pattern(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_DIGEST_VALUE = compile_pattern(_DIGEST_PATTERN)


def _raise_immutable() -> NoReturn:
    raise TypeError("canonical contract values are immutable")


class _FrozenDict(dict[str, CanonicalValue]):
    """A serialization-compatible dictionary that blocks normal mutation APIs."""

    def __setitem__(self, key: str, value: CanonicalValue) -> NoReturn:
        _raise_immutable()

    def __delitem__(self, key: str) -> NoReturn:
        _raise_immutable()

    def clear(self) -> NoReturn:
        _raise_immutable()

    def pop(self, *args: object, **kwargs: object) -> NoReturn:
        _raise_immutable()

    def popitem(self) -> NoReturn:
        _raise_immutable()

    def setdefault(self, *args: object, **kwargs: object) -> NoReturn:
        _raise_immutable()

    def update(self, *args: object, **kwargs: object) -> NoReturn:
        _raise_immutable()

    # Typeshed couples this mutating operator to non-mutating ``dict.__or__``.
    def __ior__(self, value: object) -> Self:  # type: ignore[override,misc]
        _raise_immutable()


class _FrozenList(list[CanonicalValue]):
    """A serialization-compatible list that blocks normal mutation APIs."""

    @overload
    def __setitem__(self, key: SupportsIndex, value: CanonicalValue) -> NoReturn: ...

    @overload
    def __setitem__(self, key: slice, value: Iterable[CanonicalValue]) -> NoReturn: ...

    def __setitem__(
        self,
        key: SupportsIndex | slice,
        value: CanonicalValue | Iterable[CanonicalValue],
    ) -> NoReturn:
        _raise_immutable()

    def __delitem__(self, key: SupportsIndex | slice) -> NoReturn:
        _raise_immutable()

    # Typeshed couples this mutating operator to non-mutating ``list.__add__``.
    def __iadd__(  # type: ignore[override,misc]
        self, value: Iterable[CanonicalValue]
    ) -> Self:
        _raise_immutable()

    def __imul__(self, value: SupportsIndex) -> Self:
        _raise_immutable()

    def append(self, value: CanonicalValue) -> NoReturn:
        _raise_immutable()

    def clear(self) -> NoReturn:
        _raise_immutable()

    def extend(self, values: Iterable[CanonicalValue]) -> NoReturn:
        _raise_immutable()

    def insert(self, index: SupportsIndex, value: CanonicalValue) -> NoReturn:
        _raise_immutable()

    def pop(self, index: SupportsIndex = -1) -> NoReturn:
        _raise_immutable()

    def remove(self, value: CanonicalValue) -> NoReturn:
        _raise_immutable()

    def reverse(self) -> NoReturn:
        _raise_immutable()

    def sort(self, *args: object, **kwargs: object) -> NoReturn:
        _raise_immutable()


def _freeze_value(value: CanonicalValue) -> CanonicalValue:
    if isinstance(value, list):
        return _FrozenList(_freeze_value(item) for item in value)
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze_value(item) for key, item in value.items()})
    return value


class StrictModel(BaseModel):
    """Base for immutable contracts that reject coercion and extra fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )


class CommitPosition(StrEnum):
    BEFORE_COMMIT = "before_commit"
    AFTER_COMMIT_BEFORE_RESPONSE = "after_commit_before_response"
    ON_READ = "on_read"


class StateEffect(StrEnum):
    COMMIT = "commit"
    REJECT = "reject"
    DELAY = "delay"
    DUPLICATE_DELIVERY = "duplicate_delivery"
    CONCURRENT_CHANGE = "concurrent_change"


class ResponseEffect(StrEnum):
    RETURN = "return"
    DROP = "drop"
    TIMEOUT = "timeout"
    ERROR = "error"
    MUTATE = "mutate"


class ClaimStatus(StrEnum):
    COMPLETE = "complete"
    BLOCKED = "blocked"
    PARTIAL = "partial"


class EventKind(StrEnum):
    ACTION_PROPOSED = "action_proposed"
    AUTHORITY_CHECKED = "authority_checked"
    OPERATION_PREPARED = "operation_prepared"
    ATTEMPT_DISPATCHED = "attempt_dispatched"
    ATTEMPT_DELIVERED = "attempt_delivered"
    EFFECT_COMMITTED = "effect_committed"
    EFFECT_REJECTED = "effect_rejected"
    RESPONSE_RETURNED = "response_returned"
    RESPONSE_DROPPED = "response_dropped"
    RESPONSE_TIMED_OUT = "response_timed_out"
    RESPONSE_ERRORED = "response_errored"
    RESPONSE_MUTATED = "response_mutated"
    READ_OBSERVED = "read_observed"
    TOOL_SCHEMA_OBSERVED = "tool_schema_observed"
    VISIBILITY_CHANGED = "visibility_changed"
    CONCURRENT_CHANGE_APPLIED = "concurrent_change_applied"
    FAULT_FIRED = "fault_fired"
    STATE_TRANSITION = "state_transition"
    CLAIM_RECORDED = "claim_recorded"
    CONTAINMENT_BLOCKED = "containment_blocked"


def _reject_url_values(value: object) -> None:
    if isinstance(value, str):
        if not _DIGEST_VALUE.fullmatch(value) and _URL_SCHEME_PREFIX.match(
            value.lstrip()
        ):
            raise ValueError("URL schemes are forbidden in scenario-owned values")
        return
    if isinstance(value, list):
        for item in value:
            _reject_url_values(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            _reject_url_values(item)


def _validate_and_freeze_map(value: ParameterMap) -> ParameterMap:
    _reject_url_values(value)
    return cast(ParameterMap, _freeze_value(value))


class SemanticIntent(StrictModel):
    """Wire-independent meaning of one requested side effect."""

    service: ServiceName
    operation: OperationName
    parameters: ParameterMap

    @field_validator("parameters")
    @classmethod
    def validate_and_freeze_parameters(cls, value: ParameterMap) -> ParameterMap:
        return _validate_and_freeze_map(value)


class AuthorityGrant(StrictModel):
    """Immutable authorization for one semantic intent."""

    authority_id: AuthorityId
    subject_id: SubjectId
    service: ServiceName
    operation: OperationName
    semantic_intent_digest: Digest
    allowed_parameters: ParameterMap
    expires_at_tick: NonNegativeInt
    max_effects: PositiveInt
    allowed_compensation: ActionId | None = None

    @field_validator("allowed_parameters")
    @classmethod
    def validate_and_freeze_parameters(cls, value: ParameterMap) -> ParameterMap:
        return _validate_and_freeze_map(value)


class FaultTrigger(StrictModel):
    """A service operation matched by ordinal or by a preceding event kind."""

    service: ServiceName
    operation: OperationName
    call_ordinal: PositiveInt | None = None
    event_kind: EventKind | None = None

    @model_validator(mode="after")
    def require_one_selector(self) -> Self:
        if (self.call_ordinal is None) == (self.event_kind is None):
            raise ValueError("exactly one of call_ordinal or event_kind is required")
        return self


class VisibilityStep(StrictModel):
    tick: NonNegativeInt
    visible_revision: NonNegativeInt


class FaultSpec(StrictModel):
    """Declarative, commit-relative fault configuration."""

    fault_id: FaultId
    trigger: FaultTrigger
    commit_position: CommitPosition
    state_effect: StateEffect
    response_effect: ResponseEffect
    visibility_schedule: tuple[VisibilityStep, ...]
    required: bool
    seed: NonNegativeInt

    @field_validator("visibility_schedule")
    @classmethod
    def require_increasing_visibility_ticks(
        cls, value: tuple[VisibilityStep, ...]
    ) -> tuple[VisibilityStep, ...]:
        ticks = [step.tick for step in value]
        if ticks != sorted(set(ticks)):
            raise ValueError("visibility_schedule ticks must be unique and increasing")
        return value


class LabEvent(StrictModel):
    """One normalized append-only event record; sequence checks are ledger-owned."""

    seq: PositiveInt
    tick: NonNegativeInt
    kind: EventKind
    action_id: ActionId | None = None
    attempt_id: AttemptId | None = None
    operation_key: OperationKey | None = None
    effect_id: EffectId | None = None
    intent_digest: Digest | None = None
    authority_id: AuthorityId | None = None
    workflow_id: WorkflowId | None = None
    fault_id: FaultId | None = None
    evidence: EvidenceMap

    @field_validator("evidence")
    @classmethod
    def validate_and_freeze_evidence(cls, value: EvidenceMap) -> EvidenceMap:
        return _validate_and_freeze_map(value)


class ActionClaim(StrictModel):
    """Structured final claim for one action."""

    action_id: ActionId
    status: ClaimStatus
    effect_id: EffectId | None = None


__all__ = [
    "CURRENT_PROTOCOL_VERSION",
    "CURRENT_SCHEMA_VERSION",
    "ActionClaim",
    "ActionId",
    "AttemptId",
    "AuthorityGrant",
    "AuthorityId",
    "CanonicalValue",
    "ClaimStatus",
    "CommitPosition",
    "Digest",
    "EffectId",
    "EventKind",
    "FaultId",
    "FaultSpec",
    "FaultTrigger",
    "LabEvent",
    "OperationKey",
    "OperationName",
    "ProtocolVersion",
    "ResponseEffect",
    "RunId",
    "ScenarioId",
    "SchemaVersion",
    "SemanticIntent",
    "SemanticVersion",
    "ServiceName",
    "StateEffect",
    "SubjectId",
    "VisibilityStep",
    "WorkflowId",
]
