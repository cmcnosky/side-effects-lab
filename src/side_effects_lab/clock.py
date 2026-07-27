"""Logical time, deterministic scheduling, and run-scoped identifiers."""

from dataclasses import dataclass
from heapq import heappop, heappush
from re import compile as compile_pattern

from pydantic import TypeAdapter

from side_effects_lab.canonical import canonical_digest
from side_effects_lab.models import (
    AttemptId,
    EffectId,
    RunId,
    ScenarioId,
    SubjectId,
)

_ATTEMPT_ID_ADAPTER: TypeAdapter[AttemptId] = TypeAdapter(AttemptId)
_EFFECT_ID_ADAPTER: TypeAdapter[EffectId] = TypeAdapter(EffectId)
_RUN_ID_ADAPTER: TypeAdapter[RunId] = TypeAdapter(RunId)
_SCENARIO_ID_ADAPTER: TypeAdapter[ScenarioId] = TypeAdapter(ScenarioId)
_SUBJECT_ID_ADAPTER: TypeAdapter[SubjectId] = TypeAdapter(SubjectId)

_MAX_COUNTER = (1 << 64) - 1
_EFFECT_KIND_PATTERN = compile_pattern(r"^[a-z][a-z0-9-]{0,63}$")


def _strict_non_negative_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer, not {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _strict_positive_int(value: object, *, name: str) -> int:
    result = _strict_non_negative_int(value, name=name)
    if result == 0:
        raise ValueError(f"{name} must be positive")
    return result


class LogicalClock:
    """A monotonic integer clock with no wall-clock dependency."""

    __slots__ = ("_tick",)

    def __init__(self) -> None:
        self._tick = 0

    @property
    def tick(self) -> int:
        return self._tick

    def advance(self, steps: int = 1) -> int:
        increment = _strict_positive_int(steps, name="steps")
        self._tick += increment
        return self._tick

    def advance_to(self, tick: int) -> int:
        target = _strict_non_negative_int(tick, name="tick")
        if target < self._tick:
            raise ValueError(
                f"logical clock cannot move backward from {self._tick} to {target}"
            )
        self._tick = target
        return self._tick


@dataclass(frozen=True, slots=True)
class ScheduledItem[T]:
    """One scheduled payload ordered externally by tick and insertion ordinal."""

    tick: int
    ordinal: int
    payload: T

    def __post_init__(self) -> None:
        _strict_non_negative_int(self.tick, name="tick")
        _strict_non_negative_int(self.ordinal, name="ordinal")


class DeterministicScheduler[T]:
    """A stable logical-time priority queue whose payloads are never compared."""

    __slots__ = ("_clock", "_next_ordinal", "_queue")

    def __init__(self, clock: LogicalClock | None = None) -> None:
        self._clock = clock if clock is not None else LogicalClock()
        self._next_ordinal = 0
        self._queue: list[tuple[int, int, ScheduledItem[T]]] = []

    @property
    def clock(self) -> LogicalClock:
        return self._clock

    def __len__(self) -> int:
        return len(self._queue)

    def schedule_at(self, tick: int, payload: T) -> ScheduledItem[T]:
        scheduled_tick = _strict_non_negative_int(tick, name="tick")
        if scheduled_tick < self._clock.tick:
            raise ValueError(
                "cannot schedule in the past: "
                f"clock is {self._clock.tick}, requested {scheduled_tick}"
            )
        item = ScheduledItem(
            tick=scheduled_tick,
            ordinal=self._next_ordinal,
            payload=payload,
        )
        self._next_ordinal += 1
        heappush(self._queue, (item.tick, item.ordinal, item))
        return item

    def schedule_after(self, delay: int, payload: T) -> ScheduledItem[T]:
        offset = _strict_non_negative_int(delay, name="delay")
        return self.schedule_at(self._clock.tick + offset, payload)

    def pop_next(self) -> ScheduledItem[T] | None:
        if not self._queue:
            return None
        next_tick = self._queue[0][0]
        if next_tick < self._clock.tick:
            raise RuntimeError(
                "scheduler contains an item before the current logical tick: "
                f"clock is {self._clock.tick}, item is {next_tick}"
            )
        _, _, item = heappop(self._queue)
        self._clock.advance_to(item.tick)
        return item


def make_run_id(
    scenario_id: ScenarioId,
    seed: int,
    subject_id: SubjectId,
) -> RunId:
    """Derive a stable run ID solely from scenario, seed, and subject identity."""
    validated_scenario_id = _SCENARIO_ID_ADAPTER.validate_python(scenario_id)
    validated_seed = _strict_non_negative_int(seed, name="seed")
    validated_subject_id = _SUBJECT_ID_ADAPTER.validate_python(subject_id)
    digest = canonical_digest(
        {
            "scenario_id": validated_scenario_id,
            "seed": validated_seed,
            "subject_id": validated_subject_id,
        }
    )
    return _RUN_ID_ADAPTER.validate_python(f"run-{digest.removeprefix('sha256:')}")


class RunScopedIdAllocator:
    """Allocate deterministic attempt and per-kind effect IDs within one run."""

    __slots__ = ("_attempt_counter", "_effect_counters", "_run_id")

    def __init__(self, run_id: RunId) -> None:
        self._run_id = _RUN_ID_ADAPTER.validate_python(run_id)
        self._attempt_counter = 0
        self._effect_counters: dict[str, int] = {}

    @property
    def run_id(self) -> RunId:
        return self._run_id

    def next_attempt_id(self) -> AttemptId:
        self._attempt_counter = self._next_counter(
            self._attempt_counter, domain="attempt"
        )
        return _ATTEMPT_ID_ADAPTER.validate_python(f"attempt-{self._attempt_counter}")

    def next_effect_id(self, effect_kind: str) -> EffectId:
        validated_kind = self._validate_effect_kind(effect_kind)
        counter = self._next_counter(
            self._effect_counters.get(validated_kind, 0),
            domain=f"effect:{validated_kind}",
        )
        self._effect_counters[validated_kind] = counter
        return _EFFECT_ID_ADAPTER.validate_python(f"{validated_kind}-{counter}")

    @staticmethod
    def _validate_effect_kind(value: object) -> str:
        if type(value) is not str:
            raise TypeError(f"effect_kind must be a string, not {type(value).__name__}")
        if not _EFFECT_KIND_PATTERN.fullmatch(value):
            raise ValueError(
                "effect_kind must start with a lowercase letter and contain "
                "1-64 lowercase letters, digits, or hyphens"
            )
        return value

    @staticmethod
    def _next_counter(current: int, *, domain: str) -> int:
        if current >= _MAX_COUNTER:
            raise OverflowError(f"{domain} identifier counter exhausted")
        return current + 1


__all__ = [
    "DeterministicScheduler",
    "LogicalClock",
    "RunScopedIdAllocator",
    "ScheduledItem",
    "make_run_id",
]
