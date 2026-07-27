"""Strict, versioned primitives shared by Side Effects Lab contracts."""

from collections.abc import Iterator, Mapping
from enum import StrEnum
from re import compile as compile_pattern
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
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
    StrictStr,
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
    StrictStr, StringConstraints(max_length=7, pattern=r"^SEL-[0-9]{3}$")
]
type RunId = Annotated[
    StrictStr,
    StringConstraints(max_length=128, pattern=r"^run-[a-z0-9][a-z0-9-]*$"),
]
type SubjectId = Annotated[
    StrictStr,
    StringConstraints(max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$"),
]
type ActionId = Annotated[
    StrictStr,
    StringConstraints(max_length=128, pattern=r"^action-[a-z0-9][a-z0-9-]*$"),
]
type OperationKey = Annotated[
    StrictStr,
    StringConstraints(max_length=128, pattern=r"^op-[a-z0-9][a-z0-9-]*$"),
]
type AttemptId = Annotated[
    StrictStr,
    StringConstraints(max_length=128, pattern=r"^attempt-[a-z0-9][a-z0-9-]*$"),
]
type EffectId = Annotated[
    StrictStr,
    StringConstraints(max_length=128, pattern=r"^[a-z][a-z0-9-]*$"),
]
type AuthorityId = Annotated[
    StrictStr,
    StringConstraints(max_length=128, pattern=r"^auth-[a-z0-9][a-z0-9-]*$"),
]
type WorkflowId = Annotated[
    StrictStr,
    StringConstraints(max_length=128, pattern=r"^workflow-[a-z0-9][a-z0-9-]*$"),
]
type FaultId = Annotated[
    StrictStr,
    StringConstraints(max_length=128, pattern=r"^fault-[a-z0-9][a-z0-9-]*$"),
]
type ServiceName = Annotated[
    StrictStr,
    StringConstraints(max_length=64, pattern=r"^[a-z][a-z0-9_]*$"),
]
type OperationName = Annotated[
    StrictStr,
    StringConstraints(max_length=64, pattern=r"^[a-z][a-z0-9_]*$"),
]
type ParameterName = Annotated[
    StrictStr,
    StringConstraints(max_length=64, pattern=r"^[a-z][a-z0-9_]*$"),
]
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
type Digest = Annotated[StrictStr, StringConstraints(pattern=_DIGEST_PATTERN)]
type NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
type PositiveInt = Annotated[StrictInt, Field(gt=0)]

type CanonicalValue = (
    StrictBool
    | StrictInt
    | StrictStr
    | list["CanonicalValue"]
    | dict[str, "CanonicalValue"]
    | None
)
type FrozenCanonicalValue = (
    bool | int | str | tuple["FrozenCanonicalValue", ...] | FrozenMap | None
)

_URL_SCHEME_PREFIX = compile_pattern(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_DIGEST_VALUE = compile_pattern(_DIGEST_PATTERN)


class FrozenMap(Mapping[str, FrozenCanonicalValue]):
    """Read-only mapping used for validated recursive contract values."""

    __slots__ = ("__data",)
    __data: Mapping[str, FrozenCanonicalValue]

    def __init__(self, values: Mapping[str, FrozenCanonicalValue]) -> None:
        object.__setattr__(self, "_FrozenMap__data", MappingProxyType(dict(values)))

    def __setattr__(self, name: str, value: object) -> None:
        raise TypeError("canonical contract values are immutable")

    def __getitem__(self, key: str) -> FrozenCanonicalValue:
        return self.__data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.__data)

    def __len__(self) -> int:
        return len(self.__data)

    def __repr__(self) -> str:
        return f"FrozenMap({dict(self.items())!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Mapping) and dict(self.items()) == dict(other.items())

    def __hash__(self) -> int:
        return hash(tuple(sorted(self.__data.items())))

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        return self


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


def _freeze_value(value: CanonicalValue) -> FrozenCanonicalValue:
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, dict):
        return FrozenMap({key: _freeze_value(item) for key, item in value.items()})
    return value


def _thaw_value(value: FrozenCanonicalValue) -> CanonicalValue:
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    if isinstance(value, FrozenMap):
        return {key: _thaw_value(item) for key, item in value.items()}
    return value


def _serialize_frozen_map(value: FrozenMap) -> dict[str, CanonicalValue]:
    thawed = _thaw_value(value)
    if not isinstance(thawed, dict):
        raise TypeError("frozen map serialization did not produce an object")
    return thawed


def _prepare_map_input(value: object) -> object:
    if isinstance(value, FrozenMap):
        return _serialize_frozen_map(value)
    return value


def _validate_and_freeze_map(
    value: Mapping[ParameterName, CanonicalValue],
) -> Mapping[ParameterName, CanonicalValue]:
    mutable_value = dict(value)
    _reject_url_values(mutable_value)
    frozen = _freeze_value(mutable_value)
    if not isinstance(frozen, FrozenMap):
        raise TypeError("canonical map validation did not produce an object")
    return cast(Mapping[ParameterName, CanonicalValue], frozen)


type _InputMap = dict[ParameterName, CanonicalValue]
type ParameterMap = Annotated[
    Mapping[ParameterName, CanonicalValue],
    BeforeValidator(_prepare_map_input),
    AfterValidator(_validate_and_freeze_map),
    PlainSerializer(_serialize_frozen_map, return_type=_InputMap),
]
type EvidenceMap = ParameterMap


class StrictModel(BaseModel):
    """Base for immutable contracts that reject coercion and extra fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if update:
            raise TypeError("frozen contract models cannot be updated by copy")
        return super().model_copy(deep=deep)


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


class SemanticIntent(StrictModel):
    """Wire-independent meaning of one requested side effect."""

    service: ServiceName
    operation: OperationName
    parameters: ParameterMap


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


class FaultTrigger(StrictModel):
    """A service operation matched by ordinal or by a preceding event kind."""

    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [
                {
                    "required": ["call_ordinal"],
                    "properties": {
                        "call_ordinal": {"not": {"type": "null"}},
                        "event_kind": {"type": "null"},
                    },
                },
                {
                    "required": ["event_kind"],
                    "properties": {
                        "call_ordinal": {"type": "null"},
                        "event_kind": {"not": {"type": "null"}},
                    },
                },
            ]
        }
    )

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
    visibility_schedule: tuple[VisibilityStep, ...] = Field(
        description=(
            "Logical visibility ticks; model validation requires unique, "
            "strictly increasing tick values."
        )
    )
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
    "EvidenceMap",
    "FaultId",
    "FaultSpec",
    "FaultTrigger",
    "FrozenCanonicalValue",
    "FrozenMap",
    "LabEvent",
    "NonNegativeInt",
    "OperationKey",
    "OperationName",
    "ParameterMap",
    "PositiveInt",
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
