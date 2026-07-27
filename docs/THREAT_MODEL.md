# Threat Model

## Purpose

Side Effects Lab deliberately exercises unsafe-looking actions. The highest
priority is ensuring those actions remain fixtures inside an isolated logical
world.

This threat model covers the planned MVP runtime, its scenarios, artifacts, and
trusted local subject adapter. It does not claim to sandbox malicious native
code or secure a real external service.

## Security objectives

1. A lab run cannot contact or mutate a real account, recipient, deployment,
   ticket, repository, payment system, or third party.
2. Ambient host credentials and data do not enter a run or artifact.
3. A malformed scenario or subject message fails closed.
4. A required fault that did not execute cannot produce a green result.
5. Artifacts provide enough integrity evidence to detect accidental mutation.
6. Resource exhaustion is bounded.
7. Safety-policy violations remain failures even when the gateway blocks the
   underlying effect.

## Assets

- host credentials, tokens, cookies, keychain entries, SSH configuration,
  browser sessions, and cloud metadata;
- unrelated host files and repositories;
- network identity and third-party systems;
- integrity of scenario fixtures, event traces, oracle verdicts, and replay
  digests;
- contributor trust in public claims;
- developer time and machine resources.

## Trust boundaries

### Trusted

- reviewed Side Effects Lab core code;
- checked-in, schema-valid built-in scenarios;
- bundled deterministic reference subjects;
- Python standard library and pinned dependencies, subject to supply-chain
  review.

### Partially trusted

- contributor-authored scenario files;
- local subprocess subjects explicitly selected by the user;
- artifact files loaded for replay;
- CI environment.

### Untrusted

- arbitrary text returned by a subject;
- unknown fields or paths in scenario/artifact input;
- inherited process environment;
- URLs, socket addresses, and credential-shaped values;
- artifacts from unknown sources.

## Permanent containment boundary

- Dummy services are in-process state machines, not HTTP mocks for real APIs.
- Runtime code does not resolve DNS, open outbound sockets, bind public
  interfaces, or forward unmatched calls.
- Fixtures use `example.invalid`, deterministic dummy IDs, and integer
  `credits`.
- There is no code path for real service base URLs or bearer credentials.
- MCP support, if ever added, is restricted to a bundled local fake server and
  explicit loopback transport.
- Model APIs and paid services are absent from MVP and CI.

The project is not "safe because the credentials happen to be missing." It must
reject the capability itself.

## Threats and controls

### T1 — Accidental real destination

**Abuse case:** A contributor enters a real-looking email address, repository,
webhook, or URL in a fixture. Later code accidentally treats it as routable.

**Controls**

- strict destination types, not arbitrary strings;
- email domains must end in `example.invalid`;
- repository and deployment names are local logical identifiers;
- URL schemes are forbidden in MVP scenario data;
- dummy payment values use integer credits and nonfinancial wallet IDs;
- fixture validation runs in CI;
- containment tests enumerate rejected real-looking values.

**Fail-closed result:** scenario validation error before subject execution.

### T2 — Ambient credential capture

**Abuse case:** A subprocess inherits `GITHUB_TOKEN`, cloud keys, proxy
credentials, or a model API key. A debug artifact records it.

**Controls**

- construct a new environment from a small allowlist such as locale and an
  explicit Python path;
- reject known credential/proxy/cloud variable names;
- never call dotenv loaders or read the keychain;
- strip environment, cwd, and host path values from artifacts;
- scan test artifacts for credential-shaped keys and high-entropy values.

**Fail-closed result:** containment preflight makes the run `INVALID`.

### T3 — Network escape

**Abuse case:** Runtime code falls through to a real endpoint, a local server
binds `0.0.0.0`, or a future adapter forwards an unknown tool.

**Controls**

- no network client dependency in the runtime;
- no socket-based service transport in MVP;
- gateway allowlists service and operation enums;
- unmatched tools are rejected;
- tests patch/guard socket construction and fail on any call;
- future loopback-only transport must resolve and validate the final address
  before connecting.

**Fail-closed result:** blocked call plus `INVALID` containment verdict.

### T4 — Path traversal or symlink escape

**Abuse case:** Scenario IDs, artifact paths, or subject output names escape the
run root and overwrite unrelated files.

**Controls**

- generate run directories internally;
- scenario IDs are constrained tokens, not paths;
- resolve every output path and require it to remain under the resolved run
  root;
- reject symlinked artifact destinations and archive members;
- use exclusive creation for new artifacts;
- never follow subject-provided absolute paths.

**Fail-closed result:** no write; run `INVALID`.

### T5 — Shell or command injection

**Abuse case:** A subject command or scenario string is interpolated into a
shell.

**Controls**

- subprocess command is an explicit argv array;
- `shell=True` is forbidden and mechanically linted/tested;
- built-in demo uses in-process subjects;
- scenario text is data only and never executed.

**Fail-closed result:** adapter validation error.

### T6 — Malicious or runaway subject

**Abuse case:** A subject loops, floods output, forks processes, reads host
files, or independently uses the network.

**Controls**

- default demo uses reviewed in-process subjects;
- external subprocess subjects require explicit opt-in;
- per-run step, byte, logical-time, artifact-size, and wall-time watchdog
  budgets;
- temporary cwd and scrubbed environment;
- stderr/stdout caps and strict protocol parsing;
- documentation states that local subprocess execution is not a sandbox.

**Residual risk**

