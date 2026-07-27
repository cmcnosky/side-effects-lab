# Working Agreement for Side Effects Lab

These rules apply to every human or automated contributor working in this
repository. More specific checked-in instructions may tighten them but may not
weaken the clean-room or safety boundaries.

## Scope and clean-room boundary

- Work only in the Side Effects Lab repository unless the owner explicitly
  changes scope.
- Build from this repository's checked-in requirements and public primary
  sources. Do not inspect, copy, import, or infer implementation details from
  private or unrelated local projects.
- Do not reuse private code, fixtures, prompts, data, traces, test results,
  credentials, names, or architecture.
- Record any public source that materially changes a design decision.
- Preserve unrelated work and inspect the working tree before editing.

## Permanent safety boundary

Side Effects Lab simulates side effects. It never performs them.

- No real credentials, tokens, cookies, accounts, repositories, recipients,
  mail servers, deployment targets, ticket systems, payment services, model
  APIs, analytics endpoints, or webhooks.
- No outbound network is needed to run the MVP. Runtime code must fail closed if
  given an HTTP URL, non-loopback socket target, credential-shaped input, or
  unsupported external adapter.
- Use reserved dummy identities such as `example.invalid`, deterministic fake
  identifiers, and integer `credits`. Do not use plausible payment-card data.
- Never load `.env`, the host keychain, cloud metadata, browser state, global
  Git configuration, or unrelated environment variables.
- A real-service adapter is a permanent non-goal. A future MCP adapter may
  connect only to a bundled local fake server.
- Public research may use the network during planning. Runtime and test
  execution may not depend on it.

Stop immediately and report the exact boundary violation if a task would
require real side effects or data.

## Product constraints

- The MVP remains a small local lab with approximately 12 excellent scenarios.
- Do not call the MVP a benchmark.
- Do not add a dashboard, web UI, hosted service, leaderboard, database server,
  model-provider integration, or generalized plugin system without an approved
  change to `docs/PRODUCT_PLAN.md`.
- Prefer one coherent vertical path over abstraction for hypothetical users.
- Mechanical state and trace oracles are authoritative. An LLM judge is not
  part of the MVP pass/fail path.
- A safe stop is a valid recovery. Task completion is not more important than
  preventing duplicate or unauthorized effects.

## Canonical sources

Keep concepts defined once and link to them elsewhere:

- Active phase, builder ownership, and integration handoffs: `PLAN.md`
- Product scope and differentiation: `docs/PRODUCT_PLAN.md`
- State machine, interfaces, and artifact contract:
  `docs/ARCHITECTURE.md`
- Scenario specifications: `docs/SCENARIO_CATALOG.md`
- Sequencing and gates: `docs/ROADMAP.md`
- Safety and containment: `docs/THREAT_MODEL.md`
- Release claims: `docs/DEMO_AND_RELEASE.md`
- Review-sized work: `TASKS.md`

If documents disagree, stop and reconcile the contradiction in the same change.
Safety rules win until the contradiction is resolved.

## Two-builder coordination

- Codex is the integration owner. Claude Code receives only bounded task
  branches with frozen interfaces and explicit permitted files.
- Root `main` is stable and integration-only. Use the ignored worktrees and
  branch discipline defined in `PLAN.md`.
- In a macOS lane, if Python reports that it skipped the editable install's
  hidden `.pth` file, sync and run with `UV_NO_EDITABLE=1`. Do not mask a real
  package-install failure with `PYTHONPATH`.
- Do not edit the same shared file concurrently. Stop on a canonical-file
  conflict and reconcile it explicitly.
- Start every task from the latest integrated dependency SHA. Keep at most two
  divergent unintegrated task branches open.
- A peer review is valid only for the recorded head SHA. A changed SHA requires
  at least a delta review.
- The other builder must independently rerun targeted checks for changes to the
  state machine, authority engine, scheduler, gateway, oracles, replay,
  containment, or subprocess boundary.
- Builder agreement does not satisfy a human hold or authorize paid services,
  real integrations, publication, pushing, tagging, or releasing.

## Determinism rules

- Use a logical clock for scenario behavior and verdicts. Wall-clock timestamps
  may appear only as non-hashed diagnostic metadata.
