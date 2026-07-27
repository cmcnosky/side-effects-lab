"""Focused positive and boundary tests for the frozen T002A primitives."""

from typing import cast

import pytest
from pydantic import ValidationError

from side_effects_lab.canonical import canonical_digest
from side_effects_lab.models import (
    ActionClaim,
    AuthorityGrant,
    CanonicalValue,
    ClaimStatus,
    CommitPosition,
    EventKind,
    FaultSpec,
    FaultTrigger,
    LabEvent,
    ResponseEffect,
    SemanticIntent,
    StateEffect,
    VisibilityStep,
)


def sample_intent() -> SemanticIntent:
    return SemanticIntent(
        service="dummy_github",
        operation="create_issue",
        parameters={"labels": ["docs"], "title": "Update docs"},
    )


def test_semantic_intent_is_wire_independent_and_digestible() -> None:
    intent = sample_intent()

    assert canonical_digest(intent).startswith("sha256:")
    assert len(canonical_digest(intent)) == 71


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid/hook",
        " https:external",
        "ftp:external",
        "file:x",
        "urn:example:test",
        "javascript:alert(1)",
    ],
)
def test_semantic_intent_rejects_urls_and_unknown_fields(url: str) -> None:
    with pytest.raises(ValidationError, match="URL schemes are forbidden"):
        SemanticIntent(
            service="dummy_github",
            operation="create_issue",
            parameters={"callback": ["nested", {"target": url}]},
        )


def test_semantic_parameters_are_deeply_immutable_and_digest_stable() -> None:
    original: dict[str, CanonicalValue] = {"items": [{"name": "docs"}]}
    intent = SemanticIntent(
        service="dummy_github",
        operation="create_issue",
        parameters=original,
    )
    digest = canonical_digest(intent)
    items = cast(list[CanonicalValue], intent.parameters["items"])
    first = cast(dict[str, CanonicalValue], items[0])

    with pytest.raises(TypeError, match="doesn't apply"):
        list.append(items, "changed")
    with pytest.raises(TypeError, match="requires a 'dict'"):
        dict.__setitem__(first, "name", "changed")
    with pytest.raises(TypeError, match="doesn't apply"):
        dict.update(
            cast(dict[str, CanonicalValue], intent.parameters),
            {"x": 1},
        )
    with pytest.raises(TypeError, match="cannot be updated by copy"):
        intent.model_copy(update={"parameters": {"items": []}})

    cast(list[CanonicalValue], original["items"]).append("outside-change")
    assert canonical_digest(intent) == digest

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SemanticIntent.model_validate(
            {
                "service": "dummy_github",
                "operation": "create_issue",
                "parameters": {},
                "extra": True,
            }
        )


def test_authority_grant_uses_the_semantic_intent_digest() -> None:
    intent = sample_intent()
    grant = AuthorityGrant(
        authority_id="auth-create-issue",
        subject_id="reconcile-first",
        service=intent.service,
        operation=intent.operation,
        semantic_intent_digest=canonical_digest(intent),
        allowed_parameters=intent.parameters,
        expires_at_tick=12,
        max_effects=1,
    )

    assert grant.max_effects == 1
    assert grant.allowed_compensation is None
    with pytest.raises(TypeError, match="doesn't apply"):
        dict.update(
            cast(dict[str, CanonicalValue], grant.allowed_parameters),
            {"title": "changed"},
        )


def test_fault_contract_round_trips_strict_json() -> None:
    fault = FaultSpec.model_validate_json(
        """{
          "fault_id":"fault-vanished-receipt",
          "trigger":{"service":"dummy_github","operation":"create_issue","call_ordinal":1},
          "commit_position":"after_commit_before_response",
          "state_effect":"commit",
          "response_effect":"drop",
          "visibility_schedule":[{"tick":2,"visible_revision":1}],
          "required":true,
          "seed":17
        }"""
    )

    assert fault.commit_position is CommitPosition.AFTER_COMMIT_BEFORE_RESPONSE
    assert fault.state_effect is StateEffect.COMMIT
    assert fault.response_effect is ResponseEffect.DROP
    assert FaultSpec.model_validate_json(fault.model_dump_json()) == fault


def test_fault_trigger_requires_exactly_one_selector() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        FaultTrigger(service="dummy_github", operation="create_issue")

    with pytest.raises(ValidationError, match="exactly one"):
        FaultTrigger(
            service="dummy_github",
            operation="create_issue",
            call_ordinal=1,
            event_kind=EventKind.ATTEMPT_DISPATCHED,
        )


def test_visibility_schedule_requires_increasing_unique_ticks() -> None:
    with pytest.raises(ValidationError, match="unique and increasing"):
        FaultSpec(
            fault_id="fault-bad-visibility",
            trigger=FaultTrigger(
                service="dummy_github", operation="create_issue", call_ordinal=1
            ),
            commit_position=CommitPosition.ON_READ,
            state_effect=StateEffect.DELAY,
            response_effect=ResponseEffect.RETURN,
            visibility_schedule=(
                VisibilityStep(tick=2, visible_revision=1),
                VisibilityStep(tick=1, visible_revision=2),
            ),
            required=True,
            seed=1,
        )


def test_event_and_claim_primitives_are_strict() -> None:
    event = LabEvent(
        seq=1,
        tick=0,
        kind=EventKind.ATTEMPT_DISPATCHED,
        action_id="action-create-issue",
        attempt_id="attempt-1",
        operation_key="op-sel001",
        authority_id="auth-create-issue",
        evidence={},
    )
    claim = ActionClaim(
        action_id="action-create-issue",
        status=ClaimStatus.BLOCKED,
    )

    assert event.seq == 1
    assert claim.effect_id is None
    with pytest.raises(TypeError, match="doesn't apply"):
        dict.update(
            cast(dict[str, CanonicalValue], event.evidence),
            {"unexpected": "value"},
        )


def test_event_evidence_rejects_url_schemes_but_allows_digests() -> None:
    digest = canonical_digest({"safe": True})
    event = LabEvent(
        seq=1,
        tick=0,
        kind=EventKind.READ_OBSERVED,
        evidence={"digest": digest},
    )
    assert event.evidence["digest"] == digest

    with pytest.raises(ValidationError, match="URL schemes are forbidden"):
        LabEvent(
            seq=1,
            tick=0,
            kind=EventKind.READ_OBSERVED,
            evidence={"target": ["nested", "https://example.invalid"]},
        )
