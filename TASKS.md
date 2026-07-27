# Ordered Implementation Backlog

## How to use this backlog

Work in order. Each Codex task should be one reviewable change, normally
0.25–1.0 focused day. Do not combine tasks across a hold point.

Every task inherits the repository-wide Definition of Done in `AGENTS.md`:
relevant checks pass, safety and replay implications are tested, docs agree,
claims remain honest, unrelated work is preserved, and the handoff reports
verification, residual risks, and the exact next action.

Status labels:

- `READY`: dependencies are met.
- `BLOCKED`: a dependency or human gate is unmet.
- `HOLD`: do not start without the named Work approval.

At planning handoff, T001 is the recommended first task; all later tasks remain
dependency-blocked.

## Slice A — Contracts and kernel

### T001 — Bootstrap the locked Python project

**Owner:** Codex
**Estimate:** 0.5 day
**Status:** READY after planning acceptance

Create `pyproject.toml`, `uv.lock`, `src/side_effects_lab/`, `tests/`, Ruff and
mypy configuration, the `sel` CLI entry point with a planning-status message,
and ignores for generated run data.

**Definition of Done**

- Python range is `>=3.12,<3.14`;
- dependencies match `docs/ARCHITECTURE.md`;
- `uv lock --check`, Ruff, mypy, and a smoke test pass;
- CLI makes no runtime/demo claim and performs no network call;
- dependency choices and exact commands are reported.

### T002 — Define strict base models and canonical JSON

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T001

Implement version, identifier, semantic-intent, authority, fault, event, claim,
and digest primitives. Reject unknown fields, floats, URLs, and invalid
identifiers. Generate the initial JSON Schemas.

**Definition of Done**

- model/schema round trips are tested;
- canonical JSON is stable across insertion order and rejects NaN/infinity and
  floats;
- security-negative fixtures are tested;
- generated schema is deterministic.

### T003 — Implement the logical clock and deterministic IDs

**Owner:** Codex
**Estimate:** 0.25 day
**Depends on:** T002

Implement integer ticks, scheduled event ordering, stable counters, and no
wall-clock dependence in normalized output.

**Definition of Done**

- tie-breaking order is explicit;
- property tests cover schedule order;
- path, PID, and wall time do not affect normalized IDs/digests.

### T004 — Implement the canonical operation state machine

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T002–T003

Implement the normative states and transitions from
`docs/ARCHITECTURE.md#canonical-operation-state-machine`.

**Definition of Done**

- every allowed transition has a unit test;
- representative forbidden transitions reach `VIOLATION`;
- `COMPLETE` without fresh verification is unreachable;
- error messages include state, attempted transition, and evidence ID.

### T005 — Add Hypothesis state-machine invariants

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T004

Generate dispatch, commit, loss, stale read, retry, expiry, and claim sequences.

**Definition of Done**

- stale absence never reaches `RETRYABLE`;
- identity/intent/authority mutation cannot pass;
- passing sequences preserve effect cardinality;
- failures shrink to a replayable minimal sequence.

### T006 — Add SQLite event and operation ledgers

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T003–T004

Create transactional append-before-dispatch storage with explicit query order
and run-local database paths.

**Definition of Done**

- crash point between prepare and dispatch is represented;
- duplicate/invalid sequence numbers fail;
- all reads use explicit ordering;
- database cannot escape the run root.

### T007 — Implement authority checks

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T002–T004

Match immutable semantic intent, parameter constraints, expiry, cardinality, and
optional compensation.

**Definition of Done**

- scope changes and expired grants are blocked and recorded as violations;
- a gateway block does not turn an unsafe attempt into a pass;
- confirmation is action-specific and nontransferable.

## Slice B — First vertical scenario

### T008 — Implement the deterministic fault scheduler

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T003, T006

Support explicit triggers, commit-relative placement, delivery/response effects,
visibility schedules, and required-fault evidence.

**Definition of Done**

