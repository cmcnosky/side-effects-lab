# Product Plan

## Decision summary

Side Effects Lab will be a local, deterministic test lab for one failure domain:
an agent has requested a state-changing tool action, but cannot safely infer
whether the external effect happened.

The MVP will contain 12 curated scenarios, five in-process dummy service
facades, a strict subprocess/in-process subject protocol, mechanical state and
trace oracles, JSON evidence artifacts, and two deterministic reference
subjects. It will not contain a web interface, hosted service, leaderboard,
real integration, paid model call, or benchmark claim.

The adjacent landscape is crowded. The project's defensible value is not
"fault injection for agents" in general. It is the narrower combination of:

1. faults placed deliberately before or after an authoritative commit;
2. effect cardinality checked from the service's hidden ground truth;
3. recovery constrained by stable identity, freshness, and unchanged authority;
4. partial multi-service state and false completion claims scored mechanically;
5. a runtime that is local-only and cannot fall through to real services.

If the first vertical slice does not make that distinction obvious, the project
stops rather than expanding its scenario count.

## Users

### Primary

- Agent and framework maintainers who need a small regression suite for retry,
  reconciliation, and completion-claim logic.
- Reliability and platform engineers reviewing whether a tool-using agent is
  safe to place in front of state-changing APIs.
- Open-source contributors who want reproducible examples of ambiguous commit
  outcomes without provisioning accounts.

### Secondary

- Evaluators teaching or studying trace-based agent safety.
- Hiring teams or collaborators reviewing a compact reliability-engineering
  portfolio project.

The MVP is not designed for nontechnical business users or hosted production
monitoring teams.

## Problem

Ordinary tool tests often model a call as a simple function: it returns success
or raises an error. Real state-changing calls have a harder boundary. A service
can commit an effect and then lose the response. A read used for reconciliation
can be stale. A retry can be delivered twice. Authorization or schema can
change between attempts. A workflow can commit to one service and fail at the
next.

An agent that treats every timeout as a non-event can duplicate issues, mail,
jobs, tickets, or charges. An agent that treats every accepted request as
completed can falsely claim success. A generic "retry on exception" test cannot
distinguish a timeout before commit from the same timeout after commit.

## Value proposition

Side Effects Lab makes the hidden commit point visible to the evaluator while
keeping it hidden or ambiguous to the subject. A developer gets:

- a concise unsafe trace and the violated invariant;
- the authoritative final dummy-service state;
- a replayable event artifact;
- a passing reconciliation-first comparison;
- a CI exit status that distinguishes subject failure from invalid harness
  execution.

This is more actionable than a prose critique and narrower than adopting a
general evaluation platform.

## Product principles

1. **Safety before realism.** A fake in-process service with an explicit commit
   point is better than a realistic connector that could contact a third party.
2. **Ground truth before judgment.** State and structured claims decide verdicts;
   no LLM judge is required.
3. **Ambiguity is first-class.** "Unknown" is a state, not an exception to map to
   "failed."
4. **A safe stop can pass.** The agent may be unable to finish and still recover
   safely.
5. **One invariant per scenario.** Catalog growth must add fault or policy
   coverage, not cosmetic domain variants.
6. **Evidence before claims.** Authored, validated, evaluated, and benchmarked
   are different states.

## Non-goals

- ranking models, agents, or vendors;
- a general agent evaluation framework;
- prompt-injection, jailbreak, secret-exfiltration, or spec-gaming coverage;
- production chaos engineering or network-level fidelity;
- guaranteeing exactly-once delivery;
- automatically repairing agent code;
- executing untrusted agent binaries as a secure sandbox;
- real GitHub, email, deployment, ticketing, payment, or MCP integrations;
- a dashboard, trace explorer, hosted API, SaaS control plane, or leaderboard;
- randomized fuzzing in the MVP acceptance suite;
- human-behavior simulation or subjective quality scoring.

## Adjacent work and differentiation

This was a targeted primary-source scan on 2026-07-27, not an exhaustive market
or literature review. It must be refreshed before public release.

