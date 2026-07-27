# Side Effects Lab — Two-Builder Master Execution Plan

## Current phase

**Planning is accepted. Wave 1 is active; T001 and the corrected T002A are
integrated, and T002B contract-test implementation is next from that frozen
base. Runtime implementation has not started.**

- Integration owner: Codex
- Independent implementation and adversarial-review lane: Claude Code
- Planning baseline before this plan: `3c21b55135e9d3b8061e6c423bd4ee2126461eb4`
- Current implementation task: T002B from the corrected T002A integration SHA
- First synchronization point: T002 contract freeze
- First human hold: T016 after the validated SEL-001 slice

This document controls active sequencing, ownership, synchronization, and
handoffs. It does not redefine product scope, architecture, scenarios, safety,
or release claims; those remain in the linked canonical documents.

## Objective and schedule

Use one continuously available high-capacity Codex session and one continuously
available high-capacity Claude Code session to shorten elapsed delivery time
and strengthen independent evidence. This is a two-builder plan, not a claim of
40 concurrent workers.

Expected elapsed schedule:

- first validated slice: **5.5–6.5 focused weekdays**;
- portfolio-ready: **20–23 focused weekdays**, normally **4–5 calendar weeks**;
- community-ready: **5–7 calendar weeks**, depending on external reviewers and
  human approvals.

Independent review can increase total AI effort. The intended gain is shorter
critical-path time and better fault finding, not half the labor.

## Sources of truth

- Product scope and differentiation:
  [PRODUCT_PLAN.md](docs/PRODUCT_PLAN.md)
