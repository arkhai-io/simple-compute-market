## Context

The earlier capacity-harness merge was built against an intermediate product
shape. Its raw semantic envelope is useful evidence, but its private
repository literals, G2 fixtures, controller-owned purchase path, and legacy
job correlation are not current authority. This change starts from current
`dev` and reconstructs only the portable intent inside the existing
issue-discovery tool.

The public repository owns scenario meaning and sanitized results. A separate
private orchestration layer owns Codex processes, credentials, isolated role
workspaces, wallets, cloud and host authority, unredacted evidence, and any
future authenticated mutation. Public code must remain useful without knowing
where or how an agent is launched.

## Goals

- Preserve the original issue-discovery purpose while scaling buyer roles
  before seller roles.
- Make the exact future VM/G1 rows representable without executing them.
- Give substantive buyer and seller actors ownership of their documented
  quickstart actions while keeping controller responsibilities narrow.
- Consume current durable fulfillment and typed-scarcity contracts without a
  product compatibility shim.
- Make findings and fix candidates deterministic, sanitized, cleanup-gated,
  and entirely mockable.
- Keep the runner boundary portable enough to wrap in an on-demand cloud
  system later without building that system now.

## Decisions

### Reconstruct semantics on current `dev`

No historical branch is merged or cherry-picked. Every capacity addition is
implemented as current code under one narrow OpenSpec change. Existing
issue-discovery behavior remains the base, and no production or E2E path is an
eligible workaround if a harness assertion disagrees with current product
behavior.

### Use one finite VM/G1 scenario schema

One schema represents all rows rather than one runner design per stage. A
scenario contains:

- a stable stage identifier and description;
- `deal_type=vm`, `physical_gpu_count=1`, and whole-GPU assignment;
- explicit counts for orchestrators (`O`), buyers (`B`), sellers (`S`), hosts
  (`H`), listings (`L`), requests (`R`), and physical GPUs (`G`);
- current pinned buyer and seller quickstart paths;
- an action-ownership mode: host preflight, controller reference, or
  substantive agents;
- an arrival mode: none, common release barrier, or serialized reuse;
- expected success and exact typed-scarcity counts;
- retry prohibition and cleanup invariants; and
- current reservation, fulfillment, result, executor-correlation, and teardown
  receipt requirements.

The finite set is Q0, Reference B1, Q1, Q2, Q3, Q4, Q5, Q6, Q7, and optional
Q8. Q5 permits two sequential requests from one persistent buyer and requires
terminal teardown before the second release. Q2-Q4 and Q6-Q8 release frozen
buyer demands through one common barrier. A single global physical-GPU fence
applies across every seller view. G2 and non-VM inputs fail validation.

Canonical JSON serialization with sorted keys and compact separators defines
the scenario hash. File paths, timestamps, run identifiers, private metadata,
and presentation ordering do not alter a scenario's semantic hash unless they
are normative schema fields.

### Separate public intent from private execution

Public scenarios assign role identities, quickstart references, frozen demand
or listing hashes, and required action/result receipts. They do not launch
Codex or include account, wallet, SSH, cloud, provider, or host details.

For substantive rows, each seller reads the pinned seller quickstart, prepares
its isolated identity and service, publishes only its assigned listing, and
remains alive for the scenario. Each buyer reads the pinned buyer quickstart,
prepares its isolated identity and exact demand, waits at the controller's
release boundary, and invokes that demand itself. The host role owns the
future Ansible/KVM lifecycle. The controller owns only authority checks,
barriers, bounded observation, retry prohibition, cancellation, evidence, and
cleanup. Reference B1 is explicitly controller-driven and therefore is not
agent-capacity evidence.

### Evaluate the current durable lifecycle

A successful result correlates an opaque `capacity_reservation_id` with an
opaque `fulfillment_id`, observes fulfillment status and versioned result,
checks private executor reference/target correlation by sanitized assertion,
and records fulfillment-driven teardown to a terminal zero-residue state. Raw
executor values and result payload secrets never enter a public finding.

Expected scarcity is exactly an HTTP 409 response whose structured detail has
`error=offer_unfulfillable` and `reason=no_matching_inventory`, and only when
the scenario still expects scarcity at that ordinal. Any other 409 or failure
is classified rather than suppressed.

### Use one explicit outcome and cleanup model

Evaluation produces a machine-readable outcome in one of these semantic
classes: success, expected scarcity, harness defect, possible product defect,
environment/provider issue, or cleanup failure. Expected scarcity does not
produce a finding. Cleanup is attempted on every terminal path. A successful
market action with failed cleanup becomes a cleanup-failure finding and is not
publication-eligible until private policy resolves the residue.

