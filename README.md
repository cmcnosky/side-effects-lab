# Side Effects Lab

Side Effects Lab contains the Python kernel foundation for a planned,
vendor-neutral reliability lab for agents that use tools with real-world-shaped
side effects. The implemented foundation includes strict versioned contracts,
logical time and deterministic identifiers, a guarded operation state machine,
run-local SQLite event and operation ledgers, and action-specific authority
checks. The tool gateway, service simulator, validated scenarios, subject
integration, and executable demo remain planned and are not included in this
snapshot.

The completed lab is intended to answer a narrow question:

> When a tool call might have succeeded but its response is missing, delayed,
> duplicated, stale, or contradictory, does the agent reconcile safely—or
> blindly try again?

Everything in the lab is fake and local. The planned services resemble GitHub,
email, deployments, ticketing, and payments, but they use fixture data,
in-process state, logical time, and dummy units. Side Effects Lab is not
permitted to contact a real account, recipient, deployment, payment rail, or
third party.

## Concrete example

An agent is asked to create one issue. The dummy GitHub service commits the
issue, then the lab drops the success response.

- An unsafe agent immediately retries with a new operation key and creates a
  duplicate.
- A safe agent looks up the original operation by its stable identity, verifies
  that exactly one issue exists, and only then reports completion.
- If the lookup cannot prove either presence or absence, a safe agent stops and
  reports uncertainty. It does not guess.

The oracle reads the simulated service's authoritative state and the event
trace. It does not ask another model to judge whether the answer sounds safe.

## Intended MVP

- 12 curated, deterministic scenarios
- one local command that contrasts a deliberately unsafe reference subject with
  a reconciliation-first reference subject
- mechanical pass, fail, and invalid-run verdicts
- JSON artifacts with replayable fault schedules and evidence
- CI-ready execution with no model key, paid service, container, or network
  dependency
- a five-minute portfolio demonstration

The MVP is intentionally not a dashboard, hosted service, leaderboard, model
ranking exercise, or general chaos-engineering framework.

## Status

**Public inspection snapshot; kernel-foundation stage.** This curated `main`
branch is a work in progress, not a release. It contains the architecture and
product plans, a locked Python package, strict version 0.1 base contracts,
digest-pinned generated schemas, a deterministic logical clock with generic
event ordering and run-local identifiers, the canonical guarded operation
state machine, run-local SQLite event and operation ledgers, pure deterministic
authority checks with action-specific confirmation and fail-closed evidence,
contract/kernel tests, and an implementation-status CLI. It does not contain a
tool gateway, executable lab runtime, service simulator, validated scenario,
evaluation result, release, or working subject integration.

The only implemented command reports that status:

```console
uv run --locked sel
```

The target future command shown in the plan is:

```console
uv run --locked sel demo
```

The `demo` command does not exist yet.

The [foundation CI workflow](.github/workflows/ci.yml) runs only the checks
supported by this snapshot: lockfile drift, Ruff lint and formatting, strict
mypy, pytest, and the status CLI. A passing foundation workflow is not evidence
that the planned lab, demo, or scenarios exist.

## Evaluate the current foundation in five minutes

With Python 3.12 and `uv` installed, run the status command and the focused
kernel checks from the repository root:

```console
uv run --locked sel
uv run --locked pytest -q \
  tests/test_cli.py \
  tests/test_authority_engine.py \
  tests/test_state_machine.py \
  tests/test_state_machine_properties.py
```

Then inspect the implementation beside its tests:

- [guarded operation state machine](src/side_effects_lab/state_machine.py) and
  [its example-based tests](tests/test_state_machine.py);
- [authority engine](src/side_effects_lab/authority.py) and
  [its confirmation and evidence tests](tests/test_authority_engine.py);
- [event and operation ledger](src/side_effects_lab/ledger.py) and
  [its persistence tests](tests/test_ledger.py).

This path evaluates the implemented kernel foundation. The executable demo has
its own publication gate in [the demo and release plan](docs/DEMO_AND_RELEASE.md).

## Authorship and accountability

Chris McNosky is the project owner and is accountable for product scope,
architecture decisions, integration, publication, and the repository's public
claims. The commit history and [execution plan](PLAN.md) preserve the
implementation record.

## Honest non-claims

Side Effects Lab does not currently:

- prove that any model or agent is reliable;
- implement or validate the 12 catalogued scenarios;
- qualify as a benchmark;
- protect a host from a malicious external subject process;
- support real GitHub, email, deployment, ticketing, payment, or MCP services;
- provide exactly-once delivery, which generally cannot be inferred from a lost
  response;
- be open source. Public visibility permits inspection; it does not grant a
  general right to use, copy, modify, or redistribute the work. See
  [Rights and permissions](RIGHTS.md).

## Plan map

- [Two-builder master execution plan](PLAN.md)
- [Product plan](docs/PRODUCT_PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [MVP scenario catalog](docs/SCENARIO_CATALOG.md)
- [Roadmap and stop gates](docs/ROADMAP.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Demo and release plan](docs/DEMO_AND_RELEASE.md)
- [Ordered implementation backlog](TASKS.md)
- [Rules for future agents](AGENTS.md)

## Project stance

The project borrows established ideas—stateful tool environments, deterministic
fault injection, idempotency, reconciliation, and trace-based scoring—but
focuses them on the commit boundary of agent side effects. The adjacent-tools
review found meaningful overlap with newer fault-injection work. The first
working slice must therefore demonstrate a useful distinction, not merely
rename generic timeout testing.

See the [competitive analysis](docs/PRODUCT_PLAN.md#adjacent-work-and-differentiation)
and the [first hold point](docs/ROADMAP.md#hold-1--novelty-and-usefulness).
