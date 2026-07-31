# Testing and Compatibility Architecture

The [normative contract](spec.md) defines established test boundaries. This
document explains how each test level contributes different evidence, how
asynchronous cross-service flows remain deterministic, and how capacity-test
authority stays truthful across executors.

## Test jurisdiction

Use the lowest level that can prove the behavior:

| Level | Primary evidence |
|---|---|
| Unit | Pure transformations, validation, state transitions, and policy with injected collaborators |
| Service integration | Persistence, dependency wiring, HTTP mapping, authentication, retries, and one service's client behavior |
| Contract/conformance | A shared producer/consumer session or carrier interpreted by independent implementations |
| Smoke | Deployed reachability, basic configuration, and stateless wiring |
| System/e2e | Major lifecycle contracts spanning deployed authorities |

Higher-level tests do not repeat every lower-level branch. They prove that independently tested components compose through their public boundaries.

## Producer and consumer contracts

A cross-package fixture is an executable contract. The producer owns a minimal canonical builder and validates its own output; consumers validate required semantics while tolerating nondeterministic identifiers or timestamps. Shared fixtures live in an installed owning namespace so tests exercise package boundaries rather than checkout-relative files.

Use a shared fixture only when independent implementations must agree. The API-credits middleware conformance session is the clearest current example: Python, TypeScript, and Rust gates consume one observable protocol while keeping implementation internals separate.

## Deterministic asynchronous seams

A sleep is not evidence that a lifecycle transition occurred. Deterministic asynchronous tests use one or more of:

- an observable accepted/queued state;
- a server-side wait or long poll;
- a test-control gate that pauses execution at a named boundary;
- a public or test-only event/status surface.

A gate allows a test to assert the intermediate state before deliberately permitting completion. Test controls remain separate from buyer/public APIs and must not become production authority.

## Staged system tests

A staged scenario names each produced field and each downstream prerequisite. Consumers require the exact state they use and skip clearly when an upstream stage did not produce it, avoiding cascades of misleading failures.

The VM full-deal coverage uses complementary vehicles: a controlled flow gives precise assertions at intermediate boundaries, while a real buyer-CLI flow proves buyer-visible composition. Both traverse publication, negotiation, settlement, fulfillment, ready state, and release without making e2e own every component semantic.

Scenario fixtures create the precise resource and policy state they assert, remain idempotent across reruns, and clean up state that ordinary lifecycle timing cannot safely reclaim during the test.

## Agent-driven capacity evidence

Capacity experiments classify evidence on two independent axes. The execution
boundary says what system boundary ran; the actor trigger says how a
request-bearing stage or action was initiated, or `none` for no-request
readiness. Keeping these axes separate prevents a substantive agent process, a
real infrastructure path, and a capacity claim from being inferred from one
another.

| Boundary and trigger | Evidence artifact | What it establishes |
| --- | --- | --- |
| `readiness` / `none` | Probe or role receipt | A no-request readiness condition; no action or capacity claim |
| `mock` / `agent-triggered` | Capture-only mock artifact | Portable role, frozen-action, and one-shot-wrapper composition with an empty live-resource ledger; no real provisioning or authenticated private actor ownership |
| `real-reference` / `controller-driven` | Capacity result | A deterministic real B1 lifecycle control under independent observer and host-operator evidence; not agent-capacity evidence |
| `real-qualification` / `agent-triggered` | Capacity result | A substantive agent-owned real KVM/Ansible/GPU path; no measured frontier |
| `real-measured` / `agent-triggered` | Capacity result | A substantive agent-owned measured path; frontier eligibility depends on successful independent load generation, while cleanup and correctness remain separate observations and progression gates |

“Agent-driven” means more than an agent approving bytes. Buyers and sellers
perform their pinned quickstart preparation, own their frozen market actions,
remain alive through the release barrier, and invoke the pinned one-shot
wrapper themselves. The controller may validate and freeze bytes, coordinate
barriers, and drive the deterministic reference, but it cannot act later on
behalf of an exited agent. The independent observer remains distinct from that
controller and owns the canonical SHA-256 seals for every exact outcome object
and the complete cleanup object.

An authoritative rejected action or failed overlap, skew, queue, or throttle
predicate remains useful negative agent-provenance evidence. It does not
establish a product-capacity boundary: load-generator failure censors the
product frontier rather than manufacturing an SCM limit. Likewise, a mock
capture demonstrates portable composition but neither authenticates the
private Codex process nor exercises KVM, Ansible, GPU, or durable fulfillment
authority.

## Public and private capacity-test authority