- Architecture, contracts, state machine, replay, and artifact schema:
  [ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Scenario semantics and mechanical oracles:
  [SCENARIO_CATALOG.md](docs/SCENARIO_CATALOG.md)
- Milestones and elapsed estimates: [ROADMAP.md](docs/ROADMAP.md)
- Safety and containment: [THREAT_MODEL.md](docs/THREAT_MODEL.md)
- Claims, demo, and release controls:
  [DEMO_AND_RELEASE.md](docs/DEMO_AND_RELEASE.md)
- Review-sized task definitions and Definition of Done: [TASKS.md](TASKS.md)
- Builder rules: [AGENTS.md](AGENTS.md)

If this execution plan conflicts with a canonical source, integration stops
until the documents are reconciled. Safety rules prevail while a contradiction
is unresolved.

## Operating model

Root `main` remains stable and integration-only. Local worktrees are ignored
repository state:

```text
.worktrees/integration  integration branch and phase gates
.worktrees/codex        current Codex task branch
.worktrees/claude       current Claude Code task branch or detached standby
.coordination/handoffs  ignored local handoff records
```

Rules:

1. Codex exclusively performs integration merges and owns the dependency
   lockfile, shared contracts and registries after freeze, generated schemas and
   golden artifacts, canonical CLI registration, status, release, and claims
   edits.
2. Each implementation task starts from the latest integrated dependency SHA,
   uses its own branch, and ends in one intentional conventional commit.
3. Keep no more than two divergent, unintegrated task branches open.
4. Never assign the same shared file to both builders concurrently. A frozen
   interface permits parallel module work; it does not permit concurrent
   contract edits.
5. Dense dependency work remains serial: contract freeze, state machine,
   gateway, replay, full-suite integration, and every human approval.
6. If a dependency blocks implementation, the non-driving builder performs
   review, adversarial fixture design, targeted test design, or alternate-root
   replay work against an already frozen interface.
7. Only the integration branch runs a phase gate. `main` advances only after
   that complete gate passes.
8. Conflicts in canonical files stop integration. Do not resolve them
   mechanically with `ours`, `theirs`, or an unreviewed regeneration.

## Stable ownership

Codex owns:

- integration and all canonical shared files;
- email, payments, and deployment service modules;
- SEL-002, SEL-003, SEL-005, SEL-006, SEL-010, SEL-011, and SEL-012.

Claude Code owns:

- ticketing, GitHub concurrency evolution, and workflow/group state;
- SEL-004, SEL-007, SEL-008, and SEL-009;
- independent hostile-input, mutation-reason, replay, containment, and claims
  reviews assigned below.

The minimal GitHub service and SEL-001 are joint integration work with exactly
one writer per file at a time.

## Parallel execution waves

| Wave | Codex lane | Claude Code lane | Synchronization gate |
| --- | --- | --- | --- |
| 1 — Contracts | T001 and T002A implementation | Draft the T002B negative-test matrix in parallel; implement it after T002A lands | Freeze scenario, protocol, event, authority, and artifact contracts. |
| 2 — Kernel | T003 → T004 → T006 | After T004 lands: T005 and T007 | State-machine, authority, property, and ledger checks pass together. |
| 3 — Execution core | T008 → T009 | T012 → T013 | Freeze gateway, event, oracle, and artifact interfaces. |
| 4 — Vertical components | T010, then T014 after T011 merges | T011, then SEL-001 fixtures and unsafe mutations | Merge all T008–T014 dependencies. |
| 5 — Vertical acceptance | T015A end-to-end integration | T015B alternate-root, containment, mutation, and replay verification | The exact SEL-001 gate passes; stop for T016. |
| 6 — Shared recovery | T017A implementation | T017B adversarial and freshness tests | Conclusive-absence semantics are frozen. |
| 7 — Core services | T018 → T019 → T024, then T020 → T021 | T022 → T023 → T025 | Six scenarios validate without shared service-file conflicts. |
| 8 — Catalog decision | T026A uniqueness matrix | T026B independent redundancy challenge | Work records `PROCEED`, `PIVOT UPSTREAM`, or `STOP` for material changes. |
| 9 — Complete MVP | T027 → T028 → T033, plus T034 and T035 | T029 → T030, then T031 → T032 | All scenario implementations merge before T036. |
| 10 — Full validation | T036A canonical full matrix and artifacts | T036B mutation-reason and alternate-seed/root audit | All required 12 scenarios validate; stop for T037. |
| 11 — Adapter | T038A subprocess adapter core | T038B black-box protocol and hostile-output conformance | Freeze the opt-in NDJSON adapter contract. |
| 12 — Portfolio hardening | T039, T040B demo/adapter containment, and T042A clean-clone audit | T040A general containment, T041 Linux CI, and T042B claims/link audit | Portfolio gate passes on the exact integrated SHA. |
| 13 — Community hardening | T044A schema policy, scenario template, and macOS CI | T044B contribution, security, conduct, and independent claim review | Two genuinely external T045 reproductions complete. |
| 14 — Release candidate | T046A candidate, checksums, and canonical wording | T046B refreshed primary-source adjacency and claims audit | Work performs T047; nothing publishes automatically. |

The arrows express serial dependencies inside one lane. They do not authorize
starting a later task before its `TASKS.md` dependencies have landed.

## Human holds

Agreement between Codex and Claude Code never substitutes for Work approval.

| Task | Decision retained by Work |
| --- | --- |
| T016 | Choose `PROCEED`, `PIVOT UPSTREAM`, or `STOP` after novelty evidence. |
| T026 | Approve any material catalog scope change. |
| T037 | Approve the trusted local subprocess boundary. |
| T043 | Approve and add the selected license. |
| T045 | Coordinate two genuinely external clean-clone reproductions. |
| T047 | Approve any remote creation, push, tag, release, publication, or announcement. |

Paid services, real integrations, real credentials or recipients, public
publication, and any weakening of the no-real-side-effects boundary remain
human-only decisions. They are not implied by this plan.

## Gate discipline

| Gate | Required evidence |
| --- | --- |
| Contract | Strict models, schema generation, canonical JSON, negative fixtures, and type checks pass before parallel runtime modules begin. |
| Kernel | Every allowed transition is tested; stale absence, changed identity, expired authority, and completion without verification fail mechanically. |
| Vertical | SEL-001 proves commit before response loss; blind retry fails; reconciliation-first produces exactly one verified issue; missed injection is `INVALID`; replay matches across two roots; containment catches sockets, credentials, and escaped writes. |
| Catalog | Every implemented scenario adds a distinct fault or invariant; redundant entries are removed instead of padded. |
| MVP | All 12 required faults fire, unsafe mutants fail for the intended reason, safe references reach allowed terminal states, replay matches, and the suite stays under two minutes. |
| Adapter | Subprocess support is explicit opt-in, scrubs the environment, enforces budgets, rejects malformed protocol, and is never described as a sandbox. |
| Portfolio | Demo completes in under 30 seconds after setup; CI runs lint, types, tests, replay, containment, and demo verification; a clean clone reproduces the exact integrated SHA. |
| Publication | License, external reproductions, refreshed sources, history/secret review, exact release CI, wording, and explicit Work approval are complete. |

Gate-critical changes to the state machine, authority engine, scheduler, gateway,
oracles, replay, containment, or subprocess boundary require the other builder
to rerun targeted checks independently.

## Task packet and handoff contract

Before work starts, the integration owner gives the builder:

- exact task or subtask ID;
- task branch and base SHA;
- permitted files and modules;
- landed dependencies and frozen interface versions;
- task Definition of Done and exact commands to run;
- clean-room and safety restrictions.

Every handoff records:

```text
task:
branch:
base_sha:
head_sha:
permitted_files:
changed_contracts:
checks_and_exit_status:
safety_replay_schema_implications:
residual_risks:
git_status:
next_owner:
```

The peer review result is exactly `APPROVE` or `CHANGES_REQUESTED`, followed by
specific evidence. Any new head SHA invalidates the prior approval and requires
at least a delta review. A handoff with a dirty worktree, an unlisted contract
change, or a failing required check is not merge-ready.

## Immediate launch order

1. Codex starts T002A from the integrated T001 SHA while Claude Code prepares
   the T002B negative-test matrix without editing shared files.
2. Codex integrates T002A.
3. Claude Code creates T002B from that integrated dependency SHA and turns its
   prepared matrix into negative fixtures and contract tests in permitted test
   paths.
4. Codex integrates T002A/T002B, runs the contract gate, records the frozen
   schema digests, and then opens Wave 2.

The exact first-slice acceptance gate is the six-part Milestone 2 gate in
[ROADMAP.md](docs/ROADMAP.md#milestone-2--first-vertical-slice).
