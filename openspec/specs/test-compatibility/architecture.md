# Testing and Compatibility Architecture

The [normative contract](spec.md) defines established test boundaries. This document explains how each test level contributes different evidence and how asynchronous cross-service flows remain deterministic.

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

## Boundary-change evidence

A moved or extracted boundary may require wheel-content checks, typing markers, dependency-direction tests, consumer suites, composition startup, duplicate-registration checks, and retry/idempotency coverage in addition to ordinary unit tests. Which checks apply follows the authority being changed.

## Agent-driven capacity preparation boundary

Capacity preparation extends the issue-discovery tool with a portable contract;
it does not turn the public repository into an infrastructure orchestrator. The
boundary separates scenario meaning and sanitized decisions from the authority
that may run agents and infrastructure.

| Public issue-discovery authority | External runner authority |
|---|---|
| Finite VM/G1 scenario meaning and canonical hashes | Agent processes, model credentials, and role-session supervision |
| Required role/action receipts and expected outcomes | Isolated homes, workspaces, wallets, SSH configuration, and logs |
| Sanitized result, finding, fingerprint, and issue/fix candidate contracts | Cloud, host, provisioning, wallet, and authenticated GitHub credentials |
| Public ref/run context and mock/fake/dry-run adapter selection | Exact environment selection, raw evidence, and real adapter implementations |
| Deterministic cancellation/cleanup keys and receipt validation | Performing authorized cancellation and cleanup and producing bound receipts |

The public CLI therefore has no capacity execution command. It can validate an
external result or receipt only after binding it to an explicit public ref,
scenario, run, timeout, termination, and adapter map. Adapter names express
typed seams; they do not imply that the public package contains those adapter
implementations.

### Role ownership model

The scenario contract distinguishes controller-driven reference evidence from
agent-driven evidence. Reference B1 represents one ordinary product lifecycle
without claiming agent load. In substantive rows, a seller owns its
quickstart-defined identity, service, and frozen listing; a buyer owns its
quickstart-defined preparation and exact purchase invocation in one retained
session; and the host role owns the declared external provisioning lifecycle. The controller
coordinates authority checks, barriers, bounded observation, cancellation,
evidence, and cleanup but does not impersonate those role actions.

For concurrent rows, preparedness and concurrency are separate facts. Buyers
first prepare distinct frozen demands, then one controller release boundary
allows the same buyer sessions to invoke them. For serialized reuse, terminal
teardown and zero residue separate the two requests. These receipts make the
role and timing contract inspectable without embedding model prompts or
provider commands in public SCM.

### Evidence and claim levels

Evidence is intentionally layered:

1. schema and pure-function tests prove finite scenario meaning, hashes,
   lifecycle classification, privacy, and stable identity;
2. CLI and mocked-contract tests prove context and receipt binding,
   fail-closed adapters, lifecycle classification, and deterministic
   non-mutating decisions;
3. an external fake-process integration layer can prove role ownership,
   barriers, session persistence, cancellation, and cleanup control flow;
4. an optional hermetic model rehearsal is warranted only when prompt
   interpretation, session persistence, or agent-owned action behavior cannot
   be proved below that layer; and
5. real market, wallet, cloud, host, KVM, Ansible, VM, and GPU evidence belongs
   to a separately authorized execution phase.

Passing a lower layer proves only that layer. In particular, a valid scenario,
mocked result, or model rehearsal is not Q0-Q8 execution, infrastructure
qualification, simultaneous fulfillment capacity, provisioning throughput, or
system-capacity evidence.

### Stable public identity and privacy

Scenario identity hashes compact, key-sorted normative scenario JSON after
normalizing the set-like required-receipt list. Finding identity hashes the
scenario hash, classification, failure code and location, and normalized stable
evidence summary, so repeated occurrences share an issue scope while keeping
distinct occurrence markers. Run IDs, timestamps,
public refs and SHAs, request ordinals, and other occurrence metadata are
excluded from the fingerprint but retained in bounded occurrence metadata.
Raw reservation, fulfillment, executor, and provider values; accounts;
wallets; paths; network/host identities; credentials; and private refs are not
emitted in public findings.

Cancellation and cleanup use distinct idempotency identities. Each key binds
the operation, public context, scenario identity, run context, normalized
adapter map, and termination; a receipt from any other context is not
interchangeable.

Issue planning consumes the original validated result and derives every
finding itself. It uses a caller-supplied issue snapshot only when an eligible
finding needs publication planning. This keeps create, update, reopen, no-op,
withhold, suppression, and fix-candidate decisions deterministic without
granting the public command ambient GitHub authority.

### On-demand execution seam

Explicit refs, scenario hashes, role counts, timeouts, adapter selections,
external workspaces, stable JSON, idempotency keys, and typed cleanup receipts
allow the same contract to be wrapped by a local process supervisor, a
managed job, or a pipeline task. The wrapper supplies identity and secrets;
the public contract remains unchanged. No interactive desktop assumption is
part of the interface, but no cloud runner, schedule, or pipeline implementation
is implied by this seam.

## Current limits

The e2e harness predominantly uses HTTP clients and explicit test seams, but it is not yet completely external to service packages and a few scenarios retain timing or private-client dependencies. The architecture therefore states the desired boundary only where current tests establish it and treats full harness extraction as separate work.

The capacity preparation interface establishes only schemas, validators,
planners, and non-live adapter boundaries. It does not establish that an
external runner, role agent, infrastructure target, or authenticated mutation
path is available or qualified.

Repository-wide typed-client ownership, universal sync/async parity, and a closed list of raw-HTTP exceptions are not established baseline guarantees.

## Related contracts

- [Deployment and state](../deployment-state/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