The public repository owns semantics that must remain reviewable and portable:

- closed scenario, profile, role, action, result, and finding contracts;
- deterministic canonicalization and Git-pinned validation;
- execution-boundary and actor-trigger meanings;
- independent-oracle, topology-lineage, cleanup, and frontier rules; and
- sanitized portable projections and privacy-preserving binding shapes.

Private infrastructure owns facts that the public repository cannot
authenticate safely: the live Codex process and release channel, credentials
and wallets, cloud-project admission, real host/GPU/topology and generation
fences, native evidence, watchdog and cancellation behavior, cost controls,
live teardown, and credentialed GitHub mutation. A conforming private campaign
verifies every opaque private-to-portable binding against owner-only native
proof. A public binding correlates artifacts; it does not prove the private
fact by itself.

This division also keeps preparatory public operations non-effecting. Public
validation, hashing, capture-only mock composition, and local finding handoff
do not fund wallets, publish live listings, emit purchases, create or destroy
VMs, touch KVM/Ansible/GPUs, allocate cloud resources, execute live cleanup, or
mutate GitHub.

## Pinned semantics and the executor seam

The cross-repository seam requires private orchestration to consume public
policy through deterministic SCM CLI/runner projections. A conforming adapter
supplies an exact SCM commit plus the expected canonical and, where applicable,
raw-byte digests. SCM performs Git-backed validation and returns the complete
validated registry or stage semantics, resolved scenario semantics or null,
paths, ref, and applicable digests in one closed JSON object. The adapter must
consume that object rather than import SCM Python, reread the worktree file
after validation, or maintain a second copy of profile policy.

The portable command and artifact contract preserves one seam for the current
local-Codex execution strategy and a future cloud or Tekton executor. Any
executor-local context paths may locate private inputs during an invocation,
but they do not enter canonical artifacts. Credentials, process supervision,
cancellation, native logs, and resource cleanup remain behind the private
adapter. Consequently, moving the same validated bytes between machines or
schedulers does not change their public identity or validation outcome.

## Capacity evidence and cleanup truth

Actor and emitter statuses are inputs, not the capacity oracle. Real outcomes
are correlated independently through the storefront deal reference,
reservation, durable `fulfillment_id` and Settlement Record, provisioned VM,
whole-device GPU/CUDA exercise, and teardown. Expected scarcity requires the
independent final atomic-reservation observation and terminal compensation;
an aggregate null or the nonterminal `capacity_hold_unavailable` event is not
capacity refusal.

The independent observer seals the canonical SHA-256 of every exact request
outcome object and of the complete cleanup object. The host operator
independently attests teardown and baseline restoration. A request-bearing real
stage may authorize progression only when those authorities agree with
complete terminal correlations, zero active residue, and the exact baseline
partitions: reversible resources return to equality, while only declared and
reconciled append-only/accounting deltas remain. The next-stage fence follows
the later completed observer or host-operator evidence. A producer clean flag,
actor success, or terminal service status cannot override missing evidence,
residue, or a baseline mismatch.

Finding evidence has separate raw-byte authority. Each portable evidence
reference is a repository-independent `evidence/` path plus SHA-256 of the
exact raw bytes below one explicit immutable root; canonical JSON digests do
not substitute for those hashes. Public validation rejects sensitive content
rather than rewriting it, and private infrastructure applies its exact-value
denylist before export. Cleanup-incomplete observations remain retainable
negative evidence, but they are not ready for issue publication or stage
progression.

## Boundary-change evidence

A moved or extracted boundary may require wheel-content checks, typing markers, dependency-direction tests, consumer suites, composition startup, duplicate-registration checks, and retry/idempotency coverage in addition to ordinary unit tests. Which checks apply follows the authority being changed.

## Current limits

The e2e harness predominantly uses HTTP clients and explicit test seams, but it is not yet completely external to service packages and a few scenarios retain timing or private-client dependencies. The architecture therefore states the desired boundary only where current tests establish it and treats full harness extraction as separate work.

Repository-wide typed-client ownership, universal sync/async parity, and a closed list of raw-HTTP exceptions are not established baseline guarantees.

The public capacity tool validates portable authority but cannot authenticate a
Codex session, private credentials, a cloud project, or native host/GPU state.
Those claims become real qualification or measured evidence only when the
private executor verifies them and returns artifacts that satisfy the same
public validators. Cloud or Tekton scheduling is an executor implementation
choice behind that seam, not a different evidence contract.

## Related contracts

- [Deployment and state](../deployment-state/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Capacity testing](../capacity-testing/spec.md)
