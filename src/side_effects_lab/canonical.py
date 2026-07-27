"""Canonical JSON and SHA-256 helpers for deterministic contracts."""

from collections.abc import Mapping
from enum import Enum
from hashlib import sha256
from json import dumps
from typing import cast

from pydantic import BaseModel, TypeAdapter

from side_effects_lab.models import CanonicalValue, Digest

_DIGEST_ADAPTER: TypeAdapter[Digest] = TypeAdapter(Digest)


class CanonicalJsonError(ValueError):
    """Raised when a value cannot appear in normalized JSON."""


def _normalize(value: object, path: str = "$") -> CanonicalValue:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="json"), path)
    if isinstance(value, Enum):
        return _normalize(value.value, path)
    if value is None or type(value) in {bool, int, str}:
        return cast(CanonicalValue, value)
    if type(value) is float:
        raise CanonicalJsonError(f"floating-point value is forbidden at {path}")
    if isinstance(value, list):
        return [
            _normalize(item, f"{path}[{index}]") for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        normalized: dict[str, CanonicalValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJsonError(
                    f"non-string object key is forbidden at {path}"
                )
            normalized[key] = _normalize(item, f"{path}.{key}")
        return normalized
    raise CanonicalJsonError(
        f"unsupported canonical JSON type {type(value).__name__} at {path}"
    )


def canonical_json_bytes(value: object) -> bytes:
    """Return compact UTF-8 JSON with code-point-sorted object keys."""
    normalized = _normalize(value)
    text = dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise CanonicalJsonError(
            "canonical JSON contains an invalid Unicode scalar"
        ) from error


def canonical_digest(value: object) -> Digest:
    """Return a typed SHA-256 digest of canonical JSON bytes."""
    digest = f"sha256:{sha256(canonical_json_bytes(value)).hexdigest()}"
    return _DIGEST_ADAPTER.validate_python(digest)


__all__ = ["CanonicalJsonError", "canonical_digest", "canonical_json_bytes"]
