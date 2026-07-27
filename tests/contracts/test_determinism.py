"""Cross-process determinism of canonical bytes, digests, and schema output.

Traceability: Architecture determinism rules and the T002B matrix "Determinism
checks". Canonical bytes/digests and generated schema bytes must be identical
across insertion order and across ``PYTHONHASHSEED=0`` and ``1``. Hash-seed
independence can only be proven from a fresh interpreter, so each seed runs in a
local, network-free subprocess. No test overwrites the checked-in schemas.
"""

import os
import subprocess
import sys
from pathlib import Path

from side_effects_lab.schema_generation import (
    SCHEMA_MODELS,
    SCHEMA_ROOT,
    expected_schemas,
    schema_drift,
    write_schemas,
)

_PROBE = """
import hashlib
from side_effects_lab.canonical import canonical_json_bytes, canonical_digest
from side_effects_lab.models import SemanticIntent
from side_effects_lab.schema_generation import expected_schemas

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
"""


def _run_under_seed(seed: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
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
    assert first.resolve() != SCHEMA_ROOT.resolve()


def test_checked_in_schemas_have_no_drift() -> None:
    assert schema_drift() == []