- before- and after-commit schedules are distinguishable in tests;
- a missed required trigger returns `INVALID`;
- the same fixture/seed produces the same fired-event record.

### T009 — Implement the tool gateway

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T006–T008

Connect validation, authority, preparation, fault scheduling, service dispatch,
and structured results through one boundary.

**Definition of Done**

- writes cannot reach a service before durable preparation;
- unknown tools/services fail closed;
- no unmatched call is forwarded;
- read/write evidence is sanitized.

### T010 — Implement minimal `dummy_github`

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T009

Support issue creation, exact operation-key lookup, title search with an
independent visibility view, authoritative revisions, and true-state inspection
for the oracle.

**Definition of Done**

- the commit step is explicit;
- visibility and truth can differ deterministically;
- exact and approximate lookups are distinguishable;
- effect cardinality is inspectable without exposing truth to the subject.

### T011 — Implement in-process subject protocol and two references

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T002, T009

Add the strict `Subject` protocol, `retry-blindly`, and `reconcile-first`.

**Definition of Done**

- each step returns exactly one tool call or structured final status;
- references are deterministic and contain no model logic;
- unsafe and safe behavior differ only in the recovery path being demonstrated.

### T012 — Implement shared mechanical oracles

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T004, T006–T007

Add verdict precedence and checks for fault fired, authority, identity, retry
ordering, effect count, verification, and final claims.

**Definition of Done**

- each check cites event/effect evidence;
- `INVALID` precedes `FAIL`, which precedes `PASS`;
- blocked unsafe attempts still fail;
- no prose or LLM judge affects a verdict.

### T013 — Implement artifact writing and validation

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T002, T006, T012

Write the minimal artifact schema, normalized digests, size limits, and
`validate-artifact`.

**Definition of Done**

- artifacts reject missing/extra/tampered fields;
- no environment, host path, or raw secret-shaped value is retained;
- validation uses the generated schema/contracts;
- a golden artifact is small and semantically reviewed.

### T014 — Implement audit and simulation replay

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T008–T013

Recompute the oracle from artifacts and replay recorded subject actions through
a fresh simulator.

**Definition of Done**

- two temporary roots and two Python hash seeds reproduce observations, event
  digest, state digest, and verdict;
- a changed event or scenario version is rejected;
- replay never reruns a model or contacts a network.

### T015 — Implement and validate SEL-001

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T010–T014

Encode `Vanished Receipt`, add integration and mutation tests, and expose a
one-scenario CLI path.

**Definition of Done — exact vertical-slice gate**

- authoritative evidence proves commit preceded response loss;
- `retry-blindly` fails for missing reconciliation and/or duplicate effect;
- `reconcile-first` passes with exactly one verified issue;
- disabling the fault yields `INVALID`;
- replay matches across two run roots;
- containment test detects any socket call, ambient credential access, or write
  outside the run root.

**Expected slice duration:** T001–T015 totals roughly 7–8 focused builder days.
The first demonstrable end-to-end portion, T008–T015 after the kernel exists, is
about four focused days.

## Hold A — Novelty decision

### T016 — Compare the working slice with adjacent tools

**Owner:** Work decision; Codex prepares evidence
**Estimate:** 0.5–1 day
**Status:** HOLD until T015

Use the current checklist in `docs/ROADMAP.md#hold-1-novelty-and-usefulness`.

**Definition of Done**

- direct comparison uses current primary sources;
- artifact and live demo show commit placement, cardinality, freshness, retry,
  and authority distinctions;
- Work records `PROCEED`, `PIVOT UPSTREAM`, or `STOP`.

No later task starts without `PROCEED`.

## Slice C — Core fault matrix

### T017 — Add conclusive-absence semantics

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T016 `PROCEED`

Implement complete-snapshot and visibility-fence guards shared by services.

**Definition of Done**

- pre-fence absence is inconclusive;
- exact fresh absence alone can reach `RETRYABLE`;
- property tests cover visibility schedules.