| Project | What its primary source says it covers | Relationship to Side Effects Lab |
| --- | --- | --- |
| [ToolSandbox](https://github.com/apple/ToolSandbox) | Stateful tool-use evaluation with roles, world-state snapshots, and milestone-based evaluation | Strong precedent for a simulated world and state-based scoring. Side Effects Lab narrows to commit ambiguity, exact effect cardinality, freshness, and recovery invariants. |
| [tau3-bench](https://github.com/sierra-research/tau2-bench) | User-agent-tool simulations with policies and domain tools | Strong precedent for policy-constrained stateful interactions. Side Effects Lab has no user simulator or model leaderboard and focuses on tool outcome ambiguity. |
| [Inspect](https://inspect.aisi.org.uk/) | A broad open-source evaluation framework with tools, scorers, agents, bridges, and sandboxes | Potential future integration surface, not a dependency. Rebuilding Inspect would be scope failure. |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | Dynamic evaluation of prompt-injection attacks and defenses for tool-using agents | Neighboring safety problem, deliberately out of scope. Side Effects Lab does not claim prompt-injection coverage. |
| [agent-chaos](https://github.com/deepankarm/agent-chaos) | LLM/tool timeouts, errors, mutations, fuzzing, and assertion integrations | Direct overlap at generic faults. Side Effects Lab must differentiate through modeled commits, operation identity, authority, and authoritative effect oracles—not through another list of error injectors. |
| [AgentCheck](https://arxiv.org/abs/2607.11098) | MCP response intervention, controlled replay, 12 fault types, 120 scenarios, deterministic checks plus diagnostic judge labels | The closest current overlap. AgentCheck perturbs tool responses and can use real tools; Side Effects Lab will own the local service state and commit point, forbid real endpoints, score duplicate effects and multi-service partial commits, and avoid judge-dependent verdicts. |
| [ReliabilityBench](https://arxiv.org/abs/2601.06112) | Repeated-run consistency, task perturbations, tool/API faults, end-state relations, and model evaluation | Direct overlap in timeouts, partial responses, schema drift, and end-state scoring. Side Effects Lab is a small lab rather than a benchmark and concentrates on write-side recovery semantics. |
| [faultkit](https://github.com/faultkit/faultkit) | Process-wrapped HTTP, LLM, subprocess, and syscall fault injection, including traffic forwarded to real upstreams | Better for transport and SDK failure fidelity. Side Effects Lab must never proxy or forward to real upstreams and instead models semantic service commits. |
| [Toxiproxy](https://github.com/Shopify/toxiproxy) | Deterministic and randomized network-condition simulation for tests and CI | Useful lower-layer precedent, but it cannot by itself say whether a business effect committed or whether an agent's retry was authorized. |

### Positioning sentence

> Side Effects Lab is a local crash-test course for the moment after an agent
> presses "send" but before it knows what happened.

It should not be presented as the first agent fault injector, a comprehensive
reliability solution, or a replacement for any project above.

The portfolio-level boundary supplied by the owner is also explicit: Stinger is
positioned around integrity and specification-gaming; Side Effects Lab is
positioned around stateful tool reliability and recovery. That distinction is
descriptive only. No Stinger implementation, data, artifact, assumption, or
result is an input to this clean-room project.

### Why build rather than contribute upstream?

The vertical slice must answer this empirically. A separate project is justified
only if the commit-aware state machine and evidence artifact remain small,
coherent, and useful without modifying a general framework. If the slice becomes
mostly glue around an existing project, the correct outcome is to stop and
consider an upstream scenario pack instead.

## MVP scope

### Included

- Five local service facades:
  - `dummy_github`
  - `dummy_email`
  - `dummy_deploy`
  - `dummy_ticketing`
  - `dummy_payments`
- The 12 scenarios in
  [SCENARIO_CATALOG.md](SCENARIO_CATALOG.md).
- One canonical operation state machine and one workflow/group state model.
- Exact-identity reconciliation and visibility-fence semantics.
- A deterministic fault scheduler with explicit commit-relative injection.
- An in-process subject interface and an opt-in local subprocess NDJSON adapter.
- A deliberately unsafe `retry-blindly` reference subject.
- A deterministic `reconcile-first` reference subject.
- Strict JSON artifacts, mechanical oracles, replay, and CI exit codes.
- A Typer CLI with `demo`, `run`, `replay`, `validate-scenario`, and
  `validate-artifact` commands.

### Excluded from MVP

- MCP, Inspect, LangChain, or provider-specific adapters;
- LLM calls of any kind;
- external subprocess subjects in the default demo;
- HTTP servers or sockets;
- free-form scenario plugins;
- visual trace UI;
- aggregate model scores;
- randomized chaos runs;
- Docker as a requirement.

## Scenario, validation, evaluation, and benchmark language

These terms are not interchangeable:

- **Catalogued scenario:** a reviewed specification in Markdown. Current count:
  12. This is the only count supportable during planning.
- **Implemented scenario:** executable fixture, service behavior, fault schedule,
  and oracle exist.
- **Validated scenario:** the required fault fires at the declared commit
  position; the curated unsafe behavior fails for the intended reason; the
  reconciliation-first behavior passes; and replay reproduces the verdict and
  digests.
- **Evaluation:** a named, versioned subject is run against a stated set of
  validated scenarios under a recorded configuration. Results apply only to
  that subject and configuration.
- **Benchmark:** a stable measurement protocol with a frozen versioned corpus,
  validated adapters, documented sampling and aggregation, comparability
  controls, and independent reproduction. This is outside the MVP.

Invalid runs are excluded from an evaluation denominator and reported
separately. They never become passes.

## Success criteria

### Portfolio-ready

All of the following must be verified:

- all 12 scenarios meet the complete
  [catalog validation gate](SCENARIO_CATALOG.md#catalog-validation-gate);
- each scenario adds a distinct invariant or fault interaction;
- the full local suite completes in under two minutes on a typical developer
  laptop, while the two-scenario demo completes in under 30 seconds after the
  locked environment is installed;
- the required fault fires in every scenario;
- every curated unsafe mutant is killed and the reconciliation-first reference
  subject passes;
- replay reproduces verdict, event digest, and final-state digest across two
  temporary directories;
- containment tests prove the lab does not load ambient credentials or request
  non-loopback network access;
- a new contributor can run the demo from a clean clone using the documented
  commands;
- README and demo language make no benchmark or real-world reliability claim.

### Community-ready

In addition to portfolio readiness:

- Linux and macOS CI pass on Python 3.12 and 3.13;
- schema compatibility and deprecation policy are documented;
- the owner has approved and added Apache-2.0 licensing;
- contribution, security-reporting, and code-of-conduct documents exist;
- at least two people genuinely external to both regular project builders
  reproduce the demo from a clean clone and report setup friction;
- the primary-source adjacency scan is refreshed;
- a release candidate receives an explicit owner publication approval.

### Negative success criterion

Stopping after a good vertical slice is a success if the evidence shows the
project duplicates an existing tool or cannot contain external subjects safely.

## Major product choices and rejected alternatives

| Decision | Selected | Rejected alternative and reason |
| --- | --- | --- |
| Product shape | Small local lab | General evaluation framework: duplicates mature adjacent tools and expands integration burden. |
| Verdict basis | Mechanical trace and state invariants | LLM-as-judge: nondeterministic, paid, and unnecessary for effect cardinality and authority. |
| Scenario count | 12 curated MVP scenarios | Large corpus: expensive to validate and invites benchmark language before measurement rigor exists. |
| Interaction surface | Structured tool calls and structured final status | Free-form conversational grading: introduces subjective parsing and simulator variance. |
| Presentation | Terminal demo plus JSON artifact | Dashboard/leaderboard: high effort with little proof of core value. |
| Runtime safety | In-process fake services, no network | Proxying real tools: conflicts with the permanent safety boundary. |
| License intent | Apache-2.0, owner approval required | MIT lacks an explicit patent grant; copyleft would add adoption friction for a test harness. |

## Boundaries and approvals

- **Paid services:** none are required or allowed in MVP or CI. Any later model
  evaluation is opt-in, bring-your-own-key, outside the default suite, and needs
  explicit owner approval.
- **Public publication:** only the owner may create a remote, push, publish a
  package, make a release, or announce results.
- **Real integrations:** prohibited. Local fake service adapters are the product,
  not a stepping stone to production credentials.
- **Human approval:** license activation, public release, paid services, and any
  change to the permanent side-effect boundary are human-only.
