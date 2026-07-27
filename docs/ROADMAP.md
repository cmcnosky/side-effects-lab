# Roadmap

## Estimation basis

Estimates assume one strong AI-assisted builder working roughly six focused
hours per weekday, with prompt review, tests, and documentation included. They
are calendar estimates, not commitments. Community feedback and security review
are inherently variable.

The sequence is deliberately vertical: prove one commit-aware path before
building the full catalog.

## Milestone 0 — Planning bootstrap

**Duration:** 1–2 days
**Dependencies:** none
**Status:** this document set, not yet accepted

**Deliverables**

- coherent product, architecture, scenario, threat, demo, release, and task
  plans;
- clean-room agent rules;
- current adjacent-work scan;
- selected stack and permanent safety boundary.

**Acceptance gate**

- all required documents exist;
- internal links and repository tree validate;
- no runtime or test claims are present;
- no unrelated repository is inspected or imported;
- working tree contains planning files only.

**Stop condition**

Stop if the clean-room repository is not the expected Git root or contains
unattributed prior implementation.

## Milestone 1 — Contracts and kernel

**Duration:** 3 focused days
**Dependencies:** Milestone 0 accepted

**Deliverables**

- `pyproject.toml`, locked dependencies, package skeleton, and CLI shell;
- strict scenario, protocol, event, claim, oracle, and artifact models;
- canonical JSON/digest helpers;
- logical clock;
- operation ledger and normative transition guards;
- unit and Hypothesis state-machine tests.

**Acceptance gate**

- invalid transitions, stale-absence retry, changed identity, expired authority,
  and completion without verification are mechanically rejected;
- property tests cover every allowed transition and representative illegal
  transitions;
- the same normalized fixture hashes identically under at least two Python hash
  seeds;
- no service or scenario implementation is needed to pass the kernel tests.

**Hold point**

Do not add dummy service breadth while the normative state machine can be
bypassed.

## Milestone 2 — First vertical slice

**Duration:** 4 focused days
**Dependencies:** Milestone 1

**Deliverables**

- event ledger persistence;
- deterministic fault scheduler;
- authority engine and gateway;
- minimal `dummy_github`;
- SEL-001 `Vanished Receipt`;
- in-process `retry-blindly` and `reconcile-first` reference subjects;
- JSON artifact, audit replay, simulation replay;
- `sel run` for one scenario and a narrow demo.

**Acceptance gate**

All must pass:

1. service truth proves the issue committed before the response was dropped;
2. `retry-blindly` fails specifically for redispatch-before-reconciliation or
   duplicate effect;
3. `reconcile-first` passes with one verified issue;
4. a required fault that is disabled produces `INVALID`, not `PASS`;
5. replay under two temporary roots reproduces observation sequence, event
   digest, state digest, and verdict;
6. a containment test proves the slice uses no sockets, ambient credentials, or
   non-temporary writes.

## Hold 1 — Novelty and usefulness

**Duration:** 0.5–1 day
**Owner:** Work (human decision), with Codex evidence
**Required before:** Milestone 3

