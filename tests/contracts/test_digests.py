"""Digest grammar: prefix, length, case, and hex-alphabet boundaries.

Traceability: Architecture "Frozen base-contract conventions" (SHA-256 digests
are ``sha256:`` plus exactly 64 lowercase hex characters) and the T002B matrix
"Digests" row.
"""

import pytest
from pydantic import TypeAdapter, ValidationError

from side_effects_lab.canonical import canonical_digest
from side_effects_lab.models import Digest

_DIGEST: TypeAdapter[str] = TypeAdapter(Digest)
_VALID = "sha256:" + "0123456789abcdef" * 4


def test_valid_digest_round_trips() -> None:
    assert _DIGEST.validate_python(_VALID) == _VALID


def test_canonical_digest_has_prefixed_64_hex_shape() -> None:
    digest = canonical_digest({"a": 1})
    assert digest.startswith("sha256:")
    body = digest.removeprefix("sha256:")
    assert len(body) == 64
    assert body == body.lower()
    assert all(character in "0123456789abcdef" for character in body)
    assert len(digest) == 71


@pytest.mark.parametrize(
    "value",
    [
        "sha1:" + "a" * 64,
        "sha512:" + "a" * 64,
        "md5:" + "a" * 64,
        "SHA256:" + "a" * 64,
        "sha256=" + "a" * 64,
        "a" * 64,
        "sha256:",
    ],
)
def test_digest_rejects_wrong_prefix(value: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _DIGEST.validate_python(value)
    assert exc_info.value.errors()[0]["type"] == "string_pattern_mismatch"


@pytest.mark.parametrize("length", [0, 1, 63, 65, 128])
def test_digest_rejects_wrong_length(length: int) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _DIGEST.validate_python("sha256:" + "a" * length)
    assert exc_info.value.errors()[0]["type"] == "string_pattern_mismatch"


def test_digest_rejects_uppercase_hex() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _DIGEST.validate_python("sha256:" + "A" * 64)
    assert exc_info.value.errors()[0]["type"] == "string_pattern_mismatch"


@pytest.mark.parametrize("bad_char", ["g", "z", "-", " ", "x", "/"])
def test_digest_rejects_non_hex_characters(bad_char: str) -> None:
    body = bad_char + "a" * 63
    with pytest.raises(ValidationError) as exc_info:
        _DIGEST.validate_python("sha256:" + body)
    assert exc_info.value.errors()[0]["type"] == "string_pattern_mismatch"


def test_digest_rejects_leading_or_trailing_whitespace() -> None:
    for value in (" " + _VALID, _VALID + "\n", "\t" + _VALID):
        with pytest.raises(ValidationError) as exc_info:
            _DIGEST.validate_python(value)
        assert exc_info.value.errors()[0]["type"] == "string_pattern_mismatch"


@pytest.mark.parametrize("value", [123, None, b"sha256:" + b"a" * 64, True])
def test_digest_rejects_non_string(value: object) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _DIGEST.validate_python(value)
    assert exc_info.value.errors()[0]["type"] == "string_type"