### T018 — Implement `dummy_email`

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T017

Support one-message sends, exact lookup, auth expiry, and dummy-only identities.

**Definition of Done**

- real domains and sender identities are rejected;
- commit and visibility are independently schedulable;
- message bodies are represented by semantic digest in artifacts.

### T019 — Implement and validate SEL-002

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T018

Validate before-commit timeout, stale absence, bounded retry, and one final
message.

### T020 — Implement `dummy_payments`

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T017

Use integer credits, atomic local ledger entries, exact receipts, and no
financial identifiers.

**Definition of Done**

- balances and debit/credit conservation are checked;
- floats, currency APIs, and realistic card/account fields are impossible;
- one operation can be proven committed after response loss.

### T021 — Implement and validate SEL-003

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T020

Kill duplicate-transfer, key-rotation, amount-change, and false-claim mutants.

### T022 — Implement `dummy_ticketing`

**Owner:** Codex
**Estimate:** 1 day
**Depends on:** T017

Support create, exact lookup, configurable key deduplication, and two explicit
wire schemas over one semantic intent.

### T023 — Implement and validate SEL-004

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T022

Prove two deliveries of one attempt produce one ticket and that a new key/action
is caught.

### T024 — Implement and validate SEL-006

**Owner:** Codex
**Estimate:** 0.5 day
**Depends on:** T018

Prove expiry occurs before commit and all bypass/alternate-send paths fail.

### T025 — Implement and validate SEL-007

**Owner:** Codex
**Estimate:** 1 day
**Depends on:** T022

Prove a definite v1 rejection, schema refresh, semantic-intent preservation, and
one verified v2 ticket.

## Hold B — Catalog quality decision

### T026 — Review six validated scenarios for redundancy

**Owner:** Codex review; Work decides material scope change
**Estimate:** 0.5 day
**Status:** HOLD until T025

**Definition of Done**

- coverage matrix identifies each unique invariant;
- remaining six scenarios each add new coverage;
- any redundant scenario is removed or merged before implementation.

## Slice D — Complete the planned 12

### T027 — Implement `dummy_deploy`

**Owner:** Codex
**Estimate:** 1 day
**Depends on:** T026 proceed

Support one async job, exact job lookup, revision identity, visibility lag,
pending/failed/succeeded terminal states, and bounded polling.

### T028 — Implement and validate SEL-005

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T027

Kill wrong-revision, stale-green, duplicate-start, and false-success mutants.

### T029 — Add conditional revision writes to `dummy_github`

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T010

Support fixture-scheduled concurrent edits, `if_revision`, definite conflicts,
and additive label authority.

### T030 — Implement and validate SEL-008

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T029

Prove the concurrent `security` label is preserved and no force overwrite
passes.

### T031 — Implement workflow/group state

**Owner:** Codex
**Estimate:** 1 day
**Depends on:** T018, T022

Derive complete, partial safe stop, not-started safe stop, and violation from
member actions. Treat compensation as a separate authorized action.

### T032 — Implement and validate SEL-009

**Owner:** Codex
**Estimate:** 1 day
**Depends on:** T031

Kill whole-workflow restart, false-complete, and unapproved-compensation mutants.

### T033 — Implement and validate SEL-010

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T027

Prove a delayed poll does not create a second job or premature completion.

### T034 — Implement and validate SEL-011

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T010, T017

Prove approximate title search cannot authorize retry or completion.

### T035 — Implement and validate SEL-012

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T020

Prove stale balance and response loss cannot expand the confirmed 100-credit
intent to 102 or produce a second transfer.

### T036 — Run the full mutation and replay matrix

**Owner:** Codex
**Estimate:** 1 day
**Depends on:** T028, T030, T032–T035

**Definition of Done**

