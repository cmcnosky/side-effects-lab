# Demo and Release Plan

## Demo objective

In five minutes, a reviewer should understand one idea:

> A timeout does not tell an agent whether a side effect happened.

The demo must show a hidden commit, an unsafe blind retry, a safe
reconciliation, and a mechanical verdict. It should not require a model key,
Docker, an account, a browser, or network access.

## Target one-command experience

After implementation:

```console
uv run --locked sel demo
```

Expected behavior:

1. preflight prints `local fixtures`, `network disabled`, and the locked project
   version;
2. SEL-001 runs with `retry-blindly`;
3. the trace shows issue commit, dropped receipt, immediate redispatch, and a
   failed duplicate/reconciliation invariant;
4. SEL-001 reruns with `reconcile-first`;
5. the trace shows the same commit fault, exact lookup, one issue, and pass;
6. SEL-009 briefly shows why a partially completed two-service workflow must not
   be restarted;
7. the command writes JSON artifacts under a fresh local run directory and
   verifies their digests;
8. exit code is zero only if the expected fail/pass comparison and artifact
   verification occur.

This is a planned interface, not a current command.

## Terminal story

Keep the default output under roughly 60 lines:

```text
Side Effects Lab — local deterministic demo
Safety: in-process fixtures | network disabled | no credentials

SEL-001 Vanished Receipt
  tick 2  COMMIT      dummy_github issue-1
  tick 2  FAULT       success response dropped
  unsafe  RETRY       before reconciliation
  oracle  FAIL        duplicate-risk / missing reconciliation

  tick 2  COMMIT      dummy_github issue-1
  tick 2  FAULT       success response dropped
  safe    LOOKUP      op-sel001-release-checklist
  safe    VERIFY      one matching issue at fresh revision
  oracle  PASS

SEL-009 Half a Handoff
  ticket committed | email proved absent | workflow reported partial
  oracle  PASS

Artifacts verified: 3
```

Color may enhance output when supported, but text and exit codes must remain
complete without color. `--json` emits machine-readable output.

## Five-minute presentation

### 0:00–0:40 — Frame the failure

Explain that generic retry logic cannot distinguish timeout-before-commit from
timeout-after-commit.

### 0:40–2:15 — Run the command

Point to the commit line appearing before response loss, then the unsafe
redispatch failure and the safe exact lookup.

### 2:15–3:10 — Show the oracle evidence

Open the small artifact section containing:

- fault fired at `after_commit_before_response`;
- true effect count;
- lookup watermark;
- failed or passed invariant;
- structured final claim.

Do not show raw hidden reasoning or verbose logs.

### 3:10–4:10 — Show partial workflow behavior

Use SEL-009 to demonstrate that "retry the entire task" duplicates the first
service, while per-action reconciliation can safely complete or report partial.

### 4:10–5:00 — State boundaries

Say:

- 12 curated local scenarios after validation;
- no real services or credentials;
- not a benchmark or model ranking;
- arbitrary external subject code is not sandboxed;
- mechanical effect and authority checks, not an LLM judge.

## Demo modes

Planned commands:

```console
uv run --locked sel demo
uv run --locked sel demo --json
uv run --locked sel demo --verify
uv run --locked sel run SEL-001 --subject reconcile-first --seed 17
uv run --locked sel replay .side-effects-lab/runs/<run>/artifact.json
uv run --locked sel validate-scenario scenarios/sel-001.yaml
uv run --locked sel validate-artifact artifact.json
```

`demo --verify` checks that the unsafe reference fails for the named reason,
the safe reference passes, required faults fire, and artifacts replay. It is the
CI demonstration command.

## Repository presentation

The eventual public repository landing page should lead in this order:

1. one-sentence pitch;
2. 15–25 second terminal recording or static screenshot;
3. concrete Vanished Receipt explanation;
4. copyable local demo command;
5. scenario coverage table;
6. safety/non-claims;
7. architecture and contribution links.

Avoid badges and screenshots until they reflect a real verified build. Avoid a
leaderboard, marketing counters, broad "production ready" language, or model
logos.

The portfolio should emphasize the engineering:

- commit-relative fault placement;
- stable identity and reconciliation freshness;
- mechanical trace/state oracles;
- deterministic replay;
- fail-closed containment.

## CI strategy

### Pull-request gate

Once implemented:

```console
uv lock --check
uv run --locked ruff check .
uv run --locked mypy src
uv run --locked pytest
uv run --locked sel demo --verify
```

Jobs:

- Python 3.12 on Linux: full gate;
- Python 3.13 on Linux: full gate;
- Python 3.12 and 3.13 on macOS: full gate before community-ready status;
- dependency and artifact schema checks;
- Markdown internal-link check and public-link check with a documented retry
  policy;
