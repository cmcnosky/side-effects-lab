"""Adversarial coverage of every public identifier alias.

Traceability: Architecture "Frozen base-contract conventions" (core identities)
and the T002B matrix "Identifiers" row. Each alias is exercised through its own
``TypeAdapter`` because several identifier types are not embedded in a T002A
model field yet are part of the frozen public grammar.
"""

from collections.abc import Callable
from typing import NamedTuple

import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic_core import ErrorDetails

from side_effects_lab.models import (
    ActionId,
    AttemptId,
    AuthorityId,
    EffectId,
    FaultId,
    OperationKey,
    OperationName,
    ParameterName,
    RunId,
    ScenarioId,
    ServiceName,
    SubjectId,
    WorkflowId,
)


class IdCase(NamedTuple):
    name: str
    adapter: TypeAdapter[str]
    valid: str
    wrong_grammar: str
    max_length: int
    length_bounded_by_pattern: bool


IDENTIFIERS: list[IdCase] = [
    IdCase("ScenarioId", TypeAdapter(ScenarioId), "SEL-001", "sel-001", 7, True),
    IdCase("RunId", TypeAdapter(RunId), "run-sel001-1", "sel001", 128, False),
    IdCase(
        "SubjectId", TypeAdapter(SubjectId), "reconcile-first", "Reconcile", 128, False
    ),
    IdCase(
        "ActionId",
        TypeAdapter(ActionId),
        "action-create-issue",
        "op-create",
        128,
        False,
    ),
    IdCase(
        "OperationKey",
        TypeAdapter(OperationKey),
        "op-sel001",
        "action-sel001",
        128,
        False,
    ),
    IdCase("AttemptId", TypeAdapter(AttemptId), "attempt-1", "try-1", 128, False),
    IdCase("EffectId", TypeAdapter(EffectId), "issue-1", "1issue", 128, False),
    IdCase(
        "AuthorityId",
        TypeAdapter(AuthorityId),
        "auth-create",
        "grant-create",
        128,
        False,
    ),
    IdCase(
        "WorkflowId",
        TypeAdapter(WorkflowId),
        "workflow-sel001",
        "flow-sel001",
        128,
        False,
    ),
    IdCase("FaultId", TypeAdapter(FaultId), "fault-vanish", "bug-vanish", 128, False),
    IdCase("ServiceName", TypeAdapter(ServiceName), "dummy_github", "Dummy", 64, False),
    IdCase(
        "OperationName",
        TypeAdapter(OperationName),
        "create_issue",
        "1create",
        64,
        False,
    ),
    IdCase(
        "ParameterName", TypeAdapter(ParameterName), "issue_title", "Title", 64, False
    ),
]

# Strings that must fail every identifier grammar: empty, whitespace, control,
# traversal, and embedded separators.
UNIVERSAL_INVALID: list[tuple[str, str]] = [
    ("empty", ""),
    ("leading_space", " action-create"),
    ("trailing_space", "action-create "),
    ("internal_space", "action create"),
    ("tab", "action-\tcreate"),
    ("newline", "action-create\n"),
    ("null_byte", "action-\x00create"),
    ("traversal", "../etc/passwd"),
    ("dot_traversal", "..\\action"),
]

_IDS = [case.name for case in IDENTIFIERS]


@pytest.mark.parametrize("case", IDENTIFIERS, ids=_IDS)
def test_identifier_accepts_canonical_token(case: IdCase) -> None:
    assert case.adapter.validate_python(case.valid) == case.valid


@pytest.mark.parametrize("case", IDENTIFIERS, ids=_IDS)
@pytest.mark.parametrize(
    "label,value", UNIVERSAL_INVALID, ids=[n for n, _ in UNIVERSAL_INVALID]
)
def test_identifier_rejects_unsafe_strings(
    case: IdCase, label: str, value: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        case.adapter.validate_python(value)
    # Short-max types (e.g. ScenarioId) may report length before pattern; both
    # are intended grammar rejections.
    assert exc_info.value.errors()[0]["type"] in {
        "string_pattern_mismatch",
        "string_too_long",
    }


@pytest.mark.parametrize("case", IDENTIFIERS, ids=_IDS)
def test_identifier_rejects_wrong_grammar(case: IdCase) -> None:
    with pytest.raises(ValidationError) as exc_info:
        case.adapter.validate_python(case.wrong_grammar)
    assert exc_info.value.errors()[0]["type"] == "string_pattern_mismatch"


@pytest.mark.parametrize("case", IDENTIFIERS, ids=_IDS)
@pytest.mark.parametrize("wrong_type", [123, b"action-create", None, 1.5, True])
def test_identifier_rejects_wrong_type_without_coercion(
    case: IdCase, wrong_type: object
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        case.adapter.validate_python(wrong_type)
    assert exc_info.value.errors()[0]["type"] == "string_type"


@pytest.mark.parametrize(
    "case",
    [c for c in IDENTIFIERS if not c.length_bounded_by_pattern],
    ids=[c.name for c in IDENTIFIERS if not c.length_bounded_by_pattern],
)
def test_identifier_enforces_max_length(case: IdCase) -> None:
    prefix = case.valid.split("-")[0].split("_")[0]
    too_long = prefix + "a" * case.max_length
    assert len(too_long) > case.max_length
    with pytest.raises(ValidationError) as exc_info:
        case.adapter.validate_python(too_long)
    assert exc_info.value.errors()[0]["type"] in {
        "string_too_long",
        "string_pattern_mismatch",
    }


def test_scenario_id_length_is_bounded() -> None:
    adapter: TypeAdapter[str] = TypeAdapter(ScenarioId)
    with pytest.raises(ValidationError) as exc_info:
        adapter.validate_python("SEL-0001")
    assert exc_info.value.errors()[0]["type"] in {
        "string_too_long",
        "string_pattern_mismatch",
    }


def test_effect_id_requires_leading_letter() -> None:
    adapter: TypeAdapter[str] = TypeAdapter(EffectId)
    assert adapter.validate_python("a1") == "a1"
    with pytest.raises(ValidationError) as exc_info:
        adapter.validate_python("1a")
    assert exc_info.value.errors()[0]["type"] == "string_pattern_mismatch"


def test_helper_reports_missing_location(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    # Guards the shared helper itself: a wrong location assertion must fail loudly.
    adapter: TypeAdapter[str] = TypeAdapter(ActionId)
    with pytest.raises(ValidationError) as exc_info:
        adapter.validate_python(123)
    with pytest.raises(AssertionError):
        assert_error(exc_info, ("nonexistent",))
