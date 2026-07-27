"""Every closed enum accepts its declared members and rejects unknown ones.

Traceability: Architecture "Frozen base-contract conventions" (closed event-kind
set; fault effect vocabularies; claim status) and the T002B matrix "Enums" row.
"""

from enum import StrEnum

import pytest
from pydantic import TypeAdapter, ValidationError

from side_effects_lab.models import (
    ClaimStatus,
    CommitPosition,
    EventKind,
    ResponseEffect,
    StateEffect,
)

ENUMS: list[type[StrEnum]] = [
    CommitPosition,
    StateEffect,
    ResponseEffect,
    ClaimStatus,
    EventKind,
]

EXPECTED_MEMBERS: dict[str, set[str]] = {
    "CommitPosition": {"before_commit", "after_commit_before_response", "on_read"},
    "StateEffect": {
        "commit",
        "reject",
        "delay",
        "duplicate_delivery",
        "concurrent_change",
    },
    "ResponseEffect": {"return", "drop", "timeout", "error", "mutate"},
    "ClaimStatus": {"complete", "blocked", "partial"},
}


@pytest.mark.parametrize("enum_cls", ENUMS, ids=[e.__name__ for e in ENUMS])
def test_enum_accepts_every_declared_member(enum_cls: type[StrEnum]) -> None:
    adapter: TypeAdapter[StrEnum] = TypeAdapter(enum_cls)
    for member in enum_cls:
        assert adapter.validate_json(f'"{member.value}"') is member


@pytest.mark.parametrize("enum_cls", ENUMS, ids=[e.__name__ for e in ENUMS])
@pytest.mark.parametrize("bogus", ["", "unknown", "COMMIT", "commit ", "0"])
def test_enum_rejects_unknown_member(enum_cls: type[StrEnum], bogus: str) -> None:
    adapter: TypeAdapter[StrEnum] = TypeAdapter(enum_cls)
    with pytest.raises(ValidationError) as exc_info:
        adapter.validate_json(f'"{bogus}"')
    assert exc_info.value.errors()[0]["type"] == "enum"


@pytest.mark.parametrize("enum_cls", ENUMS, ids=[e.__name__ for e in ENUMS])
def test_enum_membership_matches_frozen_expectation(enum_cls: type[StrEnum]) -> None:
    values = {member.value for member in enum_cls}
    expected = EXPECTED_MEMBERS.get(enum_cls.__name__)
    if expected is not None:
        assert values == expected
    # Every enum value must be a lowercase snake token so canonical JSON is stable.
    assert all(value == value.lower() and " " not in value for value in values)


def test_event_kind_covers_the_documented_lifecycle() -> None:
    values = {member.value for member in EventKind}
    for required in {
        "action_proposed",
        "authority_checked",
        "operation_prepared",
        "attempt_dispatched",
        "attempt_delivered",
        "effect_committed",
        "effect_rejected",
        "fault_fired",
        "state_transition",
        "claim_recorded",
        "containment_blocked",
    }:
        assert required in values
