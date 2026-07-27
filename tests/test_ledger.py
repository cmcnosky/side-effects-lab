"""Integration and containment tests for the run-local SQLite ledgers."""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from side_effects_lab.canonical import canonical_json_bytes
from side_effects_lab.ledger import (
    DispatchRequiredError,
    DuplicateOperationError,
    EventSequenceError,
    LedgerClosedError,
    LedgerIntegrityError,
    LedgerPathError,
    ManagedEventError,
    OperationNotFoundError,
    SQLiteLedger,
)
from side_effects_lab.models import EventKind, LabEvent
from side_effects_lab.state_machine import (
    InvalidTransitionError,
    OperationIdentity,
    OperationState,
    TransitionCause,
    TransitionEvidence,
)

_RUN_ID = "run-" + "a" * 64
_OTHER_RUN_ID = "run-" + "b" * 64
_INTENT_DIGEST = "sha256:" + "1" * 64
_IDENTITY = OperationIdentity(
    action_id="action-create-issue",
    operation_key="op-sel001",
    intent_digest=_INTENT_DIGEST,
    authority_id="auth-create-issue",
)
_MANAGED_KINDS: tuple[EventKind, ...] = (
    EventKind.ACTION_PROPOSED,
    EventKind.OPERATION_PREPARED,
    EventKind.ATTEMPT_DISPATCHED,
    EventKind.STATE_TRANSITION,
)


def _run_root(tmp_path: Path, name: str = "run") -> Path:
    root = tmp_path / name
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root.resolve(strict=True)


def _ledger(tmp_path: Path, name: str = "run") -> SQLiteLedger:
    return SQLiteLedger.create(_run_root(tmp_path, name), _RUN_ID)


def _evidence(
    cause: TransitionCause,
    *,
    evidence_id: str | None = None,
    **overrides: bool,
) -> TransitionEvidence:
    facts = {
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
    facts.update(overrides)
    return TransitionEvidence(
        evidence_id=evidence_id or f"evidence-{cause.value.replace('_', '-')}",
        cause=cause,
        **facts,
    )


def _transition(
    ledger: SQLiteLedger,
    target: OperationState,
    cause: TransitionCause,
    *,
    tick: int,
    identity: OperationIdentity = _IDENTITY,
) -> None:
    ledger.transition(
        identity.action_id,
        target,
        evidence=_evidence(cause),
        identity=identity,
        tick=tick,
    )


def _register_and_authorize(ledger: SQLiteLedger) -> None:
    ledger.register_operation(_IDENTITY, tick=0)
    _transition(
        ledger,
        OperationState.AUTHORIZED,
        TransitionCause.AUTHORITY_CONFIRMED,
        tick=1,
    )


def _prepare(ledger: SQLiteLedger) -> None:
    _register_and_authorize(ledger)
    _transition(
        ledger,
        OperationState.PREPARED,
        TransitionCause.PREPARATION_DURABLE,
        tick=2,
    )


def _append_read(
    ledger: SQLiteLedger,
    *,
    seq: int,
    tick: int,
    evidence: dict[str, object] | None = None,
) -> LabEvent:
    return ledger.append_event(
        LabEvent(
            seq=seq,
            tick=tick,
            kind=EventKind.READ_OBSERVED,
            action_id="action-create-issue",
            operation_key="op-sel001",
            evidence=cast(Any, evidence or {}),
        )
    )


def _raw_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def test_create_uses_fixed_owner_only_database_and_close_is_idempotent(
    tmp_path: Path,
) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)

    assert ledger.db_path == root / "ledger.sqlite3"
    assert stat.S_ISREG(ledger.db_path.stat().st_mode)
    assert stat.S_IMODE(ledger.db_path.stat().st_mode) & 0o077 == 0
    assert ledger.run_id == _RUN_ID
    assert ledger.next_event_seq() == 1
    assert ledger.events() == ()

    ledger.close()
    ledger.close()
    with pytest.raises(LedgerClosedError):
        ledger.events()


