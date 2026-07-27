"""Tests for logical time, stable scheduling, and deterministic identifiers."""

import os
import time
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from side_effects_lab.canonical import canonical_digest
from side_effects_lab.clock import (
    DeterministicScheduler,
    LogicalClock,
    RunScopedIdAllocator,
    ScheduledItem,
    make_run_id,
)
from side_effects_lab.models import AttemptId, EffectId, RunId

_ATTEMPT_ID_ADAPTER: TypeAdapter[AttemptId] = TypeAdapter(AttemptId)
_EFFECT_ID_ADAPTER: TypeAdapter[EffectId] = TypeAdapter(EffectId)
_RUN_ID_ADAPTER: TypeAdapter[RunId] = TypeAdapter(RunId)


def test_logical_clock_starts_at_zero_and_advances_monotonically() -> None:
    clock = LogicalClock()

    assert clock.tick == 0
    assert clock.advance() == 1
    assert clock.advance(3) == 4
    assert clock.advance_to(4) == 4
    assert clock.advance_to(9) == 9


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_logical_clock_rejects_non_integer_inputs(value: object) -> None:
    clock = LogicalClock()

    with pytest.raises(TypeError, match="steps must be an integer"):
        clock.advance(cast(Any, value))
    with pytest.raises(TypeError, match="tick must be an integer"):
        clock.advance_to(cast(Any, value))


def test_logical_clock_rejects_non_positive_advance_and_backward_time() -> None:
    clock = LogicalClock()

    with pytest.raises(ValueError, match="steps must be positive"):
        clock.advance(0)
    with pytest.raises(ValueError, match="steps must be non-negative"):
        clock.advance(-1)
    with pytest.raises(ValueError, match="tick must be non-negative"):
        clock.advance_to(-1)

    clock.advance_to(3)
    with pytest.raises(ValueError, match="cannot move backward from 3 to 2"):
        clock.advance_to(2)


def test_scheduled_item_is_frozen_and_validates_ordering_fields() -> None:
    item = ScheduledItem(tick=2, ordinal=0, payload={"opaque": True})

    with pytest.raises(FrozenInstanceError):
        item.tick = 3  # type: ignore[misc]
    with pytest.raises(TypeError, match="tick must be an integer"):
        ScheduledItem(tick=cast(Any, True), ordinal=0, payload="bad")
    with pytest.raises(ValueError, match="ordinal must be non-negative"):
        ScheduledItem(tick=0, ordinal=-1, payload="bad")


@given(
    st.lists(
        st.tuples(st.integers(min_value=0, max_value=50), st.integers()),
        max_size=80,
    )
)
def test_scheduler_pops_by_tick_then_insertion_order(
    actions: list[tuple[int, int]],
) -> None:
    scheduler: DeterministicScheduler[int] = DeterministicScheduler()
    for tick, payload in actions:
        scheduler.schedule_at(tick, payload)

    actual: list[tuple[int, int, int]] = []
    while (item := scheduler.pop_next()) is not None:
        actual.append((item.tick, item.ordinal, item.payload))

    expected = sorted(
        (tick, ordinal, payload) for ordinal, (tick, payload) in enumerate(actions)
    )
    assert actual == expected
    assert len(scheduler) == 0
    assert scheduler.clock.tick == (max((tick for tick, _ in actions), default=0))


class _NeverComparable:
    def __lt__(self, other: object) -> bool:
        raise AssertionError("scheduler compared opaque payloads")


def test_same_tick_fifo_never_compares_payloads() -> None:
    scheduler: DeterministicScheduler[_NeverComparable] = DeterministicScheduler()
    payloads = [_NeverComparable(), _NeverComparable(), _NeverComparable()]

    scheduled = [scheduler.schedule_at(4, payload) for payload in payloads]
    popped = [scheduler.pop_next(), scheduler.pop_next(), scheduler.pop_next()]

    assert [item.ordinal for item in scheduled] == [0, 1, 2]
    assert [item.payload if item is not None else None for item in popped] == payloads
    assert scheduler.clock.tick == 4


def test_current_tick_scheduling_and_zero_delay_are_allowed() -> None:
    clock = LogicalClock()
    clock.advance_to(5)
    scheduler: DeterministicScheduler[str] = DeterministicScheduler(clock)

    first = scheduler.schedule_at(5, "at-current")
    second = scheduler.schedule_after(0, "zero-delay")

    assert first.tick == second.tick == 5
    assert scheduler.pop_next() == first
    assert scheduler.pop_next() == second
    assert scheduler.clock is clock
    assert clock.tick == 5


