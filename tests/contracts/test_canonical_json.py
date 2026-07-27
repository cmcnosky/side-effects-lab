"""Canonical JSON: integer-only, order-independent, float/NaN/infinity-free.

Traceability: Architecture determinism rules (UTF-8, sorted keys, compact
separators, no floats) and the T002B matrix "Finite floats" / "NaN/infinity"
rows. Both the encoder and the models must refuse non-integer numerics.
"""

from collections.abc import Callable
from math import inf, nan
from typing import cast

import pytest
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from side_effects_lab.canonical import (
    CanonicalJsonError,
    canonical_digest,
    canonical_json_bytes,
)
from side_effects_lab.models import CanonicalValue, SemanticIntent


def test_canonical_json_is_compact_sorted_and_utf8() -> None:
    payload = {"z": [2, {"ok": True}], "a": "é", "m": None}
    encoded = canonical_json_bytes(payload)
    assert encoded == b'{"a":"\xc3\xa9","m":null,"z":[2,{"ok":true}]}'
    text = encoded.decode("utf-8")
    assert ", " not in text and ": " not in text  # compact separators
    assert text.index('"a"') < text.index('"m"') < text.index('"z"')  # sorted keys


def test_insertion_order_does_not_change_bytes_or_digest() -> None:
    forward = {"a": 1, "b": {"c": 2, "d": [3, 4]}}
    backward = {"b": {"d": [3, 4], "c": 2}, "a": 1}
    assert canonical_json_bytes(forward) == canonical_json_bytes(backward)
    assert canonical_digest(forward) == canonical_digest(backward)


@pytest.mark.parametrize("value", [1.5, 0.0, -2.5, 1e10])
def test_encoder_rejects_finite_floats(value: float) -> None:
    with pytest.raises(CanonicalJsonError, match="floating-point value is forbidden"):
        canonical_json_bytes({"nested": [value]})


@pytest.mark.parametrize("value", [nan, inf, -inf, float("nan"), float("inf")])
def test_encoder_rejects_nan_and_infinity(value: float) -> None:
    with pytest.raises(CanonicalJsonError, match="floating-point value is forbidden"):
        canonical_json_bytes({"nested": value})


def test_encoder_reports_the_offending_path() -> None:
    with pytest.raises(CanonicalJsonError, match=r"\$\.outer\[1\].inner"):
        canonical_json_bytes({"outer": [1, {"inner": 2.5}]})


def test_encoder_rejects_non_string_object_keys() -> None:
    with pytest.raises(CanonicalJsonError, match="non-string object key"):
        canonical_json_bytes({1: "a"})


def test_encoder_rejects_unsupported_types() -> None:
    with pytest.raises(CanonicalJsonError, match="unsupported canonical JSON type"):
        canonical_json_bytes({"blob": b"bytes"})


def test_model_rejects_float_parameter(
    fixture_text: Callable[[str], str], assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        SemanticIntent.model_validate_json(fixture_text("finite_float.json"))
    # The rejected float never matches any canonical union member.
    assert_error(exc_info, ("parameters", "weight"))


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_model_rejects_programmatic_nan_and_infinity(value: float) -> None:
    # A float is intentionally invalid input; cast past the CanonicalValue type.
    bad = cast("dict[str, CanonicalValue]", {"x": value})
    with pytest.raises(ValidationError) as exc_info:
        SemanticIntent(service="s", operation="op", parameters=bad)
    assert exc_info.value.errors()[0]["loc"][:2] == ("parameters", "x")


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_model_json_rejects_non_standard_numeric_tokens(token: str) -> None:
    raw = '{"service":"s","operation":"op","parameters":{"x":' + token + "}}"
    with pytest.raises(ValidationError):
        SemanticIntent.model_validate_json(raw)


def test_integer_data_survives_round_trip() -> None:
    intent = SemanticIntent(
        service="s", operation="op", parameters={"count": 3, "flag": True, "none": None}
    )
    assert (
        canonical_json_bytes(intent.parameters)
        == b'{"count":3,"flag":true,"none":null}'
    )


def test_booleans_are_not_treated_as_integers() -> None:
    # bool is a subclass of int; canonical output must keep JSON true/false.
    assert canonical_json_bytes({"a": True, "b": 1}) == b'{"a":true,"b":1}'
