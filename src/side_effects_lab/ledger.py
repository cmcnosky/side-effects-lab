"""Durable, deterministic event and operation ledgers backed by SQLite."""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from json import JSONDecodeError, loads
from pathlib import Path
from typing import Any, Self, cast

from pydantic import TypeAdapter, ValidationError

from side_effects_lab.canonical import canonical_digest, canonical_json_bytes
from side_effects_lab.models import (
    CURRENT_SCHEMA_VERSION,
    ActionId,
    AttemptId,
    Digest,
    EventKind,
    LabEvent,
    RunId,
)
from side_effects_lab.state_machine import (
    InvalidTransitionError,
    OperationIdentity,
    OperationState,
    OperationStateMachine,
    TransitionCause,
    TransitionEvidence,
    TransitionRecord,
)

_ACTION_ID_ADAPTER: TypeAdapter[ActionId] = TypeAdapter(ActionId)
_ATTEMPT_ID_ADAPTER: TypeAdapter[AttemptId] = TypeAdapter(AttemptId)
_RUN_ID_ADAPTER: TypeAdapter[RunId] = TypeAdapter(RunId)
_LEDGER_FILENAME = "ledger.sqlite3"
_LEDGER_SCHEMA_VERSION = 1
_MANAGED_EVENT_KINDS = frozenset(
    {
        EventKind.ACTION_PROPOSED,
        EventKind.OPERATION_PREPARED,
        EventKind.ATTEMPT_DISPATCHED,
        EventKind.STATE_TRANSITION,
    }
)
_EVENT_COLUMNS = """
    seq, tick, kind, action_id, attempt_id, operation_key, effect_id,
    intent_digest, authority_id, workflow_id, fault_id, evidence_json
"""


class LedgerError(RuntimeError):
    """Base class for ledger failures."""


class LedgerPathError(LedgerError):
    """The run root or fixed database path is unsafe."""


class EventSequenceError(LedgerError):
    """An event would break contiguous sequence or monotonic tick ordering."""


class DuplicateOperationError(LedgerError):
    """An action identifier was already registered."""


class OperationNotFoundError(LedgerError):
    """An action identifier is not present in the operation ledger."""


class DispatchRequiredError(LedgerError):
    """An IN_FLIGHT transition attempted to bypass the dispatch permit."""


class ManagedEventError(LedgerError):
    """A caller attempted to append a lifecycle event outside its transaction."""


class LedgerClosedError(LedgerError):
    """An operation was attempted after the ledger closed."""


class LedgerIntegrityError(LedgerError):
    """Persisted state failed closed validation."""


@dataclass(frozen=True, slots=True)
class PersistedTransition:
    record: TransitionRecord
    evidence: TransitionEvidence
    event_seq: int


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    identity: OperationIdentity
    state: OperationState
    created_event_seq: int
    updated_event_seq: int
    attempt_ids: tuple[AttemptId, ...]
    history: tuple[PersistedTransition, ...]


@dataclass(frozen=True, slots=True)
class DispatchPermit:
    run_id: RunId
    action_id: ActionId
    attempt_id: AttemptId
    dispatch_event_seq: int
    transition_event_seq: int


