"""Shared fixtures and error-location helpers for the T002B contract suite.

This suite is an independent adversarial re-derivation of the frozen T002A
contract behavior. Every negative assertion pins the intended error class and
field location rather than accepting any exception, per the T002B matrix.
"""

from collections.abc import Callable
from json import loads
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_core import ErrorDetails

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text() -> Callable[[str], str]:
    """Return a loader for the raw UTF-8 text of a checked-in fixture."""

    def _read(name: str) -> str:
        return (FIXTURE_DIR / name).read_text(encoding="utf-8")

    return _read


@pytest.fixture
def fixture_json() -> Callable[[str], object]:
    """Return a loader that parses a checked-in fixture into Python data."""

    def _load(name: str) -> object:
        return loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def assert_error() -> Callable[..., ErrorDetails]:
    """Return a helper asserting one error at a location with an intended type.

    ``loc`` is matched as a prefix so union-tagged locations (for example the
    ``("parameters", key, "bool")`` tag pydantic emits for a rejected float) can
    be pinned by their meaningful head without hard-coding the union member.
    """

    def _check(
        exc_info: pytest.ExceptionInfo[ValidationError],
        loc: tuple[object, ...],
        type_: str | None = None,
    ) -> ErrorDetails:
        errors = exc_info.value.errors()
        matches = [error for error in errors if error["loc"][: len(loc)] == loc]
        assert matches, (
            f"no error at loc prefix {loc!r}; got {[e['loc'] for e in errors]}"
        )
        if type_ is not None:
            typed = [error for error in matches if error["type"] == type_]
            assert typed, (
                f"no {type_!r} error at {loc!r}; "
                f"got {[(e['type'], e['loc']) for e in matches]}"
            )
            return typed[0]
        return matches[0]

    return _check