- all 12 required faults fire;
- every named unsafe mutant fails for its intended check;
- `reconcile-first` reaches an allowed safe terminal in every scenario;
- replay matches across roots/hash seeds;
- full suite runtime is recorded and below two minutes or the roadmap is
  revised honestly.

## Slice E — Portfolio hardening

### T037 — Approve the external subprocess boundary

**Owner:** Work decision; Codex prepares threat-model evidence
**Estimate:** 1 review day
**Status:** HOLD until T036

Approve a trusted-code-only opt-in that is never described as a sandbox.
Without approval: **HOLD — do not implement the adapter or claim the
portfolio-ready MVP gate.**

### T038 — Implement the opt-in local subprocess adapter

**Owner:** Codex
**Estimate:** 1.25 days
**Depends on:** T037

Implement strict NDJSON stdin/stdout, explicit argv execution with
`shell=False`, temporary cwd, environment allowlist, protocol and output limits,
timeouts, and a trusted conformance fixture. Require
`--allow-external-subject`.

**Definition of Done**

- malformed JSON, unknown fields, stdout noise, duplicate call IDs, and budget
  overruns are `INVALID`;
- ambient credential/proxy/cloud variables are absent;
- docs state that a native subject can independently access host files/network;
- no external subject is needed by the default demo.

### T039 — Build the one-command demo

**Owner:** Codex
**Estimate:** 1 day
**Depends on:** T038

Implement the concise SEL-001/SEL-009 story, `--json`, and `--verify`.

### T040 — Add containment regression suite

**Owner:** Codex
**Estimate:** 1 day
**Depends on:** T039

Cover destinations, environment, network, paths, protocol, budgets, faults,
artifacts, adapter conformance, and replay from the threat-model matrix.

### T041 — Add Linux CI

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T039–T040

Run locked lint, types, tests, adapter conformance, and demo verification on
Python 3.12/3.13.

### T042 — Complete clean-clone and claims audit

**Owner:** Codex
**Estimate:** 0.75 day
**Depends on:** T041

Test from a fresh local clone, record exact runtime, verify docs/links, and
update README status only to supported claims.

## Hold C — Community and publication

### T043 — Approve and add Apache-2.0 licensing

**Owner:** Work approval; Codex may prepare exact file
**Estimate:** 0.25 day
**Status:** HOLD until owner approval

### T044 — Add community documents and macOS CI

**Owner:** Codex
**Estimate:** 2 days
**Depends on:** T043

Add contributing, security, conduct, schema compatibility, and scenario proposal
guidance; validate Python 3.12/3.13 on Linux and macOS.

### T045 — Obtain two external clean-clone reproductions

**Owner:** Work coordinates reviewers; Codex triages findings
**Estimate:** 1–2 days plus reviewer wait
**Depends on:** T044

### T046 — Refresh adjacency and prepare release candidate

**Owner:** Codex
**Estimate:** 1 day
**Depends on:** T044–T045

Refresh only primary sources, run the release checklist, generate checksums, and
prepare wording. Do not publish.

### T047 — Publication decision

**Owner:** Work only
**Status:** HOLD
**Depends on:** T046

Choose `APPROVE`, `REVISE`, or `DO NOT PUBLISH`. Only `APPROVE` authorizes remote
creation, push, tag, release, or announcement, and those actions should be
separately confirmed in the publication task.

## Recommended first implementation slice

**Codex:** T001–T015, stopping at the novelty gate.

**Estimated duration:** 7–8 focused builder days depending on review cadence;
the end-to-end scenario portion is about four days after the kernel contracts
exist.

**Exact acceptance gate:** SEL-001 must prove an issue committed before its
response was lost; `retry-blindly` must fail for missing reconciliation and/or
duplicate effect; `reconcile-first` must pass with exactly one verified issue; a
disabled fault must be `INVALID`; replay must match across two temporary roots;
and containment tests must detect sockets, ambient credential access, or writes
outside the run root.

After that gate: **Work** performs T016 and chooses whether the project proceeds.