A native process launched under the user's account can still access capabilities
available to that account, including files and network, despite environment and
cwd controls. Portable strong sandboxing is not an MVP claim.

**Fail-closed result:** budget or protocol violation makes the run `INVALID`, but
cannot guarantee host containment against malicious code.

## Untrusted subject processes

The safe operational rule is:

> Run only subject code you would otherwise be willing to execute directly on
> the host.

The lab can constrain its own gateway. It cannot prevent a malicious subject
from opening an independent socket or reading a host file. Users evaluating
untrusted code must supply an external OS/container/VM sandbox and keep Side
Effects Lab inside it. The project will not advertise the subprocess adapter as
a security boundary.

### T7 — Oracle bypass or false green

**Abuse case:** The required fault misses its target, an exception is swallowed,
or a blocked unsafe call is mistaken for safe agent behavior.

**Controls**

- required injection plan and fired evidence are separate artifact records;
- required fault miss has verdict precedence `INVALID`;
- attempted unauthorized writes are trace violations even when blocked;
- shared oracles run before scenario-specific success checks;
- curated unsafe subjects/mutations must fail for named reasons;
- verdict recomputation is part of replay.

**Fail-closed result:** `INVALID` or `FAIL`, never `PASS`.

### T8 — Artifact tampering or stale evidence

**Abuse case:** An artifact is edited after a run, mixed with a different
scenario, or replayed against changed semantics.

**Controls**

- schema, scenario, subject, and protocol versions are required;
- canonical input, event, and state digests;
- contiguous append-only event sequence;
- replay recomputes verdict and digests;
- release artifacts publish checksums only after human approval.

**Residual risk**

SHA-256 detects accidental or untrusted-file modification when the expected
digest is known; it is not an authenticity signature by itself.

### T9 — Sensitive data in artifacts

**Abuse case:** A future subject includes secrets, personal data, or hidden
reasoning in tool arguments or text.

**Controls**

- fixtures are dummy and schema-bounded;
- artifacts prefer semantic digests and enum/count evidence over raw bodies;
- final summary text is optional, size-limited, and excluded from oracle logic;
- known secret fields are rejected rather than merely redacted;
- no chain-of-thought or hidden reasoning is requested or stored.

**Fail-closed result:** rejected message or sanitized diagnostic; `INVALID` if
required evidence cannot be retained safely.

### T10 — Resource exhaustion

**Abuse case:** Infinite retries, huge messages, artifact growth, deep JSON, or
pathological property tests exhaust the machine or CI.

**Controls**

- max steps, attempts, message bytes, nesting depth, artifact bytes, logical
  ticks, and subprocess duration;
- SQLite row and query limits appropriate to tiny fixtures;
- no unbounded recursion;
- property-test profiles with explicit example and step limits;
- budgets recorded in artifacts.

**Fail-closed result:** terminate the run and mark `INVALID`.

### T11 — Scenario supply-chain abuse

**Abuse case:** A contributed scenario embeds executable hooks, dependencies, or
arbitrary Python and runs during discovery.

**Controls**

- declarative strict data only;
- no dynamic imports, callbacks, templates, or install steps from scenarios;
- service/fault/oracle names come from built-in registries;
- scenario pack support is post-MVP and must use the same schema.

**Fail-closed result:** unsupported declaration rejected.

### T12 — Misleading publication

**Abuse case:** Authored scenarios are described as validated, reference agents
are presented as model evaluations, or a portfolio demo is called a benchmark.

**Controls**

- explicit vocabulary in the product plan;
- release-stage claim table;
- README status audit in CI/release checklist;
- human-only publication gate;
- results tied to exact subject, scenario versions, seed, and commit.

**Fail-closed result:** hold release until wording and evidence agree.

## Abuse cases intentionally out of scope

- attacking or fuzzing third-party endpoints;
- validating real payment, email, deployment, or repository credentials;
- offensive prompt injection or data exfiltration research;
- malware analysis;
- secure multi-tenant execution;
- cryptographic attestation of model or agent identity;
- production authorization or compensation orchestration.

## Security test matrix

| Boundary | Required test |
| --- | --- |
| Destinations | reject real domains, URLs, IPs, and realistic payment identifiers |
| Environment | known secret and proxy variables absent from subject and artifact |
| Network | any socket construction during built-in run fails the test |
| Filesystem | traversal, absolute path, symlink escape, and overwrite attempts fail |
| Protocol | unknown fields, duplicate IDs, oversized/deep JSON, and stdout noise invalidate |
| Budgets | runaway steps, attempts, bytes, and time terminate predictably |
| Fault evidence | disabled/missed required injection is `INVALID` |
| Oracle | every curated unsafe mutant is `FAIL` |
| Replay | tampered event, state, scenario version, or digest is rejected |

## Incident response for development

If a test or run appears to touch a real resource:

1. stop the process;
2. do not rerun to "confirm";
3. preserve only the minimum local logs needed to identify the path, without
   exposing secrets;
4. inspect for actual external effects using a human-approved method;
5. rotate any possibly exposed credential;
6. add a regression test and update this threat model;
7. hold all publication until the owner reviews the incident.

## Security acceptance boundary

The MVP may claim:

> Built-in scenarios and reference subjects run against in-process dummy
> services with no intended network or ambient-credential dependency, verified
> by the documented containment tests.

It may not claim:

> Side Effects Lab safely sandboxes arbitrary agents or guarantees that external
> subject code cannot access the host or network.
