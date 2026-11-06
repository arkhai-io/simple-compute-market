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

Architecture tests inspect production imports and package metadata rather than test monkeypatch patterns. The repository check, `make check-architecture`, holds the layer, scope, and kind rules for every package, including no concrete cross-domain import. Per-package architecture tests hold what it cannot express: one default contract construction site, no lower-layer singleton accessor, which module of a package may import what, and an installed dependency on the lower-layer contract package.



## Multi-domain storefront evidence ownership

Core tests own contribution discovery, frozen registry invariants, exact-object resolution, schema-opaque carriers, publication fan-out, immutable bindings, and cross-swap rejection. Domain suites own selected-site adapters and payment receipt gates. Bare-metal live acceptance requires disposable hardware, real access and revocation, teardown, and capacity release; deterministic ports cannot establish those claims. API-credit suites own canonical key ownership, fulfillment-keyed grants, unknown-outcome retrieval, private credential delivery, and retryable issuance.

## Payment evidence ownership

SCM's credential-free suites exercise generated payment models, shared JCS vectors,
mandate policy, signed receipts, accepted-state persistence and domain composition.
A controlled VM smoke can prove pending → provisioning → ready with one delivery,
but cannot prove a hosted ledger or a hardware effect.

The VM, bare-metal and API-credit Compose lanes run
[`tools/payments-lane-double`](../../../tools/payments-lane-double/README.md), an
HTTP wrapper around the payments kit's clock-injected `PaymentsAuthority` engine.
`FakePaymentsClient` uses the same engine: there is one deterministic ledger model.
The double mirrors the producer's routes, bearer authentication, admission,
authorization, idempotency and errors. Its suite claims the once-only surface;
its labelled public accounts, tokens, seeded payer, receipt signer and lane CA
are development fixtures, never production credentials. Receipts always state
`livemode: false`. These results establish SCM's use of the public payments
boundary, not provider funding, hosted-ledger correctness or service availability.

Bare-metal and API-credit payment stages run without skips. VM commit, delivery,
replay and servicing stages run; operator-end and refund stages require an
accepting mediation target (`MEDIATION.SERVICE_URL`) and otherwise report a named
blocked skip. The registry's recommended fixture authority has an `.invalid`
origin, no usable private half for its record key and no bearer token at the
double. The VM storefront has a public development dispute credential in its
secret overlay, so unavailable mediation leaves servicing `running` rather than
making an otherwise usable credential absent. No production fixture-identity
refusal is implemented by this double.

The independently operated payments service owns accounting, fees, hold release
and extensions, and cash providers. The Agreement-named dispute authority owns
cases, rulings and their effects. Consumer tests inherit neither Stripe claims
nor a hosted-release qualification matrix. Tests requiring a service's internals
belong to that service; SCM imports public contracts and tests its clients.
External qualification records the actual target, consumer revision,
authentication, funding provenance and readiness before mutations. An absent or
unready external target or missing physical host is an unmet prerequisite.
Configured missing settings and an unready lane-owned target fail by name before
scenarios, without a settlement fallback. Real access, revocation and capacity
return require their own physical observations.

## Lifecycle contract evidence

The payments kit owns installed JSON Schema/generated models, JCS/signature and
snapshot vectors, and one clock-injected per-part `PaymentsAuthority` fixture
engine. Its in-process `FakePaymentsClient`, the lane HTTP double and consumer fixtures use that engine. Mediation owns its
independently installed schema/models, both ed25519/eip191 claim vectors and
ruling traces. These fixtures prove deterministic public-contract compatibility,
not the internal implementation or deployed monetary execution of either service.
SCM imports no authority service implementation.

Unit/service suites own same-key retry, lost-response adoption, caller-session
admission/end races, exact-envelope capture, pinned-authority verification,
independent cursor floors, respondent answer journals and conservative retention.
Site/provisioning producer integration tests own atomic event/outbox rollback,
all ending causes, crash/ack recovery, exact signed push/pull after signer change,
unsupported-peer parking and explicit resumption. Consumers do not replace that
producer proof with a hand-built report.

Deployed VM and mock-bare-metal scenarios distinguish receipt-time surrender,
retrieval of the original signed site report before teardown, and later proven
capacity return. Mock provisioning proves no physical access or revocation.
Once-only payment/case encounters prove no rate stop, funding or monetary ruling
execution. A configured real authority and, for physical claims, a disposable
real host remain qualification prerequisites. Readiness failures and unrun lanes
are named, not converted into fixture passes. See the
[lifecycle limits](../deal-lifecycle/architecture.md#current-limits).

## Ordinary Arkhai purchase evidence

A physical qualification can drive the shipped ordinary buyer and collect independent observations through the supported typed operator clients. Keep buyer credentials separate from operator credentials and bind each run's source, selected artifacts, configuration, buyer result, Agreement/payment evidence, reservation, fulfillment, provisioning jobs, and access observations in restricted evidence. Public summaries should retain only sanitized outcomes and explicit limits.

A completed payment proof correlates genuine TEST funding evidence with attributable rental charges and the accepted Agreement/receipt state; pre-existing unexplained credit is not funding proof. The receipt gate and seller/provider lifecycle observations establish distinct facts. Paid buyer journeys are required for claims about the actual tenant identity, negotiated privilege, valid grant, GPU work, delivery, ordinary teardown, fresh access denial, and restored capacity. A supplemental network-policy probe is admissible only from an actual operator-only CPU guest on the same paid deployment, using the pinned guest base, its actual default bridge and virtio NIC, and the loaded policy structure. It may establish only the finite selectors observed on that path; it establishes none of the paid tenant identity, credential, privilege, grant, GPU, payment, delivery, or lifecycle facts and does not prove universal isolation. A namespace-only probe is not a substitute for this guest-path evidence.

The ordinary buyer method may replace a payment-specific scenario driver, but it does not make an old named test marker pass. Preserve unrun or unavailable observations explicitly, and do not equate a controlled local smoke, published vector, or component suite with external funding or physical access.

## Current limits

The e2e harness predominantly uses HTTP clients and explicit test seams, but it is not yet completely external to service packages and a few scenarios retain timing or private-client dependencies. The architecture therefore states the desired boundary only where current tests establish it and treats full harness extraction as separate work.

Repository-wide typed-client ownership, universal sync/async parity, and a closed list of raw-HTTP exceptions are not established baseline guarantees.

## Related contracts

- [Deployment and state](../deployment-state/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