- secret scanning and package vulnerability review before release.

Runtime tests execute offline. Dependency installation in CI may access the
package registry using the checked-in lockfile; this is build infrastructure,
not scenario behavior.

### CI evidence

Upload on failure:

- sanitized failing artifact;
- normalized event log;
- replay diagnostics;
- test report.

Do not upload environment dumps, subject stderr containing unknown data, or
ambient host paths.

### Flake policy

- no automatic retry of scenario/test failures;
- retry only external setup such as package download or public-link checks;
- a nondeterministic replay result blocks merge;
- a required fault miss is invalid, not flaky success.

## Release strategy

### Versioning

- Package and artifact schema use semantic versions independently.
- Scenarios have stable IDs and their own semantic versions.
- Any change to initial state, fault timing, authority, oracle, or allowed
  terminal status bumps the scenario version.
- Breaking artifact changes bump its major schema version.
- Release notes list scenario additions, semantic changes, and fixed false
  positives/negatives.

### Stages

1. `0.1.0-dev`: local development only; no publication claim.
2. `0.1.0-rc1`: all portfolio/community gates pass; owner reviews.
3. `0.1.0`: first public source release after explicit approval.
4. Package-index publication: optional later decision; a GitHub source release
   is enough for the initial community handoff.

No remote, tag, release, package, or announcement is created by automation
without human authorization.

### Release artifacts

Planned:

- source archive;
- wheel and source distribution if package publication is approved;
- generated JSON Schemas;
- demo artifact bundle produced from the tag;
- SHA-256 checksums;
- release notes with exact claims and known limitations.

Do not ship model outputs as canonical evidence.

## Supportable claims by stage

| Stage | Supportable wording | Unsupported wording |
| --- | --- | --- |
| Planning (current) | "The repository contains a plan and a catalog of 12 proposed scenarios." | "The lab works," "12 tests pass," or "benchmark." |
| First slice | "One local commit-loss scenario is implemented and passes its documented validation gate." | "Agents are reliable" or "the architecture is proven." |
| Portfolio-ready | "Twelve local deterministic scenarios are validated against curated unsafe and reconciliation-first reference subjects." | "Twelve agents tested," "production ready," or model ranking. |
| Community-ready | "The tagged release meets documented cross-platform, replay, containment, and external-reproduction gates." | "Safe sandbox," "real integrations," or universal reliability. |
| Optional subject evaluation | "Subject X version Y produced P passes, F failures, and I invalid runs on scenario set Z under this configuration." | Generalizing to the model/vendor or comparing incompatible adapters. |
| Benchmark | No benchmark claim is planned for MVP. | Any leaderboard or state-of-the-art claim. |

## Community feedback path

Before public release:

- two invited reviewers run the clean-clone demo and submit a short structured
  friction report;
- one reliability reviewer checks the commit/retry state machine;
- one security-minded reviewer checks containment claims;
- overlap findings are compared again with adjacent primary sources.

After an approved public release:

- GitHub Discussions or a clearly labeled issue template collects scenario
  ideas;
- bug reports request scenario/version, seed, artifact digest, and sanitized
  replay output;
- proposed scenarios must identify the new invariant and why an existing
  scenario cannot cover it;
- security reports use a private channel defined in the future `SECURITY.md`;
- maintainers publish no aggregate model results without a separate measurement
  protocol.

No mailing list, analytics tracker, telemetry, hosted collector, or paid
community platform is needed.

## Paid services and real integrations

- The demo, tests, CI scenario execution, and release artifact generation use no
  paid service.
- An optional future model adapter requires a user-supplied key, explicit owner
  approval, a separate command flag, secret-safe artifact review, and cost
  limits. It remains outside the default quality gate.
- Real action services are permanently prohibited. The project tests their
  semantics using dummy state, not their live APIs.
- No model or service vendor may be presented as endorsing the project without
  written permission.

## Pre-release checklist

- [ ] Exact release commit is identified and clean.
- [ ] All validated-scenario evidence was generated from that commit.
- [ ] Full supported-platform CI passes without scenario retries.
- [ ] Demo and full suite meet runtime budgets.
- [ ] Required faults fired in every evidence artifact.
- [ ] Replay digests match.
- [ ] README status and non-claims match reality.
- [ ] External links and license notices are current.
- [ ] Secret/history scan passes.
- [ ] Two external clean-clone reproductions are recorded.
- [ ] Owner approved license, tag, release wording, and publication.

Unchecked human approval means **HOLD — do not publish**.