def test_scheduler_rejects_invalid_delay_and_past_ticks() -> None:
    scheduler: DeterministicScheduler[str] = DeterministicScheduler()

    with pytest.raises(TypeError, match="delay must be an integer"):
        scheduler.schedule_after(cast(Any, True), "bad")
    with pytest.raises(TypeError, match="delay must be an integer"):
        scheduler.schedule_after(cast(Any, 1.5), "bad")
    with pytest.raises(ValueError, match="delay must be non-negative"):
        scheduler.schedule_after(-1, "bad")
    with pytest.raises(TypeError, match="tick must be an integer"):
        scheduler.schedule_at(cast(Any, True), "bad")
    with pytest.raises(TypeError, match="tick must be an integer"):
        scheduler.schedule_at(cast(Any, 1.5), "bad")

    scheduler.schedule_at(2, "advance")
    assert scheduler.pop_next() is not None
    with pytest.raises(ValueError, match="cannot schedule in the past"):
        scheduler.schedule_at(1, "past")


def test_external_clock_advance_does_not_silently_drop_stale_queue_item() -> None:
    clock = LogicalClock()
    scheduler: DeterministicScheduler[str] = DeterministicScheduler(clock)
    scheduled = scheduler.schedule_at(2, "still-queued")
    clock.advance_to(3)

    with pytest.raises(RuntimeError, match="item before the current logical tick"):
        scheduler.pop_next()

    assert len(scheduler) == 1
    assert scheduled.payload == "still-queued"


def test_empty_scheduler_does_not_advance_time() -> None:
    clock = LogicalClock()
    clock.advance_to(7)
    scheduler: DeterministicScheduler[str] = DeterministicScheduler(clock)

    assert scheduler.pop_next() is None
    assert clock.tick == 7


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=30),
            st.text(alphabet="abc", max_size=12),
        ),
        max_size=60,
    )
)
def test_identical_schedules_have_identical_normalized_trace_digests(
    actions: list[tuple[int, str]],
) -> None:
    def run() -> tuple[list[dict[str, object]], str]:
        scheduler: DeterministicScheduler[str] = DeterministicScheduler()
        for tick, payload in actions:
            scheduler.schedule_at(tick, payload)
        trace: list[dict[str, object]] = []
        while (item := scheduler.pop_next()) is not None:
            trace.append(
                {
                    "ordinal": item.ordinal,
                    "payload": item.payload,
                    "tick": item.tick,
                }
            )
        return trace, canonical_digest(trace)

    assert run() == run()


def test_run_id_is_stable_and_each_declared_input_matters() -> None:
    baseline = make_run_id("SEL-001", 17, "reconcile-first")

    assert baseline == (
        "run-2af272f27137904fff4b56f6cbe9d8bcb3c8a9d954646452277cf3440d2cf1ff"
    )
    assert baseline == make_run_id("SEL-001", 17, "reconcile-first")
    assert baseline != make_run_id("SEL-002", 17, "reconcile-first")
    assert baseline != make_run_id("SEL-001", 18, "reconcile-first")
    assert baseline != make_run_id("SEL-001", 17, "retry-blindly")
    assert _RUN_ID_ADAPTER.validate_python(baseline) == baseline
    assert len(baseline) <= 128
    assert ":" not in baseline
    assert "_" not in baseline


def test_maximum_length_subject_still_produces_a_bounded_run_id() -> None:
    run_id = make_run_id("SEL-001", 17, "s" * 128)

    assert _RUN_ID_ADAPTER.validate_python(run_id) == run_id
    assert len(run_id) == 68


def test_run_id_rejects_invalid_contract_inputs() -> None:
    with pytest.raises(ValidationError):
        make_run_id(cast(Any, "sel-001"), 1, "reconcile-first")
    with pytest.raises(TypeError, match="seed must be an integer"):
        make_run_id("SEL-001", cast(Any, True), "reconcile-first")
    with pytest.raises(TypeError, match="seed must be an integer"):
        make_run_id("SEL-001", cast(Any, 1.5), "reconcile-first")
    with pytest.raises(ValueError, match="seed must be non-negative"):
        make_run_id("SEL-001", -1, "reconcile-first")
    with pytest.raises(ValidationError):
        make_run_id("SEL-001", 1, cast(Any, "subject:external"))


