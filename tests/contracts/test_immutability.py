"""Deep immutability of validated recursive contract values.

Traceability: Architecture "Frozen base-contract conventions" (recursive
parameter/evidence containers are defensively copied into read-only mappings and
tuples; copy updates must create and validate a new contract) and the T002B
matrix "Semantic intent" immutability guarantees. Every mutation vector is
exercised: caller aliasing, ordinary mutation, unbound ``dict``/``list``
descriptors, and ``model_copy(update=...)``.
"""

from copy import copy, deepcopy
from typing import cast

import pytest
from pydantic import ValidationError

from side_effects_lab.canonical import canonical_digest
from side_effects_lab.models import CanonicalValue, FrozenMap, SemanticIntent


def _intent() -> SemanticIntent:
    return SemanticIntent(
        service="dummy_github",
        operation="create_issue",
        parameters={"items": [{"name": "docs"}], "count": 1},
    )


def test_validated_containers_are_frozen_types() -> None:
    intent = _intent()
    assert isinstance(intent.parameters, FrozenMap)
    items = intent.parameters["items"]
    assert isinstance(items, tuple)
    assert isinstance(items[0], FrozenMap)


def test_caller_aliasing_cannot_mutate_after_validation() -> None:
    original: dict[str, CanonicalValue] = {"items": [{"name": "docs"}]}
    intent = SemanticIntent(
        service="dummy_github", operation="create_issue", parameters=original
    )
    digest = canonical_digest(intent)

    # Mutating the caller's original structures must not reach the model.
    cast(list[CanonicalValue], original["items"]).append("outside")
    assert canonical_digest(intent) == digest
    assert len(cast(tuple[object, ...], intent.parameters["items"])) == 1


def test_ordinary_item_assignment_is_blocked() -> None:
    intent = _intent()
    with pytest.raises(TypeError):
        intent.parameters["count"] = 2  # type: ignore[index]
    inner = cast(tuple[object, ...], intent.parameters["items"])[0]
    with pytest.raises(TypeError):
        cast(dict[str, object], inner)["name"] = "changed"


def test_frozenmap_attribute_assignment_is_blocked() -> None:
    intent = _intent()
    # setattr (not attribute syntax) keeps the intentionally-unknown attribute
    # name off mypy's radar while still routing through FrozenMap.__setattr__.
    with pytest.raises(TypeError, match="canonical contract values are immutable"):
        setattr(intent.parameters, "injected", 1)  # noqa: B010


def test_unbound_list_descriptor_cannot_mutate_tuple() -> None:
    intent = _intent()
    items = intent.parameters["items"]
    with pytest.raises(TypeError, match="doesn't apply"):
        list.append(cast(list[object], items), "changed")


def test_unbound_dict_descriptors_cannot_mutate_frozen_map() -> None:
    intent = _intent()
    params = cast(dict[str, object], intent.parameters)
    with pytest.raises(TypeError, match="doesn't apply"):
        dict.update(params, {"z": 1})
    with pytest.raises(TypeError, match="requires a 'dict'"):
        dict.__setitem__(params, "z", 1)
    with pytest.raises(TypeError, match="doesn't apply"):
        dict.clear(params)


def test_model_copy_update_is_forbidden() -> None:
    intent = _intent()
    with pytest.raises(TypeError, match="cannot be updated by copy"):
        intent.model_copy(update={"parameters": {}})


def test_model_copy_without_update_returns_equal_model() -> None:
    intent = _intent()
    clone = intent.model_copy()
    assert clone == intent
    assert canonical_digest(clone) == canonical_digest(intent)


def test_frozen_model_attribute_assignment_is_blocked() -> None:
    intent = _intent()
    with pytest.raises(ValidationError) as exc_info:
        intent.service = "other"
    assert exc_info.value.errors()[0]["type"] == "frozen_instance"


def test_frozen_map_copy_and_deepcopy_are_identity() -> None:
    params = _intent().parameters
    assert copy(params) is params
    assert deepcopy(params) is params


def test_frozen_map_equality_and_hash_are_value_based() -> None:
    left = _intent().parameters
    right = _intent().parameters
    assert left == right
    assert hash(left) == hash(right)