class SQLiteLedger:
    """One run-local append-only event and operation ledger."""

    __slots__ = ("_closed", "_connection", "_db_path", "_run_id", "_run_root")

    def __init__(
        self,
        run_root: Path,
        db_path: Path,
        run_id: RunId,
        connection: sqlite3.Connection,
    ) -> None:
        self._run_root = run_root
        self._db_path = db_path
        self._run_id = run_id
        self._connection = connection
        self._closed = False

    @classmethod
    def create(cls, run_root: Path, run_id: RunId) -> Self:
        validated_root = _validated_run_root(run_root)
        validated_run_id = _RUN_ID_ADAPTER.validate_python(run_id)
        db_path = validated_root / _LEDGER_FILENAME
        _require_absent_database(db_path)

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            file_descriptor = os.open(db_path, flags, 0o600)
        except OSError as error:
            raise LedgerPathError(
                "could not create the fixed ledger database"
            ) from error
        os.close(file_descriptor)
        _validate_database_file(db_path, validated_root)

        connection = _connect(db_path)
        ledger = cls(validated_root, db_path, validated_run_id, connection)
        try:
            ledger._initialize_schema()
            ledger.validate()
        except Exception:
            connection.close()
            ledger._closed = True
            raise
        return ledger

    @classmethod
    def reopen(cls, run_root: Path, run_id: RunId) -> Self:
        validated_root = _validated_run_root(run_root)
        validated_run_id = _RUN_ID_ADAPTER.validate_python(run_id)
        db_path = validated_root / _LEDGER_FILENAME
        _validate_database_file(db_path, validated_root)
        try:
            connection = _connect(db_path)
        except sqlite3.DatabaseError as error:
            raise LedgerIntegrityError("ledger database is not valid SQLite") from error
        ledger = cls(validated_root, db_path, validated_run_id, connection)
        try:
            ledger.validate()
        except Exception:
            connection.close()
            ledger._closed = True
            raise
        return ledger

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def run_id(self) -> RunId:
        return self._run_id

    def __enter__(self) -> Self:
        self._require_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def next_event_seq(self) -> int:
        self._require_open()
        return self._next_event_seq_unlocked()

    def append_event(self, event: LabEvent) -> LabEvent:
        self._require_open()
        validated = _validated_event(event)
        if validated.kind in _MANAGED_EVENT_KINDS:
            raise ManagedEventError(
                f"{validated.kind.value} must be appended by its ledger transaction"
            )
        with self._transaction():
            return self._insert_event(validated)

    def events(self) -> tuple[LabEvent, ...]:
        self._require_open()
        rows = self._connection.execute(
            f"SELECT {_EVENT_COLUMNS} FROM events ORDER BY seq"
        ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def event_digest(self) -> Digest:
        return canonical_digest(
            [event.model_dump(mode="json") for event in self.events()]
        )

    def register_operation(
        self,
        identity: OperationIdentity,
        *,
        tick: int,
    ) -> OperationSnapshot:
        self._require_open()
        _require_identity(identity)
        validated_tick = _strict_non_negative_int(tick, name="tick")
        with self._transaction():
            existing = self._connection.execute(
                "SELECT action_id FROM operations WHERE action_id = ? "
                "ORDER BY action_id",
                (identity.action_id,),
            ).fetchone()
            if existing is not None:
                raise DuplicateOperationError(
                    f"operation {identity.action_id} is already registered"
                )
            event_seq = self._next_event_seq_unlocked()
            self._insert_event(
                LabEvent(
                    seq=event_seq,
                    tick=validated_tick,
                    kind=EventKind.ACTION_PROPOSED,
                    action_id=identity.action_id,
                    operation_key=identity.operation_key,
                    intent_digest=identity.intent_digest,
                    authority_id=identity.authority_id,
                    evidence={},
                )
            )
            self._connection.execute(
                """
                INSERT INTO operations (
                    action_id, operation_key, intent_digest, authority_id,
                    state, created_event_seq, updated_event_seq
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity.action_id,
                    identity.operation_key,
                    identity.intent_digest,
                    identity.authority_id,
                    OperationState.PROPOSED.value,
                    event_seq,
                    event_seq,
                ),
            )
            return self._operation_unlocked(identity.action_id)

    def transition(
        self,
        action_id: ActionId,
        target: OperationState,
        *,
        evidence: TransitionEvidence,
        identity: OperationIdentity,
        tick: int,
    ) -> PersistedTransition:
        self._require_open()
        validated_action_id = _ACTION_ID_ADAPTER.validate_python(action_id)
        _require_state(target)
        _require_evidence(evidence)
        _require_identity(identity)
        validated_tick = _strict_non_negative_int(tick, name="tick")
        if target is OperationState.IN_FLIGHT:
            raise DispatchRequiredError(
                "IN_FLIGHT requires record_dispatch() and a durable permit"
            )

        caught_error: InvalidTransitionError | None = None
        persisted: PersistedTransition | None = None
        with self._transaction():
            machine, _ = self._load_machine_unlocked(validated_action_id)
            history_length = len(machine.history)
            try:
                record = machine.transition(
                    target,
                    evidence=evidence,
                    identity=identity,
                )
            except InvalidTransitionError as error:
                caught_error = error
                if len(machine.history) == history_length:
                    record = None
                else:
                    record = error.record
            if record is not None:
                persisted = self._persist_transition(
                    identity=machine.identity,
                    candidate_identity=identity,
                    record=record,
                    evidence=evidence,
                    tick=validated_tick,
                )

        if caught_error is not None:
            raise caught_error
        if persisted is None:
            raise LedgerIntegrityError("successful transition was not persisted")
        return persisted

    def record_dispatch(
        self,
        action_id: ActionId,
        *,
        attempt_id: AttemptId,
        evidence: TransitionEvidence,
        identity: OperationIdentity,
        tick: int,
    ) -> DispatchPermit:
        self._require_open()
        validated_action_id = _ACTION_ID_ADAPTER.validate_python(action_id)
        validated_attempt_id = _ATTEMPT_ID_ADAPTER.validate_python(attempt_id)
        _require_evidence(evidence)
        _require_identity(identity)
        validated_tick = _strict_non_negative_int(tick, name="tick")

        caught_error: InvalidTransitionError | None = None
        permit: DispatchPermit | None = None
        with self._transaction():
            machine, _ = self._load_machine_unlocked(validated_action_id)
            history_length = len(machine.history)
            try:
                record = machine.transition(
                    OperationState.IN_FLIGHT,
                    evidence=evidence,
                    identity=identity,
                    attempt_id=validated_attempt_id,
                )
            except InvalidTransitionError as error:
                caught_error = error
                if len(machine.history) == history_length:
                    record = None
                else:
                    record = error.record

            if record is not None and caught_error is not None:
                self._persist_transition(
                    identity=machine.identity,
                    candidate_identity=identity,
                    record=record,
                    evidence=evidence,
                    tick=validated_tick,
                )
            elif record is not None:
                dispatch_seq = self._next_event_seq_unlocked()
                self._insert_event(
                    LabEvent(
                        seq=dispatch_seq,
                        tick=validated_tick,
                        kind=EventKind.ATTEMPT_DISPATCHED,
                        action_id=machine.identity.action_id,
                        attempt_id=validated_attempt_id,
                        operation_key=machine.identity.operation_key,
                        intent_digest=machine.identity.intent_digest,
                        authority_id=machine.identity.authority_id,
                        evidence={},
                    )
                )
                persisted = self._persist_transition(
                    identity=machine.identity,
                    candidate_identity=identity,
                    record=record,
                    evidence=evidence,
                    tick=validated_tick,
                )
                attempt_ordinal = len(machine.attempt_ids)
                try:
                    self._connection.execute(
                        """
                        INSERT INTO attempts (
                            attempt_id, action_id, ordinal,
                            dispatch_event_seq, transition_event_seq
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            validated_attempt_id,
                            machine.identity.action_id,
                            attempt_ordinal,
                            dispatch_seq,
                            persisted.event_seq,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise LedgerIntegrityError(
                        f"attempt identifier collision: {validated_attempt_id}"
                    ) from error
                permit = DispatchPermit(
                    run_id=self._run_id,
                    action_id=machine.identity.action_id,
                    attempt_id=validated_attempt_id,
                    dispatch_event_seq=dispatch_seq,
                    transition_event_seq=persisted.event_seq,
                )

        if caught_error is not None:
            raise caught_error
        if permit is None:
            raise LedgerIntegrityError("successful dispatch was not persisted")
        return permit

    def operation(self, action_id: ActionId) -> OperationSnapshot:
        self._require_open()
        validated_action_id = _ACTION_ID_ADAPTER.validate_python(action_id)
        return self._operation_unlocked(validated_action_id)

    def operations(self) -> tuple[OperationSnapshot, ...]:
        self._require_open()
        rows = self._connection.execute(
            """
            SELECT action_id FROM operations
            ORDER BY created_event_seq, action_id
            """
        ).fetchall()
        return tuple(self._operation_unlocked(row["action_id"]) for row in rows)

    def validate(self) -> None:
        self._require_open()
        try:
            self._validate_contents()
        except (LedgerIntegrityError, LedgerPathError):
            raise
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
            sqlite3.DatabaseError,
        ) as error:
            raise LedgerIntegrityError(
                "ledger database contents are invalid"
            ) from error

    def _validate_contents(self) -> None:
        _validate_database_file(self._db_path, self._run_root)
        try:
            quick_check = self._connection.execute("PRAGMA quick_check").fetchall()
            if [row[0] for row in quick_check] != ["ok"]:
                raise LedgerIntegrityError("SQLite quick_check failed")
            foreign_key_errors = self._connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if foreign_key_errors:
                raise LedgerIntegrityError("SQLite foreign-key check failed")
            metadata = self._connection.execute(
                """
                SELECT ledger_schema_version, contract_schema_version, run_id
                FROM ledger_metadata
                ORDER BY singleton_id
                """
            ).fetchall()
        except sqlite3.DatabaseError as error:
            raise LedgerIntegrityError(
                "ledger database structure is invalid"
            ) from error
        if len(metadata) != 1:
            raise LedgerIntegrityError("ledger metadata row is missing or duplicated")
        row = metadata[0]
        if row["ledger_schema_version"] != _LEDGER_SCHEMA_VERSION:
            raise LedgerIntegrityError("unsupported internal ledger schema version")
        if row["contract_schema_version"] != CURRENT_SCHEMA_VERSION:
            raise LedgerIntegrityError("ledger contract schema version mismatch")
        if row["run_id"] != self._run_id:
            raise LedgerIntegrityError("ledger run_id does not match requested run")

        events = self.events()
        if [event.seq for event in events] != list(range(1, len(events) + 1)):
            raise LedgerIntegrityError("event sequences are not contiguous")
        ticks = [event.tick for event in events]
        if ticks != sorted(ticks):
            raise LedgerIntegrityError("event ticks are not nondecreasing")

        snapshots = self.operations()
        event_by_seq = {event.seq: event for event in events}
        expected_managed_sequences: set[int] = set()
        for snapshot in snapshots:
            proposed = event_by_seq.get(snapshot.created_event_seq)
            if (
                proposed is None
                or proposed.kind is not EventKind.ACTION_PROPOSED
                or not _event_matches_identity(proposed, snapshot.identity)
                or proposed.attempt_id is not None
                or proposed.evidence
            ):
                raise LedgerIntegrityError("operation lacks its proposal event")
            expected_managed_sequences.add(snapshot.created_event_seq)
            expected_updated_seq = (
                snapshot.history[-1].event_seq
                if snapshot.history
                else snapshot.created_event_seq
            )
            if snapshot.updated_event_seq != expected_updated_seq:
                raise LedgerIntegrityError("operation updated sequence is inconsistent")
            expected_managed_sequences.update(
                self._validate_attempt_rows(snapshot, event_by_seq)
            )
            expected_managed_sequences.update(
                self._validate_transition_events(snapshot, event_by_seq)
            )
        actual_managed_sequences = {
            event.seq for event in events if event.kind in _MANAGED_EVENT_KINDS
        }
        if actual_managed_sequences != expected_managed_sequences:
            raise LedgerIntegrityError("managed lifecycle event is orphaned or missing")

    def _initialize_schema(self) -> None:
        statements = (
            """
            CREATE TABLE ledger_metadata (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                ledger_schema_version INTEGER NOT NULL,
                contract_schema_version TEXT NOT NULL,
                run_id TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE events (
                seq INTEGER PRIMARY KEY CHECK (seq > 0),
                tick INTEGER NOT NULL CHECK (tick >= 0),
                kind TEXT NOT NULL,
                action_id TEXT,
                attempt_id TEXT,
                operation_key TEXT,
                effect_id TEXT,
                intent_digest TEXT,
                authority_id TEXT,
                workflow_id TEXT,
                fault_id TEXT,
                evidence_json BLOB NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE operations (
                action_id TEXT PRIMARY KEY,
                operation_key TEXT NOT NULL,
                intent_digest TEXT NOT NULL,
                authority_id TEXT NOT NULL,
                state TEXT NOT NULL,
                created_event_seq INTEGER NOT NULL REFERENCES events(seq),
                updated_event_seq INTEGER NOT NULL REFERENCES events(seq)
            ) STRICT
            """,
            """
            CREATE TABLE transitions (
                action_id TEXT NOT NULL REFERENCES operations(action_id),
                ordinal INTEGER NOT NULL CHECK (ordinal > 0),
                event_seq INTEGER NOT NULL UNIQUE REFERENCES events(seq),
                source_state TEXT NOT NULL,
                attempted_state TEXT NOT NULL,
                resulting_state TEXT NOT NULL,
                candidate_action_id TEXT NOT NULL,
                candidate_operation_key TEXT NOT NULL,
                candidate_intent_digest TEXT NOT NULL,
                candidate_authority_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                cause TEXT NOT NULL,
                fresh INTEGER NOT NULL CHECK (fresh IN (0, 1)),
                authoritative INTEGER NOT NULL CHECK (authoritative IN (0, 1)),
                exact_identity INTEGER NOT NULL CHECK (exact_identity IN (0, 1)),
                postcondition_verified INTEGER NOT NULL
                    CHECK (postcondition_verified IN (0, 1)),
                cardinality_valid INTEGER NOT NULL
                    CHECK (cardinality_valid IN (0, 1)),
                attempt_id TEXT,
                violation_reason TEXT,
                PRIMARY KEY (action_id, ordinal)
            ) STRICT
            """,
            """
            CREATE TABLE attempts (
                attempt_id TEXT PRIMARY KEY,
                action_id TEXT NOT NULL REFERENCES operations(action_id),
                ordinal INTEGER NOT NULL CHECK (ordinal > 0),
                dispatch_event_seq INTEGER NOT NULL UNIQUE REFERENCES events(seq),
                transition_event_seq INTEGER NOT NULL UNIQUE REFERENCES events(seq),
                UNIQUE (action_id, ordinal)
            ) STRICT
            """,
        )
        with self._transaction():
            for statement in statements:
                self._connection.execute(statement)
            self._connection.execute(
                """
                INSERT INTO ledger_metadata (
                    singleton_id, ledger_schema_version,
                    contract_schema_version, run_id
                ) VALUES (1, ?, ?, ?)
                """,
                (_LEDGER_SCHEMA_VERSION, CURRENT_SCHEMA_VERSION, self._run_id),
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._require_open()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _next_event_seq_unlocked(self) -> int:
        row = self._connection.execute(
            "SELECT seq FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return 1 if row is None else cast(int, row["seq"]) + 1

    def _insert_event(self, event: LabEvent) -> LabEvent:
        validated = _validated_event(event)
        expected_seq = self._next_event_seq_unlocked()
        if validated.seq != expected_seq:
            raise EventSequenceError(
                f"event seq must be contiguous: expected {expected_seq}, "
                f"received {validated.seq}"
            )
        latest = self._connection.execute(
            "SELECT tick FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if latest is not None and validated.tick < latest["tick"]:
            raise EventSequenceError(
                f"event tick cannot move backward from {latest['tick']} "
                f"to {validated.tick}"
            )
        values = validated.model_dump(mode="json")
        try:
            self._connection.execute(
                f"INSERT INTO events ({_EVENT_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    values["seq"],
                    values["tick"],
                    values["kind"],
                    values["action_id"],
                    values["attempt_id"],
                    values["operation_key"],
                    values["effect_id"],
                    values["intent_digest"],
                    values["authority_id"],
                    values["workflow_id"],
                    values["fault_id"],
                    canonical_json_bytes(values["evidence"]),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise EventSequenceError("event sequence could not be appended") from error
        return validated

    def _event_from_row(self, row: sqlite3.Row) -> LabEvent:
        try:
            raw_evidence = bytes(row["evidence_json"])
            evidence = loads(raw_evidence.decode("utf-8"))
            event = LabEvent(
                seq=row["seq"],
                tick=row["tick"],
                kind=EventKind(row["kind"]),
                action_id=row["action_id"],
                attempt_id=row["attempt_id"],
                operation_key=row["operation_key"],
                effect_id=row["effect_id"],
                intent_digest=row["intent_digest"],
                authority_id=row["authority_id"],
                workflow_id=row["workflow_id"],
                fault_id=row["fault_id"],
                evidence=evidence,
            )
            if raw_evidence != canonical_json_bytes(event.evidence):
                raise LedgerIntegrityError(
                    "persisted event evidence is not canonical JSON"
                )
            return event
        except (
            JSONDecodeError,
            TypeError,
            UnicodeDecodeError,
            ValidationError,
        ) as error:
            raise LedgerIntegrityError("persisted event is invalid") from error

    def _persist_transition(
        self,
        *,
        identity: OperationIdentity,
        candidate_identity: OperationIdentity,
        record: TransitionRecord,
        evidence: TransitionEvidence,
        tick: int,
    ) -> PersistedTransition:
        if (
            record.resulting_state is OperationState.PREPARED
            and record.violation_reason is None
        ):
            prepared_seq = self._next_event_seq_unlocked()
            self._insert_event(
                LabEvent(
                    seq=prepared_seq,
                    tick=tick,
                    kind=EventKind.OPERATION_PREPARED,
                    action_id=identity.action_id,
                    operation_key=identity.operation_key,
                    intent_digest=identity.intent_digest,
                    authority_id=identity.authority_id,
                    evidence={},
                )
            )

        transition_seq = self._next_event_seq_unlocked()
        transition_facts = _transition_event_evidence(record, evidence)
        self._insert_event(
            LabEvent(
                seq=transition_seq,
                tick=tick,
                kind=EventKind.STATE_TRANSITION,
                action_id=identity.action_id,
                attempt_id=record.attempt_id,
                operation_key=identity.operation_key,
                intent_digest=identity.intent_digest,
                authority_id=identity.authority_id,
                evidence=cast(Any, transition_facts),
            )
        )
        ordinal_row = self._connection.execute(
            """
            SELECT ordinal FROM transitions
            WHERE action_id = ?
            ORDER BY ordinal DESC, event_seq DESC
            LIMIT 1
            """,
            (identity.action_id,),
        ).fetchone()
        ordinal = 1 if ordinal_row is None else cast(int, ordinal_row["ordinal"]) + 1
        self._connection.execute(
            """
            INSERT INTO transitions (
                action_id, ordinal, event_seq, source_state, attempted_state,
                resulting_state, candidate_action_id, candidate_operation_key,
                candidate_intent_digest, candidate_authority_id, evidence_id,
                cause, fresh, authoritative, exact_identity,
                postcondition_verified, cardinality_valid, attempt_id,
                violation_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity.action_id,
                ordinal,
                transition_seq,
                record.source_state.value,
                record.attempted_state.value,
                record.resulting_state.value,
                candidate_identity.action_id,
                candidate_identity.operation_key,
                candidate_identity.intent_digest,
                candidate_identity.authority_id,
                record.evidence_id,
                record.cause.value,
                int(evidence.fresh),
                int(evidence.authoritative),
                int(evidence.exact_identity),
                int(evidence.postcondition_verified),
                int(evidence.cardinality_valid),
                record.attempt_id,
                record.violation_reason,
            ),
        )
        self._connection.execute(
            """
            UPDATE operations
            SET state = ?, updated_event_seq = ?
            WHERE action_id = ?
            """,
            (record.resulting_state.value, transition_seq, identity.action_id),
        )
        return PersistedTransition(record, evidence, transition_seq)

    def _operation_unlocked(self, action_id: ActionId) -> OperationSnapshot:
        machine, history = self._load_machine_unlocked(action_id)
        row = self._operation_row(action_id)
        return OperationSnapshot(
            identity=machine.identity,
            state=machine.state,
            created_event_seq=row["created_event_seq"],
            updated_event_seq=row["updated_event_seq"],
            attempt_ids=machine.attempt_ids,
            history=history,
        )

    def _operation_row(self, action_id: ActionId) -> sqlite3.Row:
        row = self._connection.execute(
            """
            SELECT action_id, operation_key, intent_digest, authority_id,
                   state, created_event_seq, updated_event_seq
            FROM operations
            WHERE action_id = ?
            ORDER BY action_id
            """,
            (action_id,),
        ).fetchone()
        if row is None:
            raise OperationNotFoundError(f"operation {action_id} is not registered")
        return cast(sqlite3.Row, row)

    def _load_machine_unlocked(
        self, action_id: ActionId
    ) -> tuple[OperationStateMachine, tuple[PersistedTransition, ...]]:
        row = self._operation_row(action_id)
        try:
            identity = OperationIdentity(
                action_id=row["action_id"],
                operation_key=row["operation_key"],
                intent_digest=row["intent_digest"],
                authority_id=row["authority_id"],
            )
            cached_state = OperationState(row["state"])
        except (TypeError, ValueError, ValidationError) as error:
            raise LedgerIntegrityError(
                "persisted operation identity/state is invalid"
            ) from error
        machine = OperationStateMachine(identity)
        transition_rows = self._connection.execute(
            """
            SELECT action_id, ordinal, event_seq, source_state, attempted_state,
                   resulting_state, candidate_action_id,
                   candidate_operation_key, candidate_intent_digest,
                   candidate_authority_id, evidence_id, cause, fresh,
                   authoritative, exact_identity, postcondition_verified,
                   cardinality_valid, attempt_id, violation_reason
            FROM transitions
            WHERE action_id = ?
            ORDER BY ordinal, event_seq
            """,
            (action_id,),
        ).fetchall()
        persisted: list[PersistedTransition] = []
        for expected_ordinal, transition_row in enumerate(transition_rows, start=1):
            if transition_row["ordinal"] != expected_ordinal:
                raise LedgerIntegrityError("transition ordinals are not contiguous")
            try:
                evidence = TransitionEvidence(
                    evidence_id=transition_row["evidence_id"],
                    cause=TransitionCause(transition_row["cause"]),
                    fresh=_strict_db_bool(transition_row["fresh"], name="fresh"),
                    authoritative=_strict_db_bool(
                        transition_row["authoritative"], name="authoritative"
                    ),
                    exact_identity=_strict_db_bool(
                        transition_row["exact_identity"], name="exact_identity"
                    ),
                    postcondition_verified=_strict_db_bool(
                        transition_row["postcondition_verified"],
                        name="postcondition_verified",
                    ),
                    cardinality_valid=_strict_db_bool(
                        transition_row["cardinality_valid"],
                        name="cardinality_valid",
                    ),
                )
                expected_record = TransitionRecord(
                    source_state=OperationState(transition_row["source_state"]),
                    attempted_state=OperationState(transition_row["attempted_state"]),
                    resulting_state=OperationState(transition_row["resulting_state"]),
                    evidence_id=transition_row["evidence_id"],
                    cause=TransitionCause(transition_row["cause"]),
                    attempt_id=transition_row["attempt_id"],
                    violation_reason=transition_row["violation_reason"],
                )
                candidate_identity = OperationIdentity(
                    action_id=transition_row["candidate_action_id"],
                    operation_key=transition_row["candidate_operation_key"],
                    intent_digest=transition_row["candidate_intent_digest"],
                    authority_id=transition_row["candidate_authority_id"],
                )
            except (TypeError, ValueError) as error:
                raise LedgerIntegrityError("persisted transition is invalid") from error

            actual_record: TransitionRecord
            history_length = len(machine.history)
            try:
                actual_record = machine.transition(
                    expected_record.attempted_state,
                    evidence=evidence,
                    identity=candidate_identity,
                    attempt_id=expected_record.attempt_id,
                )
            except InvalidTransitionError as error:
                actual_record = error.record
            if len(machine.history) != history_length + 1:
                raise LedgerIntegrityError(
                    "persisted transition did not append state-machine history"
                )
            if actual_record != expected_record:
                raise LedgerIntegrityError(
                    "persisted transition does not replay through the state machine"
                )
            persisted.append(
                PersistedTransition(
                    record=expected_record,
                    evidence=evidence,
                    event_seq=transition_row["event_seq"],
                )
            )

        if machine.state is not cached_state:
            raise LedgerIntegrityError("cached operation state disagrees with replay")
        attempt_rows = self._connection.execute(
            """
            SELECT attempt_id, ordinal FROM attempts
            WHERE action_id = ?
            ORDER BY ordinal, attempt_id
            """,
            (action_id,),
        ).fetchall()
        try:
            stored_attempts = tuple(
                _ATTEMPT_ID_ADAPTER.validate_python(attempt_row["attempt_id"])
                for attempt_row in attempt_rows
            )
        except ValidationError as error:
            raise LedgerIntegrityError(
                "persisted attempt identifier is invalid"
            ) from error
        if [attempt_row["ordinal"] for attempt_row in attempt_rows] != list(
            range(1, len(attempt_rows) + 1)
        ):
            raise LedgerIntegrityError("attempt ordinals are not contiguous")
        if stored_attempts != machine.attempt_ids:
            raise LedgerIntegrityError(
                "persisted attempts disagree with transition replay"
            )
        return machine, tuple(persisted)

    def _validate_attempt_rows(
        self,
        snapshot: OperationSnapshot,
        event_by_seq: dict[int, LabEvent],
    ) -> set[int]:
        rows = self._connection.execute(
            """
            SELECT attempt_id, action_id, ordinal,
                   dispatch_event_seq, transition_event_seq
            FROM attempts
            WHERE action_id = ?
            ORDER BY ordinal, attempt_id
            """,
            (snapshot.identity.action_id,),
        ).fetchall()
        referenced_sequences: set[int] = set()
        history_by_attempt = {
            persisted.record.attempt_id: persisted
            for persisted in snapshot.history
            if persisted.record.attempt_id is not None
            and persisted.record.resulting_state is OperationState.IN_FLIGHT
            and persisted.record.violation_reason is None
        }
        for expected_ordinal, row in enumerate(rows, start=1):
            if row["ordinal"] != expected_ordinal:
                raise LedgerIntegrityError("attempt ordinals are not contiguous")
            dispatch = event_by_seq.get(row["dispatch_event_seq"])
            transition = event_by_seq.get(row["transition_event_seq"])
            if (
                dispatch is None
                or dispatch.kind is not EventKind.ATTEMPT_DISPATCHED
                or not _event_matches_identity(dispatch, snapshot.identity)
                or dispatch.attempt_id != row["attempt_id"]
                or dispatch.evidence
            ):
                raise LedgerIntegrityError("attempt dispatch event is inconsistent")
            persisted = history_by_attempt.get(row["attempt_id"])
            if (
                transition is None
                or transition.kind is not EventKind.STATE_TRANSITION
                or not _event_matches_identity(transition, snapshot.identity)
                or transition.attempt_id != row["attempt_id"]
                or row["transition_event_seq"] != row["dispatch_event_seq"] + 1
                or transition.tick != dispatch.tick
                or persisted is None
                or persisted.event_seq != row["transition_event_seq"]
                or persisted.record.resulting_state is not OperationState.IN_FLIGHT
            ):
                raise LedgerIntegrityError("attempt transition event is inconsistent")
            referenced_sequences.update(
                {row["dispatch_event_seq"], row["transition_event_seq"]}
            )
        return referenced_sequences

    def _validate_transition_events(
        self,
        snapshot: OperationSnapshot,
        event_by_seq: dict[int, LabEvent],
    ) -> set[int]:
        referenced_sequences: set[int] = set()
        for persisted in snapshot.history:
            event = event_by_seq.get(persisted.event_seq)
            if (
                event is None
                or event.kind is not EventKind.STATE_TRANSITION
                or not _event_matches_identity(event, snapshot.identity)
                or event.attempt_id != persisted.record.attempt_id
                or event.evidence
                != _transition_event_evidence(persisted.record, persisted.evidence)
            ):
                raise LedgerIntegrityError("state-transition event is inconsistent")
            referenced_sequences.add(persisted.event_seq)
            if (
                persisted.record.resulting_state is OperationState.PREPARED
                and persisted.record.violation_reason is None
            ):
                prepared_seq = persisted.event_seq - 1
                prepared = event_by_seq.get(prepared_seq)
                if (
                    prepared is None
                    or prepared.kind is not EventKind.OPERATION_PREPARED
                    or not _event_matches_identity(prepared, snapshot.identity)
                    or prepared.attempt_id is not None
                    or prepared.evidence
                    or prepared.tick != event.tick
                ):
                    raise LedgerIntegrityError(
                        "operation-prepared event is inconsistent"
                    )
                referenced_sequences.add(prepared_seq)
        return referenced_sequences

    def _require_open(self) -> None:
        if self._closed:
            raise LedgerClosedError("ledger is closed")


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        db_path,
        isolation_level=None,
        timeout=0.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def _validated_run_root(run_root: Path) -> Path:
    if not isinstance(run_root, Path):
        raise TypeError("run_root must be a pathlib.Path")
    if not run_root.is_absolute():
        raise LedgerPathError("run_root must be absolute")
    try:
        path_stat = run_root.lstat()
        resolved = run_root.resolve(strict=True)
    except OSError as error:
        raise LedgerPathError("run_root must already exist") from error
    if stat.S_ISLNK(path_stat.st_mode):
        raise LedgerPathError("run_root must not be a symlink")
    if not stat.S_ISDIR(path_stat.st_mode):
        raise LedgerPathError("run_root must be a directory")
    if resolved != run_root:
        raise LedgerPathError("run_root must be provided in resolved form")
    if path_stat.st_uid != os.getuid():
        raise LedgerPathError("run_root must be owned by the current user")
    mode = stat.S_IMODE(path_stat.st_mode)
    if mode & 0o077 or mode & 0o700 != 0o700:
        raise LedgerPathError("run_root permissions must be owner-only rwx")
    return resolved


def _require_absent_database(db_path: Path) -> None:
    try:
        db_path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise LedgerPathError("could not inspect fixed database path") from error
    raise LedgerPathError("fixed ledger database path already exists")


def _validate_database_file(db_path: Path, run_root: Path) -> None:
    try:
        path_stat = db_path.lstat()
    except OSError as error:
        raise LedgerPathError("fixed ledger database does not exist") from error
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise LedgerPathError("fixed ledger database must be a regular file")
    if path_stat.st_nlink != 1:
        raise LedgerPathError("ledger database must not be hard-linked")
    if path_stat.st_uid != os.getuid():
        raise LedgerPathError("ledger database must be owned by the current user")
    if stat.S_IMODE(path_stat.st_mode) & 0o077:
        raise LedgerPathError("ledger database permissions must be owner-only")
    try:
        resolved = db_path.resolve(strict=True)
    except OSError as error:
        raise LedgerPathError("fixed ledger database cannot be resolved") from error
    if resolved.parent != run_root or resolved.name != _LEDGER_FILENAME:
        raise LedgerPathError("ledger database escaped the resolved run root")


def _validated_event(event: LabEvent) -> LabEvent:
    if not isinstance(event, LabEvent):
        raise TypeError("event must be a LabEvent")
    return LabEvent.model_validate(event.model_dump(mode="python"), strict=True)


def _require_identity(identity: OperationIdentity) -> None:
    if not isinstance(identity, OperationIdentity):
        raise TypeError("identity must be an OperationIdentity")


def _require_state(state: OperationState) -> None:
    if not isinstance(state, OperationState):
        raise TypeError("target must be an OperationState")


def _require_evidence(evidence: TransitionEvidence) -> None:
    if not isinstance(evidence, TransitionEvidence):
        raise TypeError("evidence must be TransitionEvidence")


def _strict_non_negative_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _strict_db_bool(value: object, *, name: str) -> bool:
    if value == 0:
        return False
    if value == 1:
        return True
    raise LedgerIntegrityError(f"persisted {name} flag is invalid")


def _event_matches_identity(
    event: LabEvent,
    identity: OperationIdentity,
) -> bool:
    return (
        event.action_id == identity.action_id
        and event.operation_key == identity.operation_key
        and event.intent_digest == identity.intent_digest
        and event.authority_id == identity.authority_id
    )


def _transition_event_evidence(
    record: TransitionRecord,
    evidence: TransitionEvidence,
) -> dict[str, object]:
    return {
        **record.canonical_value(),
        "fresh": evidence.fresh,
        "authoritative": evidence.authoritative,
        "exact_identity": evidence.exact_identity,
        "postcondition_verified": evidence.postcondition_verified,
        "cardinality_valid": evidence.cardinality_valid,
    }


__all__ = [
    "DispatchPermit",
    "DispatchRequiredError",
    "DuplicateOperationError",
    "EventSequenceError",
    "LedgerClosedError",
    "LedgerError",
    "LedgerIntegrityError",
    "LedgerPathError",
    "ManagedEventError",
    "OperationNotFoundError",
    "OperationSnapshot",
    "PersistedTransition",
    "SQLiteLedger",
]