Cancellation and cleanup receipts are first-class result fields, not log-text
inferences. Selecting a live market, wallet, cloud, host, provisioning, or
GitHub mutation adapter while in preparation mode fails before any subprocess
or network invocation.

### Derive stable findings only from sanitized defect identity

The finding fingerprint hashes canonical sanitized fields that identify the
defect: schema version, scenario hash, semantic classification, normalized
failure code/location, and stable evidence summary. It excludes occurrence
metadata such as timestamps, run IDs, temporary paths, private refs, account
or project data, credentials, and raw logs. Repeated occurrences therefore
map to one issue identity while retaining separate sanitized occurrence
records.

Public finding documents include only public repository/branch/SHA, scenario
hash, run metadata, correlation-presence assertions, cleanup state, and
redacted evidence. Negative tests scan fixtures, results, and rendered issue
bodies for private identifiers and credential shapes.

### Plan issue and guarded fix behavior without mutation

Issue planning uses stable markers to choose exactly one of create, no-op,
update, or reopen. Expected scarcity is suppressed before issue planning.
Cleanup eligibility gates publication planning, except that cleanup failure
itself remains a candidate finding.

A draft-fix proposal is allowed only for a change classified as owned by the
public harness and confined to an allowlisted harness path. Its proposed head
is exactly `fix/<finding-fingerprint>`, its base is the applicable public
replacement branch, and it is always draft/never auto-merge. When mutation
authority is absent, the result is a candidate packet containing the proposed
commands and metadata, not a branch or pull request. All preparation tests use
mock repositories or dry-run packets.

### Preserve a future on-demand runner seam

The public CLI accepts explicit public repository, branch, SHA, scenario,
run, timeout, and adapter inputs and emits stable JSON plus meaningful exit
codes. Cancellation and cleanup are idempotent typed operations. Credentials
and workspace roots are external inputs owned by the private runner. This is
enough for a later Tekton Task, GitHub Action, managed job, or VM wrapper; no
such wrapper belongs in this change.

## Alternatives Rejected

- **Merge the historical harness branch:** rejected because it would import
  obsolete product assumptions and unrelated expansion work.
- **Create a `capacity-testing` capability/platform:** rejected because the
  existing issue-discovery and test-compatibility boundaries are sufficient.
- **Keep controller-owned buyer actions:** rejected because it measures a
  controller driver, not the intended agent-driven load generator.
- **Generalize immediately to all deal types or GPUs:** rejected because the
  requested experiment is VM-only with one physical GPU.
- **Use a live smoke run to validate preparation:** rejected because schema,
  fake-process, and mocked contract tests prove the changed boundaries without
  external effects.
- **Add CI or Tekton now:** rejected because portable interfaces avoid a later
  rewrite without creating speculative runner infrastructure.

## Compatibility, Migration, and Rollback

Capacity fixtures are development contracts, not public service wire formats.
The migration is an atomic switch from absent/obsolete capacity fixtures to
the current schema. Existing ordinary issue-discovery phases remain valid.
Rollback removes only the new harness paths and documentation; no database,
service state, cloud resource, or remote issue/branch needs repair.

## Verification Strategy

1. Strict OpenSpec validation and source/path inspection.
2. Draft 2020-12 schema and exact finite-matrix fixture tests.
3. Pure canonical hash, lifecycle evaluation, scarcity, cleanup, and
   fingerprint tests.
4. CLI valid/invalid JSON, exit-code, cancellation, cleanup, and live-adapter
   rejection tests.
5. Mock issue create/update/reopen/suppress and fix-candidate fallback tests.
6. Cross-repository fake-process tests for substantive role ownership,
   barriers, session persistence, partial failure, cancellation, and cleanup.
7. The smallest hermetic real-Codex role rehearsal only if private changes to
   prompt interpretation, session persistence, or agent-owned actions remain
   unproved after the fake-process layer. It must use mock adapters and is not
   capacity evidence.

## Design Promotion Record

| Accepted decision | Permanent location |
| --- | --- |
| finite VM/G1 matrix, role ownership, current lifecycle, scarcity, cleanup, and finding behavior | `openspec/specs/test-compatibility/spec.md` |
| public/private boundary, evidence layering, stable identity, and future runner seam | `openspec/specs/test-compatibility/architecture.md` |
| operator commands, result claims, and no-live boundary | `docs/development/ISSUE_DISCOVERY.md` and `tools/issue-discovery/README.md` |

## Scope Freeze

The semantic scope above is implementation-ready and frozen. Task detail may
be refined only within it. New product behavior, path families, deal types,
GPU topology, publication machinery, runner infrastructure, or live
qualification requires a separate authorized change rather than an edit that
quietly broadens this proposal.