def test_context_manager_closes_the_ledger(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    with ledger as opened:
        assert opened.next_event_seq() == 1

    with pytest.raises(LedgerClosedError):
        ledger.next_event_seq()


def test_relative_unresolved_missing_and_nondirectory_roots_are_rejected(
    tmp_path: Path,
) -> None:
    relative = Path("relative-run")
    with pytest.raises(LedgerPathError, match="absolute"):
        SQLiteLedger.create(relative, _RUN_ID)

    root = _run_root(tmp_path, "resolved")
    unresolved = root / ".." / root.name
    with pytest.raises(LedgerPathError, match="resolved"):
        SQLiteLedger.create(unresolved, _RUN_ID)

    with pytest.raises(LedgerPathError, match="exist"):
        SQLiteLedger.create((tmp_path / "missing").resolve(), _RUN_ID)

    regular_file = tmp_path / "not-a-directory"
    regular_file.write_text("sentinel", encoding="utf-8")
    with pytest.raises(LedgerPathError, match="directory"):
        SQLiteLedger.create(regular_file.resolve(), _RUN_ID)


def test_root_symlink_and_non_owner_only_permissions_are_rejected(
    tmp_path: Path,
) -> None:
    root = _run_root(tmp_path, "real")
    link = tmp_path / "linked"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(LedgerPathError, match="symlink"):
        SQLiteLedger.create(link, _RUN_ID)

    insecure = _run_root(tmp_path, "insecure")
    insecure.chmod(0o750)
    with pytest.raises(LedgerPathError, match="owner-only"):
        SQLiteLedger.create(insecure, _RUN_ID)


def test_database_symlink_cannot_escape_or_change_an_outside_sentinel(
    tmp_path: Path,
) -> None:
    root = _run_root(tmp_path)
    sentinel = tmp_path / "outside.sqlite3"
    sentinel.write_bytes(b"outside-sentinel")
    (root / "ledger.sqlite3").symlink_to(sentinel)

    with pytest.raises(LedgerPathError, match="already exists"):
        SQLiteLedger.create(root, _RUN_ID)

    assert sentinel.read_bytes() == b"outside-sentinel"


def test_database_hard_link_cannot_alias_a_database_outside_the_run_root(
    tmp_path: Path,
) -> None:
    outside_root = _run_root(tmp_path, "outside")
    outside = SQLiteLedger.create(outside_root, _RUN_ID)
    outside.close()
    inside_root = _run_root(tmp_path, "inside")
    os.link(outside_root / "ledger.sqlite3", inside_root / "ledger.sqlite3")

    with pytest.raises(LedgerPathError, match="hard-linked"):
        SQLiteLedger.reopen(inside_root, _RUN_ID)

    assert (outside_root / "ledger.sqlite3").stat().st_nlink == 2


@pytest.mark.parametrize("existing_kind", ["file", "directory"])
def test_create_never_overwrites_an_existing_fixed_path(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    root = _run_root(tmp_path)
    db_path = root / "ledger.sqlite3"
    if existing_kind == "file":
        db_path.write_bytes(b"unknown")
    else:
        db_path.mkdir()

    with pytest.raises(LedgerPathError, match="already exists"):
        SQLiteLedger.create(root, _RUN_ID)

    if existing_kind == "file":
        assert db_path.read_bytes() == b"unknown"
    else:
        assert db_path.is_dir()


def test_reopen_checks_run_identity_and_wrong_format(tmp_path: Path) -> None:
    root = _run_root(tmp_path, "valid")
    ledger = SQLiteLedger.create(root, _RUN_ID)
    ledger.close()

    reopened = SQLiteLedger.reopen(root, _RUN_ID)
    reopened.close()
    with pytest.raises(LedgerIntegrityError, match="run_id"):
        SQLiteLedger.reopen(root, _OTHER_RUN_ID)

    wrong_root = _run_root(tmp_path, "wrong")
    wrong_db = wrong_root / "ledger.sqlite3"
    wrong_db.write_bytes(b"not sqlite")
    wrong_db.chmod(0o600)
    with pytest.raises(LedgerIntegrityError, match="SQLite"):
        SQLiteLedger.reopen(wrong_root, _RUN_ID)


def test_append_event_enforces_contiguous_sequences_and_atomic_rejection(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    first = _append_read(ledger, seq=1, tick=3)
    original = ledger.events()

    assert first.seq == 1
    for invalid_seq in [1, 3]:
        with pytest.raises(EventSequenceError, match="expected 2"):
            _append_read(ledger, seq=invalid_seq, tick=3)
        assert ledger.events() == original


@pytest.mark.parametrize("invalid_seq", [0, -1])
def test_append_event_revalidates_constructed_invalid_sequences(
    tmp_path: Path,
    invalid_seq: int,
) -> None:
    ledger = _ledger(tmp_path)
    invalid = LabEvent.model_construct(
        seq=invalid_seq,
        tick=0,
        kind=EventKind.READ_OBSERVED,
        evidence={},
    )

    with pytest.raises(ValidationError):
        ledger.append_event(invalid)

    assert ledger.events() == ()


def test_append_event_rejects_tick_regression_without_mutation(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _append_read(ledger, seq=1, tick=4)
    original = ledger.events()

    with pytest.raises(EventSequenceError, match="backward"):
        _append_read(ledger, seq=2, tick=3)

    assert ledger.events() == original
    assert ledger.next_event_seq() == 2


@pytest.mark.parametrize("kind", _MANAGED_KINDS)
def test_public_append_cannot_bypass_managed_lifecycle_events(
    tmp_path: Path,
    kind: EventKind,
) -> None:
    ledger = _ledger(tmp_path)
    event = LabEvent(seq=1, tick=0, kind=kind, evidence={})

    with pytest.raises(ManagedEventError):
        ledger.append_event(event)

    assert ledger.events() == ()


def test_canonical_evidence_and_digest_ignore_mapping_insertion_order(
    tmp_path: Path,
) -> None:
    first = _ledger(tmp_path, "first")
    second = _ledger(tmp_path, "second")
    _append_read(
        first,
        seq=1,
        tick=0,
        evidence={"outer": {"b": 2, "a": 1}, "z": True},
    )
    _append_read(
        second,
        seq=1,
        tick=0,
        evidence={"z": True, "outer": {"a": 1, "b": 2}},
    )

    assert first.events() == second.events()
    assert first.event_digest() == second.event_digest()


def test_explicit_query_order_survives_reverse_unordered_selects(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    _append_read(ledger, seq=1, tick=0, evidence={"ordinal": 1})
    _append_read(ledger, seq=2, tick=0, evidence={"ordinal": 2})
    original = ledger.events()
    connection = cast(Any, ledger)._connection
    connection.execute("PRAGMA reverse_unordered_selects = ON")

    assert ledger.events() == original
    assert ledger.next_event_seq() == 3
    ledger.validate()


def test_operation_registration_is_atomic_and_duplicate_rolls_back(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    snapshot = ledger.register_operation(_IDENTITY, tick=0)
    original_events = ledger.events()

    assert snapshot.identity == _IDENTITY
    assert snapshot.state is OperationState.PROPOSED
    assert snapshot.created_event_seq == snapshot.updated_event_seq == 1
    assert snapshot.history == ()
    assert snapshot.attempt_ids == ()
    assert original_events[0].kind is EventKind.ACTION_PROPOSED

    with pytest.raises(DuplicateOperationError):
        ledger.register_operation(_IDENTITY, tick=1)

    assert ledger.events() == original_events
    assert ledger.operations() == (snapshot,)


def test_operations_are_ordered_by_creation_even_with_reverse_pragma(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    first = replace(_IDENTITY, action_id="action-first", operation_key="op-first")
    second = replace(_IDENTITY, action_id="action-second", operation_key="op-second")
    ledger.register_operation(first, tick=0)
    ledger.register_operation(second, tick=1)
    cast(Any, ledger)._connection.execute("PRAGMA reverse_unordered_selects = ON")

    assert [item.identity.action_id for item in ledger.operations()] == [
        "action-first",
        "action-second",
    ]


def test_preparation_is_durable_without_an_attempt(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _prepare(ledger)
    snapshot = ledger.operation(_IDENTITY.action_id)

    assert snapshot.state is OperationState.PREPARED
    assert snapshot.attempt_ids == ()
    assert [event.kind for event in ledger.events()] == [
        EventKind.ACTION_PROPOSED,
        EventKind.STATE_TRANSITION,
        EventKind.OPERATION_PREPARED,
        EventKind.STATE_TRANSITION,
    ]


def test_direct_in_flight_transition_cannot_bypass_dispatch_permit(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    _prepare(ledger)
    original_events = ledger.events()

    with pytest.raises(DispatchRequiredError, match="record_dispatch"):
        ledger.transition(
            _IDENTITY.action_id,
            OperationState.IN_FLIGHT,
            evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED),
            identity=_IDENTITY,
            tick=3,
        )

    assert ledger.events() == original_events
    assert ledger.operation(_IDENTITY.action_id).state is OperationState.PREPARED


def test_prepare_before_dispatch_crash_point_survives_reopen(tmp_path: Path) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    _prepare(ledger)
    ledger.close()

    reopened = SQLiteLedger.reopen(root, _RUN_ID)
    snapshot = reopened.operation(_IDENTITY.action_id)

    assert snapshot.state is OperationState.PREPARED
    assert snapshot.attempt_ids == ()
    assert all(
        event.kind is not EventKind.ATTEMPT_DISPATCHED for event in reopened.events()
    )


def test_dispatch_is_visible_before_service_callback_and_returns_permit(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    _prepare(ledger)
    permit = ledger.record_dispatch(
        _IDENTITY.action_id,
        attempt_id="attempt-1",
        evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED),
        identity=_IDENTITY,
        tick=3,
    )

    with _raw_connection(ledger.db_path) as observer:
        row = observer.execute(
            "SELECT kind, attempt_id FROM events WHERE seq = ? ORDER BY seq",
            (permit.dispatch_event_seq,),
        ).fetchone()
        operation = observer.execute(
            "SELECT state FROM operations WHERE action_id = ? ORDER BY action_id",
            (_IDENTITY.action_id,),
        ).fetchone()

    assert row is not None
    assert tuple(row) == (EventKind.ATTEMPT_DISPATCHED.value, "attempt-1")
    assert operation is not None
    assert operation["state"] == OperationState.IN_FLIGHT.value
    assert permit.run_id == _RUN_ID
    assert permit.action_id == _IDENTITY.action_id
    assert permit.attempt_id == "attempt-1"
    assert permit.dispatch_event_seq < permit.transition_event_seq


def test_post_permit_reopen_is_in_flight_without_implicit_retry(tmp_path: Path) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    _prepare(ledger)
    ledger.record_dispatch(
        _IDENTITY.action_id,
        attempt_id="attempt-1",
        evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED),
        identity=_IDENTITY,
        tick=3,
    )
    ledger.close()

    reopened = SQLiteLedger.reopen(root, _RUN_ID)
    snapshot = reopened.operation(_IDENTITY.action_id)

    assert snapshot.state is OperationState.IN_FLIGHT
    assert snapshot.attempt_ids == ("attempt-1",)
    assert (
        sum(event.kind is EventKind.ATTEMPT_DISPATCHED for event in reopened.events())
        == 1
    )


def test_same_action_duplicate_attempt_persists_violation(tmp_path: Path) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    _prepare(ledger)
    ledger.record_dispatch(
        _IDENTITY.action_id,
        attempt_id="attempt-1",
        evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED),
        identity=_IDENTITY,
        tick=3,
    )
    _transition(
        ledger,
        OperationState.RETRYABLE,
        TransitionCause.PRECOMMIT_REJECTION,
        tick=4,
    )

    with pytest.raises(InvalidTransitionError, match="already used"):
        ledger.record_dispatch(
            _IDENTITY.action_id,
            attempt_id="attempt-1",
            evidence=_evidence(TransitionCause.REDISPATCH_AUTHORIZED),
            identity=_IDENTITY,
            tick=5,
        )

    assert ledger.operation(_IDENTITY.action_id).state is OperationState.VIOLATION
    ledger.close()
    assert (
        SQLiteLedger.reopen(root, _RUN_ID).operation(_IDENTITY.action_id).state
        is OperationState.VIOLATION
    )


def test_cross_action_attempt_collision_rolls_back_second_dispatch(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    _prepare(ledger)
    ledger.record_dispatch(
        _IDENTITY.action_id,
        attempt_id="attempt-1",
        evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED),
        identity=_IDENTITY,
        tick=3,
    )
    second = replace(
        _IDENTITY,
        action_id="action-second",
        operation_key="op-second",
        authority_id="auth-second",
    )
    ledger.register_operation(second, tick=4)
    ledger.transition(
        second.action_id,
        OperationState.AUTHORIZED,
        evidence=_evidence(TransitionCause.AUTHORITY_CONFIRMED),
        identity=second,
        tick=5,
    )
    ledger.transition(
        second.action_id,
        OperationState.PREPARED,
        evidence=_evidence(TransitionCause.PREPARATION_DURABLE),
        identity=second,
        tick=6,
    )
    before = ledger.events()

    with pytest.raises(LedgerIntegrityError, match="collision"):
        ledger.record_dispatch(
            second.action_id,
            attempt_id="attempt-1",
            evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED),
            identity=second,
            tick=7,
        )

    assert ledger.events() == before
    assert ledger.operation(second.action_id).state is OperationState.PREPARED


def test_invalid_transition_commits_violation_then_rethrows_and_reopens(
    tmp_path: Path,
) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    ledger.register_operation(_IDENTITY, tick=0)

    with pytest.raises(InvalidTransitionError, match="attempted=COMPLETE"):
        ledger.transition(
            _IDENTITY.action_id,
            OperationState.COMPLETE,
            evidence=_evidence(TransitionCause.FRESH_POSTCONDITION),
            identity=_IDENTITY,
            tick=1,
        )

    snapshot = ledger.operation(_IDENTITY.action_id)
    assert snapshot.state is OperationState.VIOLATION
    assert len(snapshot.history) == 1
    assert snapshot.history[0].record.resulting_state is OperationState.VIOLATION
    ledger.close()

    reopened = SQLiteLedger.reopen(root, _RUN_ID)
    assert reopened.operation(_IDENTITY.action_id) == snapshot


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("action_id", "action-other"),
        ("operation_key", "op-other"),
        ("intent_digest", "sha256:" + "2" * 64),
        ("authority_id", "auth-other"),
    ],
)
def test_changed_candidate_identity_violation_replays_after_reopen(
    tmp_path: Path,
    field_name: str,
    replacement: str,
) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    ledger.register_operation(_IDENTITY, tick=0)
    changed = replace(_IDENTITY, **{field_name: replacement})

    with pytest.raises(InvalidTransitionError, match=field_name):
        ledger.transition(
            _IDENTITY.action_id,
            OperationState.AUTHORIZED,
            evidence=_evidence(TransitionCause.AUTHORITY_CONFIRMED),
            identity=changed,
            tick=1,
        )

    expected = ledger.operation(_IDENTITY.action_id)
    ledger.close()
    reopened = SQLiteLedger.reopen(root, _RUN_ID)

    assert reopened.operation(_IDENTITY.action_id) == expected
    assert expected.state is OperationState.VIOLATION


def test_already_violation_rejection_does_not_append_history(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.register_operation(_IDENTITY, tick=0)
    with pytest.raises(InvalidTransitionError):
        ledger.transition(
            _IDENTITY.action_id,
            OperationState.COMPLETE,
            evidence=_evidence(TransitionCause.FRESH_POSTCONDITION),
            identity=_IDENTITY,
            tick=1,
        )
    before = ledger.operation(_IDENTITY.action_id)
    before_events = ledger.events()

    with pytest.raises(InvalidTransitionError, match="VIOLATION is terminal"):
        ledger.transition(
            _IDENTITY.action_id,
            OperationState.AUTHORIZED,
            evidence=_evidence(TransitionCause.AUTHORITY_CONFIRMED),
            identity=_IDENTITY,
            tick=2,
        )

    assert ledger.operation(_IDENTITY.action_id) == before
    assert ledger.events() == before_events


def test_full_history_reconstructs_identically_after_reopen(tmp_path: Path) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    _prepare(ledger)
    ledger.record_dispatch(
        _IDENTITY.action_id,
        attempt_id="attempt-1",
        evidence=_evidence(TransitionCause.ATTEMPT_DELIVERED),
        identity=_IDENTITY,
        tick=3,
    )
    _transition(
        ledger,
        OperationState.INDETERMINATE,
        TransitionCause.AMBIGUOUS_OUTCOME,
        tick=4,
    )
    _transition(
        ledger,
        OperationState.RECONCILING,
        TransitionCause.RECONCILIATION_STARTED,
        tick=5,
    )
    _transition(
        ledger,
        OperationState.VERIFYING,
        TransitionCause.EXACT_EFFECT_FOUND,
        tick=6,
    )
    _transition(
        ledger,
        OperationState.COMPLETE,
        TransitionCause.FRESH_POSTCONDITION,
        tick=7,
    )
    expected = ledger.operation(_IDENTITY.action_id)
    expected_events = ledger.events()
    expected_digest = ledger.event_digest()
    ledger.close()

    reopened = SQLiteLedger.reopen(root, _RUN_ID)

    assert reopened.operation(_IDENTITY.action_id) == expected
    assert reopened.events() == expected_events
    assert reopened.event_digest() == expected_digest
    assert expected.state is OperationState.COMPLETE


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        (
            "UPDATE operations SET state = 'PREPARED' "
            "WHERE action_id = 'action-create-issue'",
            "cached operation state",
        ),
        (
            "UPDATE transitions SET cause = 'ambiguous_outcome' "
            "WHERE action_id = 'action-create-issue' AND ordinal = 1",
            "does not replay",
        ),
        (
            "UPDATE transitions SET ordinal = 3 "
            "WHERE action_id = 'action-create-issue' AND ordinal = 1",
            "ordinals",
        ),
    ],
)
def test_tampered_operation_or_transition_fails_closed_without_repair(
    tmp_path: Path,
    statement: str,
    message: str,
) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    _register_and_authorize(ledger)
    ledger.close()
    with _raw_connection(root / "ledger.sqlite3") as connection:
        connection.execute(statement)

    with pytest.raises(LedgerIntegrityError, match=message):
        SQLiteLedger.reopen(root, _RUN_ID)

    with _raw_connection(root / "ledger.sqlite3") as connection:
        if "operations" in statement:
            value = connection.execute(
                "SELECT state FROM operations ORDER BY action_id"
            ).fetchone()[0]
            assert value == "PREPARED"
        elif "cause" in statement:
            value = connection.execute(
                "SELECT cause FROM transitions ORDER BY ordinal"
            ).fetchone()[0]
            assert value == "ambiguous_outcome"
        else:
            value = connection.execute(
                "SELECT ordinal FROM transitions ORDER BY ordinal"
            ).fetchone()[0]
            assert value == 3


def test_tampered_event_sequence_and_foreign_key_fail_closed(tmp_path: Path) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    ledger.register_operation(_IDENTITY, tick=0)
    ledger.close()
    with _raw_connection(root / "ledger.sqlite3") as connection:
        connection.execute("UPDATE events SET seq = 2 WHERE seq = 1")

    with pytest.raises(LedgerIntegrityError, match="foreign-key"):
        SQLiteLedger.reopen(root, _RUN_ID)

    with _raw_connection(root / "ledger.sqlite3") as connection:
        assert (
            connection.execute("SELECT seq FROM events ORDER BY seq").fetchall()[0][0]
            == 2
        )


def test_tampered_event_json_fails_closed(tmp_path: Path) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    _append_read(ledger, seq=1, tick=0)
    ledger.close()
    with _raw_connection(root / "ledger.sqlite3") as connection:
        connection.execute(
            "UPDATE events SET evidence_json = ? WHERE seq = 1",
            (b"{not-json",),
        )

    with pytest.raises(LedgerIntegrityError, match="event"):
        SQLiteLedger.reopen(root, _RUN_ID)


def test_semantically_equal_noncanonical_event_json_fails_closed(
    tmp_path: Path,
) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    _append_read(ledger, seq=1, tick=0, evidence={"a": 1, "b": 2})
    ledger.close()
    noncanonical = b'{ "b": 2, "a": 1 }'
    with _raw_connection(root / "ledger.sqlite3") as connection:
        connection.execute(
            "UPDATE events SET evidence_json = ? WHERE seq = 1",
            (noncanonical,),
        )

    with pytest.raises(LedgerIntegrityError, match="not canonical"):
        SQLiteLedger.reopen(root, _RUN_ID)

    with _raw_connection(root / "ledger.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT evidence_json FROM events ORDER BY seq"
            ).fetchone()[0]
            == noncanonical
        )


def test_forged_transition_after_terminal_violation_fails_replay(
    tmp_path: Path,
) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    ledger.register_operation(_IDENTITY, tick=0)
    with pytest.raises(InvalidTransitionError):
        ledger.transition(
            _IDENTITY.action_id,
            OperationState.COMPLETE,
            evidence=_evidence(TransitionCause.FRESH_POSTCONDITION),
            identity=_IDENTITY,
            tick=1,
        )
    ledger.close()

    with _raw_connection(root / "ledger.sqlite3") as connection:
        connection.execute(
            """
            INSERT INTO events (
                seq, tick, kind, action_id, attempt_id, operation_key,
                effect_id, intent_digest, authority_id, workflow_id,
                fault_id, evidence_json
            ) VALUES (?, ?, ?, ?, NULL, ?, NULL, ?, ?, NULL, NULL, ?)
            """,
            (
                3,
                2,
                EventKind.STATE_TRANSITION.value,
                _IDENTITY.action_id,
                _IDENTITY.operation_key,
                _IDENTITY.intent_digest,
                _IDENTITY.authority_id,
                canonical_json_bytes({}),
            ),
        )
        connection.execute(
            """
            INSERT INTO transitions (
                action_id, ordinal, event_seq, source_state, attempted_state,
                resulting_state, candidate_action_id, candidate_operation_key,
                candidate_intent_digest, candidate_authority_id, evidence_id,
                cause, fresh, authoritative, exact_identity,
                postcondition_verified, cardinality_valid, attempt_id,
                violation_reason
            ) VALUES (?, 2, 3, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0,
                      NULL, ?)
            """,
            (
                _IDENTITY.action_id,
                OperationState.VIOLATION.value,
                OperationState.AUTHORIZED.value,
                OperationState.VIOLATION.value,
                _IDENTITY.action_id,
                _IDENTITY.operation_key,
                _IDENTITY.intent_digest,
                _IDENTITY.authority_id,
                "evidence-after-violation",
                TransitionCause.AUTHORITY_CONFIRMED.value,
                "VIOLATION is terminal",
            ),
        )
        connection.execute(
            """
            UPDATE operations SET updated_event_seq = 3
            WHERE action_id = ?
            """,
            (_IDENTITY.action_id,),
        )

    with pytest.raises(LedgerIntegrityError, match="did not append"):
        SQLiteLedger.reopen(root, _RUN_ID)


def test_orphan_managed_event_fails_closed_without_removal(tmp_path: Path) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    ledger.close()
    with _raw_connection(root / "ledger.sqlite3") as connection:
        connection.execute(
            """
            INSERT INTO events (
                seq, tick, kind, action_id, attempt_id, operation_key,
                effect_id, intent_digest, authority_id, workflow_id,
                fault_id, evidence_json
            ) VALUES (1, 0, 'state_transition', NULL, NULL, NULL,
                      NULL, NULL, NULL, NULL, NULL, ?)
            """,
            (b"{}",),
        )

    with pytest.raises(LedgerIntegrityError, match="orphaned"):
        SQLiteLedger.reopen(root, _RUN_ID)

    with _raw_connection(root / "ledger.sqlite3") as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM events ORDER BY seq").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        (
            "UPDATE operations SET updated_event_seq = 1 "
            "WHERE action_id = 'action-create-issue'",
            "updated sequence",
        ),
        (
            "UPDATE events SET operation_key = 'op-other' WHERE seq = 1",
            "proposal event",
        ),
        (
            "UPDATE events SET evidence_json = x'7b7d' WHERE seq = 2",
            "state-transition event",
        ),
    ],
)
def test_tampered_managed_event_links_fail_closed(
    tmp_path: Path,
    statement: str,
    message: str,
) -> None:
    root = _run_root(tmp_path)
    ledger = SQLiteLedger.create(root, _RUN_ID)
    _register_and_authorize(ledger)
    ledger.close()
    with _raw_connection(root / "ledger.sqlite3") as connection:
        connection.execute(statement)

    with pytest.raises(LedgerIntegrityError, match=message):
        SQLiteLedger.reopen(root, _RUN_ID)


def test_api_boundaries_reject_wrong_types_and_unknown_operations(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)

    with pytest.raises(ValidationError):
        ledger.operation(cast(Any, "wrong-prefix"))
    with pytest.raises(TypeError, match="integer"):
        ledger.register_operation(_IDENTITY, tick=cast(Any, True))
    with pytest.raises(OperationNotFoundError, match="not registered"):
        ledger.operation("action-missing")
