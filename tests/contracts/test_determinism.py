"""Cross-process determinism of canonical bytes, digests, and schema output.

Traceability: Architecture determinism rules and the T002B matrix "Determinism
checks". Canonical bytes/digests and generated schema bytes must be identical
across insertion order and across ``PYTHONHASHSEED=0`` and ``1``. Hash-seed
independence can only be proven from a fresh interpreter, so each seed runs in a
local, network-free subprocess whose environment is a minimal explicit allowlist
(only ``PYTHONHASHSEED``) rather than an inherited copy of the parent's. No test
overwrites the checked-in schemas.
"""

import os
import subprocess
import sys
from pathlib import Path

from side_effects_lab.schema_generation import (
    SCHEMA_DIGEST_MANIFEST,
    SCHEMA_MODELS,
    SCHEMA_ROOT,
    expected_schema_digest_manifest,
    expected_schemas,
    schema_drift,
    write_schemas,
)

# A sentinel the parent process can set to prove it never reaches the child: the
# subprocess environment is an explicit allowlist, not a copy of ``os.environ``.
_SENTINEL_NAME = "SIDE_EFFECTS_LAB_PARENT_SENTINEL"
_SENTINEL_VALUE = "leak-canary-6f3d9c2a"

_PROBE = """
import hashlib
import os
from side_effects_lab.canonical import canonical_json_bytes, canonical_digest
from side_effects_lab.models import SemanticIntent
from side_effects_lab.schema_generation import (
    expected_schema_digest_manifest,
    expected_schemas,
)

keys = [f"k{i}" for i in range(12)]
forward = {k: {"i": idx, "s": k, "b": True, "n": None} for idx, k in enumerate(keys)}
backward = {k: forward[k] for k in reversed(keys)}
intent_a = SemanticIntent(
    service="dummy_github",
    operation="create_issue",
    parameters={"z": 1, "a": [1, {"m": 2, "b": 3}]},
)
intent_b = SemanticIntent(
    service="dummy_github",
    operation="create_issue",
    parameters={"a": [1, {"b": 3, "m": 2}], "z": 1},
)
present = "SIDE_EFFECTS_LAB_PARENT_SENTINEL" in os.environ
print("sentinel", "present" if present else "absent")
print("fwd", canonical_digest(forward))
print("bwd", canonical_digest(backward))
print("canon", canonical_json_bytes(forward).hex())
print("intent_a", canonical_digest(intent_a))
print("intent_b", canonical_digest(intent_b))
schemas = expected_schemas()
blob = b"".join(schemas[name] for name in sorted(schemas))
print("schema_all", hashlib.sha256(blob).hexdigest())
for name in sorted(schemas):
    print("schema:" + name, hashlib.sha256(schemas[name]).hexdigest())
print("schema_manifest", hashlib.sha256(expected_schema_digest_manifest()).hexdigest())
"""


def _run_under_seed(seed: str) -> dict[str, str]:
    # Minimal explicit allowlist: the child inherits nothing from the parent
    # except the hash seed under test.
    env = {"PYTHONHASHSEED": seed}
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    result: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        key, value = line.split(" ", 1)
        result[key] = value
    return result


def test_canonical_and_schema_output_is_hash_seed_independent() -> None:
    seed0 = _run_under_seed("0")
    seed1 = _run_under_seed("1")
    assert seed0, "probe produced no output"
    assert seed0 == seed1


def test_parent_environment_does_not_leak_into_probe() -> None:
    # Set a unique sentinel in this process, then prove the child never sees it:
    # the subprocess environment is the explicit allowlist, not a copy of ours.
    os.environ[_SENTINEL_NAME] = _SENTINEL_VALUE
    try:
        assert os.environ[_SENTINEL_NAME] == _SENTINEL_VALUE
        result = _run_under_seed("0")
    finally:
        os.environ.pop(_SENTINEL_NAME, None)
    assert result["sentinel"] == "absent"


def test_insertion_order_is_irrelevant_in_a_fresh_interpreter() -> None:
    for seed in ("0", "1"):
        result = _run_under_seed(seed)
        assert result["fwd"] == result["bwd"]
        assert result["intent_a"] == result["intent_b"]


def test_schema_bytes_are_identical_across_seeds_and_repeat_generation() -> None:
    seed0 = _run_under_seed("0")
    seed1 = _run_under_seed("1")
    for name in SCHEMA_MODELS:
        assert seed0["schema:" + name] == seed1["schema:" + name]
    # Re-generating in-process twice yields byte-identical output.
    first = expected_schemas()
    second = expected_schemas()
    assert first == second


def test_write_schemas_is_deterministic_without_touching_checked_in(
    tmp_path: Path,
) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    write_schemas(first)
    write_schemas(second)
    expected = expected_schemas()
    for name, content in expected.items():
        assert (first / name).read_bytes() == content
        assert (second / name).read_bytes() == content
        # Checked-in bytes match but are only read, never rewritten, here.
        assert (SCHEMA_ROOT / name).read_bytes() == content
    expected_manifest = expected_schema_digest_manifest()
    assert (first / SCHEMA_DIGEST_MANIFEST).read_bytes() == expected_manifest
    assert (second / SCHEMA_DIGEST_MANIFEST).read_bytes() == expected_manifest
    assert (SCHEMA_ROOT / SCHEMA_DIGEST_MANIFEST).read_bytes() == expected_manifest
    assert first.resolve() != SCHEMA_ROOT.resolve()


def test_checked_in_schemas_have_no_drift() -> None:
    assert schema_drift() == []
