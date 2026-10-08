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

For an injected domain boundary, focused tests supply a compatible contract object distinct from the default and assert object identity at application, container, repository, codec, settlement, and fulfillment seams. Invalid type, identity, version, declarations, and hook sets are rejected at the root with stateful collaborators left untouched. Existing HTTP and package suites continue to own observable workflow parity; restart coverage reopens real persisted identifiers and confirms that parameterization adds no schema rewrite.

Architecture tests inspect production imports and package metadata rather than test monkeypatch patterns. They enforce one default contract construction site, no lower-layer singleton accessor, no concrete cross-domain import, and an installed dependency on the lower-layer contract package.



## Multi-domain storefront evidence ownership

Core tests own contribution discovery, frozen registry invariants, exact-object resolution, schema-opaque carriers, publication fan-out, immutable bindings, and cross-swap rejection. Domain suites own selected-site adapters and payment receipt gates. Bare-metal live acceptance requires disposable hardware, real access and revocation, teardown, and capacity release; deterministic ports cannot establish those claims. API-credit suites own canonical key ownership, fulfillment-keyed grants, unknown-outcome retrieval, private credential delivery, and retryable issuance.

## Payment evidence ownership

SCM's credential-free suites exercise generated payment models, shared JCS vectors, mandate policy, signed receipts, accepted-state persistence, and domain composition through deterministic collaborators. A controlled VM smoke can prove pending → provisioning → ready with one delivery, but cannot prove a live ledger or hardware effect.

The payments service owns ledger accounting, fee collection, hold release, disputes, and cash-provider behavior. Consumer tests do not inherit Stripe claims or a signed hosted-release profile matrix. Live qualification against a deployed payments service is owned by the payments service's own end-to-end tests, which import this repository's published packages; this repository does not import the private service to test it. This repository's live payment scenario runs only when a payments target is configured, and otherwise reports the unmet prerequisite. A live payment run records the actual service target, consumer revision, authentication method, seed state, and observed readiness. Missing credentials, unavailable service, or missing physical target is reported as an unmet prerequisite before scenario mutations, not converted into local acceptance.

## Current limits

The e2e harness predominantly uses HTTP clients and explicit test seams, but it is not yet completely external to service packages and a few scenarios retain timing or private-client dependencies. The architecture therefore states the desired boundary only where current tests establish it and treats full harness extraction as separate work.

Repository-wide typed-client ownership, universal sync/async parity, and a closed list of raw-HTTP exceptions are not established baseline guarantees.

## Related contracts

- [Deployment and state](../deployment-state/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