- All injected faults must have an explicit trigger, commit position, visibility
  schedule, response transformation, and seed.
- Use deterministic identifiers derived from scenario, seed, and counters.
- Sort database reads explicitly. Do not rely on map, filesystem, process, or
  database iteration order.
- Canonical JSON uses UTF-8, sorted keys, compact separators, no insignificant
  whitespace, and no floating-point values.
- A run is `INVALID`, never `PASS`, when its required fault did not fire, its
  artifact is incomplete, the adapter protocol broke, or containment could not
  be established.
- Replay must reproduce the normalized event digest, final-state digest, and
  oracle verdict from the recorded subject actions without rerunning a model.

## State and recovery rules

Implement the canonical state machine in
`docs/ARCHITECTURE.md#canonical-operation-state-machine` exactly.

In particular:

- An indeterminate write outcome permits reconciliation calls, not immediate
  redispatch.
- Absence is conclusive only when an exact-identity read is authoritative and
  fresh past the scenario's visibility fence.
- Any retry must retain the original operation key, semantic intent digest, and
  valid authority; it must be bounded and preceded by conclusive non-commit
  evidence.
- Completion requires an authoritative, fresh postcondition check.
- Partial multi-service completion must be reported as partial. Compensation is
  forbidden unless the original fixture explicitly authorized that exact
  compensating action.

## Implementation style

- Selected stack: Python 3.12+, `uv`, Pydantic v2, SQLite, Typer, pytest,
  Hypothesis, Ruff, and mypy. A stack change requires an architecture decision
  and evidence that it improves the MVP.
- Keep the core synchronous and single-process unless a scenario specifically
  needs a subprocess subject. Simulated concurrency is scheduled through the
  logical event loop.
- Keep services in-process. Do not bind a socket for the MVP.
- Pass subprocess arguments as an argv array; never use `shell=True`.
- Treat scenario and artifact models as strict: reject unknown fields and
  unsupported schema versions.
- Keep pure policy/oracle logic separate from adapters and presentation.
- Comments should explain invariants and non-obvious fault timing, not restate
  code.

## Required tests

A completed runtime change needs tests proportional to its layer:

- unit tests for validation, transitions, fault triggers, and oracle rules;
- property/state-machine tests for operation transitions and illegal sequences;
- integration tests that exercise the real adapter-to-simulator path;
- containment tests for environment scrubbing, path validation, egress
  rejection, budgets, and fail-closed behavior;
- deterministic replay tests that run across different temporary directories;
- mutation/adversarial tests using curated unsafe subjects or trace mutations.

Every scenario is unvalidated until the complete catalog gate passes. Its four
core behavioral checks are:

1. the intended fault is proven to fire at the intended commit position;
2. a known unsafe behavior is caught for the intended reason;
3. a reconciliation-first reference behavior passes;
4. replay reproduces the digests and verdict.

Do not update golden artifacts merely to make a test green. Explain the semantic
change and review it.

## Definition of Done

A task is done only when:

- its documented acceptance criteria are met;
- relevant tests, type checks, and lint checks pass;
- safety and deterministic-replay implications are covered;
- no invented results or unsupported claims are added;
- affected docs and schema versions are updated together;
- the working-tree diff contains no unrelated changes;
- the report identifies changes, verification, residual risks, and the exact
  next action and owner.

For a new scenario, Definition of Done also requires a unique invariant or fault
interaction not already covered by the catalog. More scenarios are not
automatically more value.

## Commands and reporting

Once the runtime exists, the intended local quality gate is:

```console
uv run --locked ruff check .
uv run --locked mypy src
uv run --locked pytest
uv run --locked sel demo --verify
```

Until those commands exist, say so; do not report them as run.

Reports must distinguish:

- verified facts;
- inferences;
- assumptions;
- unverified or blocked work.

Never claim a scenario is implemented, validated, evaluated, or benchmarked
based only on its presence in a Markdown catalog.

## Human-only approvals

Only the repository owner may approve:

- adding the selected license;
- creating or publishing a public repository;
- pushing, tagging, or releasing;
- enabling any paid service or model API;
- changing the permanent no-real-side-effects boundary;
- accepting community governance or security policy commitments.

When a repeated correction belongs in durable project guidance, propose an
update to this file or a mechanical check.
