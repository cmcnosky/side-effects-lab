"""Focused tests for canonical JSON and typed digests."""

import pytest

from side_effects_lab.canonical import (
    CanonicalJsonError,
    canonical_digest,
    canonical_json_bytes,
)


def test_canonical_json_is_compact_utf8_and_order_independent() -> None:
    left = {"z": [2, {"ok": True}], "a": "é"}
    right = {"a": "é", "z": [2, {"ok": True}]}

    expected = b'{"a":"\xc3\xa9","z":[2,{"ok":true}]}'
    assert canonical_json_bytes(left) == expected
    assert canonical_json_bytes(right) == expected
    assert canonical_digest(left) == canonical_digest(right)


@pytest.mark.parametrize("value", [1.5, float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_every_float(value: float) -> None:
    with pytest.raises(CanonicalJsonError, match="floating-point value is forbidden"):
        canonical_json_bytes({"nested": [value]})


def test_digest_has_canonical_sha256_shape() -> None:
    assert canonical_digest({"a": 1}) == (
        "sha256:015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"
    )
