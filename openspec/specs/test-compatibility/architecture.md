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

## Hosted settlement evidence ownership

Hosted settlement has one provider-authentic system lane and two lower-level
evidence boundaries. Each boundary proves only behavior it owns:

| Evidence boundary | Owner | What it proves |
|---|---|---|
| Financial-provider and webhook-inbox integration | Hosted producer | Production journal, immutable fingerprints, leases, retries, idempotency, reconciliation, inbox deduplication, and lifecycle transitions under provider-neutral scripted outcomes |
| Client, adapter, configuration, packaging, and marketplace orchestration | Owning producer or marketplace package | Released public contracts and credential-free composition without provider mutation |
| Protected `stripe-test` system E2E | Marketplace consumer | The complete marketplace lifecycle composed with an exact ordinary hosted production release and supported Stripe test-mode Checkout, webhook, connected-account, retrieval, transfer, refund, decline, and authentication behavior |

The hosted producer's scripted collaborator is a direct test injection at its
financial-provider interface. It has no HTTP server, provider-shaped public
model, credential, clock/event control API, production entry point, or release
artifact. Scripts prescribe typed interface outcomes; names and assertions
describe Arkhai behavior under those outcomes rather than attributing them to
Stripe. Focused Stripe adapter tests verify SDK request construction and
normalization, but only the protected lane establishes real Stripe behavior.

The marketplace owns protected publication, discovery, negotiation,
materialization, buyer action, VM fulfillment, collection, reclaim, status,
restart, and recovery scenarios. It consumes the hosted implementation only
through the signed production manifest, released client, digest-pinned image,
ordinary migration, API, worker, and public network contracts. Missed-webhook
and restart evidence pauses real forwarding or ordinary processes and retains
the authority store and original operation identity; arbitrary provider fault
placement remains at the provider port.

Every protected run creates a unique namespace but keeps financial
idempotency derived from durable operation identity. Retrieval follows the
exact Checkout, payment, transfer, or refund relations created by that run
rather than accepting an account's latest object. Reports identify the
marketplace repository and exact consumer commit separately from the hosted
manifest digest, client wheel hash, service image digest, signed release
repository/workflow reference/source commit, and the separate protected
producer workflow run identity used as orchestration evidence.

Preflight establishes a verified production release, a test-mode secret
(`sk_test` or least-privilege `rk_test`), non-live returned objects, Stripe connectivity, an allowlisted capable and
ready connected account, loopback-only webhook forwarding, and Chromium
before publication or financial mutation. Terminal results use the
`product`, `account`, `environment`, and `timeout` classes. Evidence is an
allowlist of identities, scenario/stage, opaque operation identity, normalized
state/amount/currency/cardinality, and bounded diagnostics; secrets, action
URLs, account/customer/card data, raw webhooks, and unrestricted provider
payloads never enter reports.

Public and fork checks receive no protected credentials and do not discover or
skip secret-bearing tests. Alkahest system E2E remains a separate mechanism
lane. Local EAS/allowlisted-arbiter work is condition-boundary conformance
only; it is not part of hosted financial evidence, and there is currently no
standalone hosted local-EAS operator target.

## Expanded consumer evidence matrix

Credential-free marketplace tests own exact profile configuration and option identity, per-profile readiness/publication, persistent opaque payer binding, direct payer and authorization helpers, bounded automation, storefront mediation, transient action redaction, delayed funding gates, immutable journals, legacy recovery, reclaim races, and package boundaries. They use the released provider-neutral client with deterministic ports and never stand in for Stripe assertions.

The protected VM lane attributes each selected `card.v1`, `us_bank_transfer.v1`, `us_ach_debit.v1`, and off-session `requires_action` assertion separately. Reports keep marketplace source/commit distinct from the hosted signed manifest, client, image, schema/migrations, provenance, repository/workflow/source, and protected workflow run. A missing rail, account, mandate, browser, or signed-release prerequisite is an unavailable assertion, not permission to substitute another profile or local simulation.

Reports permit only public lifecycle stages, profile/currency, normalized outcomes, timestamps, attempts, and bounded hashed opaque correlations. Recursive canary scanning rejects credentials, provider/customer/payment-method/mandate/bank/card data, raw actions or URLs, payloads, events, requests, source-bearing local paths, and unrestricted logs before evidence is signed.

## Current limits

The e2e harness predominantly uses HTTP clients and explicit test seams, but it is not yet completely external to service packages and a few scenarios retain timing or private-client dependencies. The architecture therefore states the desired boundary only where current tests establish it and treats full harness extraction as separate work.

Repository-wide typed-client ownership, universal sync/async parity, and a closed list of raw-HTTP exceptions are not established baseline guarantees.

## Related contracts

- [Deployment and state](../deployment-state/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