def test_run_scoped_attempt_ids_are_monotonic_and_reproducible() -> None:
    run_id = make_run_id("SEL-001", 17, "reconcile-first")
    first = RunScopedIdAllocator(run_id)
    second = RunScopedIdAllocator(run_id)

    first_ids = [first.next_attempt_id(), first.next_attempt_id()]
    second_ids = [second.next_attempt_id(), second.next_attempt_id()]

    assert first_ids == second_ids
    assert first_ids == ["attempt-1", "attempt-2"]
    assert first_ids[0] != first_ids[1]
    for attempt_id in first_ids:
        assert _ATTEMPT_ID_ADAPTER.validate_python(attempt_id) == attempt_id
        assert len(attempt_id) <= 128


def test_effect_counters_are_isolated_by_kind_and_from_attempts() -> None:
    run_id = make_run_id("SEL-001", 17, "reconcile-first")
    first = RunScopedIdAllocator(run_id)
    first_email_1 = first.next_effect_id("email")
    first.next_attempt_id()
    first_issue_1 = first.next_effect_id("issue")
    first_email_2 = first.next_effect_id("email")

    second = RunScopedIdAllocator(run_id)
    second_issue_1 = second.next_effect_id("issue")
    second_email_1 = second.next_effect_id("email")
    second_email_2 = second.next_effect_id("email")

    assert (first_email_1, first_email_2) == (second_email_1, second_email_2)
    assert first_issue_1 == second_issue_1
    assert (first_email_1, first_email_2, first_issue_1) == (
        "email-1",
        "email-2",
        "issue-1",
    )
    assert first_email_1 != first_email_2
    for effect_id in (first_email_1, first_email_2, first_issue_1):
        assert _EFFECT_ID_ADAPTER.validate_python(effect_id) == effect_id
        assert len(effect_id) <= 128


def test_maximum_length_effect_kind_still_produces_a_valid_effect_id() -> None:
    allocator = RunScopedIdAllocator(make_run_id("SEL-001", 0, "subject"))

    effect_id = allocator.next_effect_id("a" * 64)

    assert _EFFECT_ID_ADAPTER.validate_python(effect_id) == effect_id
    assert len(effect_id) <= 128


@pytest.mark.parametrize(
    "effect_kind",
    ["dummy_email", "1issue", "Issue", "", "a" * 65, True, 1],
)
def test_invalid_effect_kind_does_not_consume_a_counter(
    effect_kind: object,
) -> None:
    run_id = make_run_id("SEL-001", 0, "subject")
    allocator = RunScopedIdAllocator(run_id)

    with pytest.raises((TypeError, ValueError)):
        allocator.next_effect_id(cast(Any, effect_kind))

    assert allocator.next_effect_id("email") == RunScopedIdAllocator(
        run_id
    ).next_effect_id("email")


def test_ids_and_normalized_digests_ignore_root_pid_and_wall_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    def snapshot(root: Path, *, pid: int, wall: float, monotonic: float) -> str:
        monkeypatch.chdir(root)
        monkeypatch.setattr(os, "getpid", lambda: pid)
        monkeypatch.setattr(time, "time", lambda: wall)
        monkeypatch.setattr(time, "monotonic", lambda: monotonic)

        run_id = make_run_id("SEL-001", 17, "reconcile-first")
        allocator = RunScopedIdAllocator(run_id)
        scheduler: DeterministicScheduler[str] = DeterministicScheduler()
        scheduler.schedule_at(3, "visible")
        scheduled = scheduler.pop_next()
        assert scheduled is not None
        return canonical_digest(
            {
                "attempt_id": allocator.next_attempt_id(),
                "effect_id": allocator.next_effect_id("issue"),
                "run_id": run_id,
                "scheduled": {
                    "ordinal": scheduled.ordinal,
                    "payload": scheduled.payload,
                    "tick": scheduled.tick,
                },
            }
        )

    first = snapshot(first_root, pid=101, wall=1.25, monotonic=9.5)
    second = snapshot(second_root, pid=999_999, wall=8_765.0, monotonic=0.125)

    assert first == second
