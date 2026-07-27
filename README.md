# Side Effects Lab

Side Effects Lab is a planned, vendor-neutral reliability lab for agents that
use tools with real-world-shaped side effects.

The lab will answer a narrow question:

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

Within the portfolio positioning supplied for this project, Stinger covers
integrity and specification-gaming while Side Effects Lab covers stateful tool
reliability and recovery. They are separate projects: this repository does not
inspect, import, depend on, or reuse Stinger code, data, artifacts, or results.

## Status

**Bootstrap only.** This repository contains architecture and product documents,
a locked Python package skeleton, and a planning-status CLI. It does not contain
a runtime, simulator, validated scenario, evaluation result, release, or working
integration.

The only implemented command reports that status:

```console
uv run --locked sel
```

The target future command shown in the plan is:

```console
uv run --locked sel demo
```

The `demo` command does not exist yet.

## Honest non-claims

Side Effects Lab does not currently:

- prove that any model or agent is reliable;
- implement or validate the 12 catalogued scenarios;
- qualify as a benchmark;
- protect a host from a malicious external subject process;
- support real GitHub, email, deployment, ticketing, payment, or MCP services;
- provide exactly-once delivery, which generally cannot be inferred from a lost
  response;
- have an open-source license in force. Apache-2.0 is the selected intended
  license, but the repository is not licensed until the owner approves and adds
  a `LICENSE` file.

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
