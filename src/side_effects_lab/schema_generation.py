"""Deterministically render and verify the initial contract schemas."""

from argparse import ArgumentParser
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

from side_effects_lab.canonical import canonical_json_bytes
from side_effects_lab.models import (
    CURRENT_SCHEMA_VERSION,
    ActionClaim,
    AuthorityGrant,
    FaultSpec,
    LabEvent,
    SemanticIntent,
)

SCHEMA_ROOT = Path("schemas") / CURRENT_SCHEMA_VERSION
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

SCHEMA_MODELS: Mapping[str, type[BaseModel]] = {
    "action-claim.schema.json": ActionClaim,
    "authority-grant.schema.json": AuthorityGrant,
    "event.schema.json": LabEvent,
    "fault-spec.schema.json": FaultSpec,
    "semantic-intent.schema.json": SemanticIntent,
}


def render_schema(model: type[BaseModel]) -> bytes:
    document = model.model_json_schema(mode="validation")
    document["$schema"] = SCHEMA_DIALECT
    document["x-side-effects-lab-schema-version"] = CURRENT_SCHEMA_VERSION
    return canonical_json_bytes(document) + b"\n"


def expected_schemas() -> dict[str, bytes]:
    return {
        name: render_schema(model)
        for name, model in sorted(SCHEMA_MODELS.items(), key=lambda item: item[0])
    }


def write_schemas(output_dir: Path = SCHEMA_ROOT) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in expected_schemas().items():
        (output_dir / name).write_bytes(content)


def schema_drift(output_dir: Path = SCHEMA_ROOT) -> list[str]:
    expected = expected_schemas()
    actual_names = {path.name for path in output_dir.glob("*.json")}
    problems = [
        f"unexpected schema: {name}" for name in sorted(actual_names - set(expected))
    ]
    for name, content in expected.items():
        path = output_dir / name
        if not path.exists():
            problems.append(f"missing schema: {name}")
        elif path.read_bytes() != content:
            problems.append(f"changed schema: {name}")
    return problems


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=SCHEMA_ROOT)
    args = parser.parse_args()

    if args.write:
        write_schemas(args.output_dir)
        return

    problems = schema_drift(args.output_dir)
    if problems:
        parser.exit(1, "\n".join(problems) + "\n")


if __name__ == "__main__":
    main()