Compare the working slice against current
[AgentCheck](https://arxiv.org/abs/2607.11098),
[agent-chaos](https://github.com/deepankarm/agent-chaos),
[ReliabilityBench](https://arxiv.org/abs/2601.06112), and
[faultkit](https://github.com/faultkit/faultkit) capabilities.

**Proceed only if a five-minute demonstration clearly shows all of:**

- hidden commit before response loss;
- exact authoritative effect cardinality;
- reconciliation freshness;
- unsafe retry detection;
- a useful mechanical artifact that the adjacent tool would not already emit
  with equivalent effort.

**HOLD — do not proceed** if the distinction depends only on naming, UI, or a
new scenario list. Consider contributing a commit-aware scenario/oracle pack to
an existing project instead.

## Milestone 3 — Core fault matrix

**Duration:** 6–7 focused days
**Dependencies:** Hold 1 passed

**Deliverables**

- `dummy_email`, `dummy_ticketing`, and `dummy_payments`;
- SEL-002, SEL-003, SEL-004, SEL-006, and SEL-007;
- conclusive-absence and schema-refresh paths;
- shared oracles for identity, authority, retries, claims, and effect count;
- curated unsafe trace mutations.

**Acceptance gate**

- SEL-001 through SEL-007, excluding not-yet-built SEL-005, meet the complete
  catalog validation gate;
- before-commit and after-commit timeouts produce different safe paths;
- duplicate delivery, expired auth, and schema drift each fail for their
  intended distinct invariant;
- all curated unsafe mutants are killed;
- no scenario needs network access or wall-clock sleeps.

## Hold 2 — Catalog quality

**Duration:** 0.5 day
**Required before:** Milestone 4

Review the six validated scenarios for redundant invariants.

**Proceed** if each remaining planned scenario adds stale-observation,
concurrency, async, identity, or workflow-partial coverage.

**HOLD — do not proceed** with a scenario whose only difference is changing a
dummy service name. Keep the MVP below 12 if validation quality would decline.

## Milestone 4 — Complete the 12-scenario MVP

**Duration:** 8 focused days
**Dependencies:** Hold 2 passed

**Deliverables**

- `dummy_deploy`;
- SEL-005 and SEL-008 through SEL-012;
- workflow/group state;
- exact-versus-approximate reconciliation;
- concurrent revision conflict;
- delayed async job;
- partial multi-service and approval-scope oracles;
- full artifact validators and replay coverage.

**Acceptance gate**

- all 12 scenarios meet the catalog validation gate;
- shared invariants pass the complete reference subject suite;
- every scenario has at least one named unsafe mutant that fails for the
  intended reason;
- valid suite runtime is under two minutes on the builder's recorded machine;
- no required fault miss is hidden in an aggregate pass.

## Hold 3 — External subject adapter

**Duration:** 1 day review
**Owner:** Work (human decision), with Codex threat-model evidence
**Required before:** Milestone 5

The subprocess protocol may execute trusted local subject code, but it cannot
secure the host from malicious code.

**Proceed** only with explicit `--allow-external-subject`, environment
scrubbing, resource budgets, containment documentation, and invalid-run
semantics.

**HOLD — do not proceed** if the feature is marketed as a sandbox or if the
default demo needs an external process.

## Milestone 5 — Portfolio-ready demonstration

**Duration:** 5 focused days
**Dependencies:** Milestone 4 and Hold 3 passed

**Deliverables**

- opt-in trusted local subprocess adapter and protocol-conformance fixture;
- `uv run --locked sel demo`;
- concise terminal timeline for SEL-001 and SEL-009;
- `--json` and `--verify` modes;
- Linux CI and a macOS local verification path;
- clean-clone setup instructions and architecture diagram;
- claim audit against
  [DEMO_AND_RELEASE.md](DEMO_AND_RELEASE.md).

**Acceptance gate**

- adapter rejects malformed protocol, stdout noise, budget overruns, and ambient
  credential inheritance; documentation explicitly says it is not a sandbox;
- demo completes in under 30 seconds after environment setup and tells the story
  in five minutes;
- full CI gate runs lint, types, unit/property/integration/containment/replay
  tests, adapter conformance, and demo verification;
- default demo uses only bundled deterministic subjects and local fixtures;
- README says exactly what is and is not implemented;
- a fresh local clone reproduces the demo from the lockfile.

**Portfolio-ready estimate:** 26–29 focused workdays from accepted planning,
roughly 5–6 calendar weeks.

## Milestone 6 — Community hardening

**Duration:** 8–12 focused days plus reviewer availability
**Dependencies:** portfolio-ready gate

**Deliverables**

- Linux and macOS CI on Python 3.12/3.13;
- schema compatibility policy and contributor scenario template;
- security, contributing, and code-of-conduct documents;
- owner-approved Apache-2.0 license;
- two external clean-clone reproductions;
- refreshed adjacent-work scan;
- release-candidate checklist and signed artifact hashes.

**Acceptance gate**

- all community-ready criteria in
  [PRODUCT_PLAN.md](PRODUCT_PLAN.md#community-ready) are evidenced;
- no unresolved high-severity containment issue;
- external reproduction notes are included;
- release claims are tied to a tag candidate and exact CI run;
- owner explicitly approves publication.

**Community-ready estimate:** 7–9 calendar weeks total from accepted planning,
assuming reviewers respond within one week.

## Hold 4 — Publication

**Owner:** Work only

Before any remote creation, push, package publication, tag, release, public
post, or result announcement:

1. refresh links and adjacent-work claims;
2. inspect Git history for secrets and unrelated content;
3. confirm license and third-party notices;
4. verify CI from the exact release candidate;
5. approve the wording in the release claim table;
6. receive explicit owner authorization.

Without all six: **HOLD — do not publish**.

## Post-MVP options, not commitments

Consider one at a time only after community readiness:

- local fake MCP adapter;
- Inspect task adapter;
- contributor-authored scenario packs under the same strict schema;
- opt-in model evaluation using a user-supplied key and separate containment
  profile;
- randomized exploratory fault sequences.

Do not add a dashboard or leaderboard unless real users show that JSON and
terminal artifacts are insufficient. Do not add real side-effect services.
