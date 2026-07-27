"""Security-shaped inputs at the exact T002A ownership boundary.

Traceability: Architecture containment note ("a string that begins, after
leading whitespace, with generic URI-scheme syntax is rejected in T002-owned
parameters and event evidence; a valid sha256: digest is the sole exception")
and the T002B matrix "URLs and schemes" / "Secret/env/path shapes" rows.

T002A owns exactly two value-shape rejections in its parameter/evidence maps:
generic URI schemes and non-integer numerics. Secret-shaped field names and
plain filesystem paths are deliberately deferred to later containment tasks;
this suite asserts T002A neither enforces nor silently drops them.
"""

from collections.abc import Callable

import pytest
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from side_effects_lab.canonical import canonical_digest
from side_effects_lab.models import CanonicalValue, EventKind, LabEvent, SemanticIntent


def _intent_params(parameters: dict[str, CanonicalValue]) -> SemanticIntent:
    return SemanticIntent(
        service="dummy_github", operation="create_issue", parameters=parameters
    )


REJECTED_SCHEMES = [
    "http://example.invalid/x",
    "https://example.invalid/hook",
    "ftp://example.invalid",
    "file:///etc/passwd",
    "mailto:root@example.invalid",
    "javascript:alert(1)",
    "urn:example:resource",
    "data:text/plain;base64,AA==",
    "C:\\Windows\\system32",
]


@pytest.mark.parametrize("scheme", REJECTED_SCHEMES)
def test_url_schemes_are_rejected_in_parameters(
    scheme: str, assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _intent_params({"target": scheme})
    error = assert_error(exc_info, ("parameters",), "value_error")
    assert "URL schemes are forbidden" in error["msg"]


@pytest.mark.parametrize(
    "scheme", ["  https://example.invalid", "\thttp:evil", " \nftp:x"]
)
def test_leading_whitespace_does_not_bypass_scheme_rejection(scheme: str) -> None:
    with pytest.raises(ValidationError, match="URL schemes are forbidden"):
        _intent_params({"target": scheme})


def test_url_schemes_are_rejected_deep_inside_nested_containers() -> None:
    with pytest.raises(ValidationError, match="URL schemes are forbidden"):
        _intent_params({"a": ["ok", {"b": [{"c": "https://example.invalid"}]}]})


def test_url_schemes_are_rejected_in_event_evidence() -> None:
    with pytest.raises(ValidationError, match="URL schemes are forbidden"):
        LabEvent(
            seq=1,
            tick=0,
            kind=EventKind.READ_OBSERVED,
            evidence={"target": ["nested", "https://example.invalid"]},
        )


def test_from_url_fixture(
    fixture_text: Callable[[str], str], assert_error: Callable[..., ErrorDetails]
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        SemanticIntent.model_validate_json(fixture_text("url_scheme.json"))
    assert_error(exc_info, ("parameters",), "value_error")


def test_valid_sha256_digest_is_the_only_scheme_shaped_exception() -> None:
    digest = canonical_digest({"safe": True})
    intent = _intent_params({"ref": digest})
    assert intent.parameters["ref"] == digest


def test_digest_shaped_but_invalid_value_is_still_rejected() -> None:
    # ``sha256:`` followed by a non-digest body is not the exception; it is a
    # scheme-shaped string and must be refused.
    with pytest.raises(ValidationError, match="URL schemes are forbidden"):
        _intent_params({"ref": "sha256:not-a-real-digest"})


def test_secret_shaped_field_names_are_not_owned_by_t002(
    fixture_text: Callable[[str], str],
) -> None:
    # Secret-shaped names and a unix path are accepted here; T002A owns value
    # *schemes*, not field-name secrecy. Later containment layers own that.
    intent = SemanticIntent.model_validate_json(
        fixture_text("secret_or_env_shape.json")
    )
    assert intent.parameters["api_key"] == "dummy-token-not-real"
    assert intent.parameters["home_path"] == "/home/example/data"
    assert intent.parameters["credits"] == 10


def test_plain_filesystem_paths_are_deferred_not_rejected() -> None:
    intent = _intent_params({"path": "/etc/passwd", "rel": "../secrets"})
    assert intent.parameters["path"] == "/etc/passwd"
    assert intent.parameters["rel"] == "../secrets"


def test_uppercase_env_keys_fail_parameter_grammar_not_secrecy(
    assert_error: Callable[..., ErrorDetails],
) -> None:
    # An environment-blob key like PATH is rejected for violating the parameter
    # name grammar, which is the T002-owned constraint that happens to apply.
    with pytest.raises(ValidationError) as exc_info:
        _intent_params({"PATH": "/usr/bin"})
    error = assert_error(exc_info, ("parameters", "PATH"), "string_pattern_mismatch")
    assert error["loc"][-1] == "[key]"
