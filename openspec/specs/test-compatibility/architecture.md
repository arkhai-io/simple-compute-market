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

SCM's credential-free suites exercise generated payment models, shared JCS vectors, mandate policy, signed receipts, accepted-state persistence, and domain composition through deterministic collaborators. A controlled VM smoke can prove pending → provisioning → ready with one delivery, but cannot prove a live ledger or hardware effect.

The payments service owns ledger accounting, fees, hold release/extensions and
cash providers; the dispute authority owns cases/rulings and applies their effects. Consumer tests do not inherit Stripe claims or a signed hosted-release profile matrix. Complete-deal qualification that needs the payments service's internals (local ledger, development-mode auth, operator test funds, ledger reads) is owned by the payments service's own end-to-end tests, which import this repository's published packages; this repository does not import the private service to test it. This repository's live payment scenario targets a public payments test deployment through its public API, runs only when such a target is configured, and otherwise reports the unmet prerequisite. A live payment run records the actual service target, consumer revision, authentication method, seed state, and observed readiness. An absent or unready external payments target, or a missing physical target, is reported as an unmet prerequisite before scenario mutations, not converted into local acceptance. Once a payments target is configured, the settings a scenario supplies itself — its parties' accounts and credentials and the service policy it pins — are configuration the run owes, so a missing one fails the scenario, naming it, rather than blocking it: a run with no target stays a blocked skip, while a misconfigured payments run fails deterministically.

### The in-lane payments double

The VM, bare-metal, and API-credit lanes each run a payments double, `tools/payments-lane-double`, so their once-only payment scenarios run rather than skip. It is an HTTPS service over the payments kit's `PaymentsAuthority` engine — the engine the in-process `FakePaymentsClient` uses, so there is no second ledger — and it mirrors the payments service's API: its routes, bearer authentication, approval admission in the service's order, read authorization, the idempotent repeat of an approved mandate whatever the clock or balance, and the published `ApiError` codes. It serves whatever its engine serves; its suite and documentation claim only the once-only surface: approval, Agreement attachment, signed receipts, transaction snapshots, seller reverse, and the account's own balance read. A double mirrors its producer unless there is a compelling reason to deviate ([`ARCHITECTURE.md`, "Testing strategy"](../../../docs/development/ARCHITECTURE.md#testing-strategy)), because a double that answers differently proves only that a client agrees with the double.

Each lane's callers reach it at `https://payments-double:8443` under a committed lane CA they trust through their payments configuration's `ca_bundle_path`; its accounts, tokens, receipt-signing seed and certificates are labelled public development values. The lane marks the target its own (`PAYMENTS.LANE_OWNED`), so an unready double fails the run by name rather than turning every payment scenario into a skip, and lane setup runs each payment storefront's `check-payments` from its own container before any scenario. A result against the double establishes that SCM's roles compose through the payments service's published HTTP contract from committed configuration. It establishes nothing about the payments service's ledger, funding, availability, live receipts, or rate parts and holds at the HTTP boundary: the double always signs `livemode: false`, so a live-configured role refuses its receipts, and its state lives in one process's memory for the life of the lane.

The lanes' registries recommend one pinned dispute authority nobody can answer: its origin is `https://dispute.invalid`, under a top-level domain that never resolves; its record key was generated with its private half discarded unrecorded; and its account has no bearer token at the double. A copied fixture is therefore refused by mode, unknown to a real service, or inert. The VM payment scenario's operator-end case and refund stages need an authority that accepts a filed case, a setting apart from the payments target (`MEDIATION.SERVICE_URL`, blank by default); without one they report a blocked skip naming it, while its commit, delivery, replay and servicing stages run against the double. The VM lane's storefront holds an identity-bound dispute credential for the pinned authority, so servicing reports the deal `running` while that authority cannot be reached rather than `repair_required`.

## Lifecycle contract evidence

The payments kit owns installed JSON Schema/generated models, JCS/signature and
snapshot vectors, and one clock-injected per-part `PaymentsAuthority` fixture
engine. Its in-process `FakePaymentsClient`, its consumer fixtures, and the lanes'
HTTP payments double all use that engine; only the double can serve a buyer
subprocess or a storefront container. Mediation owns its
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

The ordinary buyer method is also written as scenarios. Each compute lane runs a buyer purchase through the shipped CLI in `arkhai.payments.v1` against its payments double: VM's ends by a back-dated lease and a stepped watchdog cycle, bare metal's by the buyer's teardown before the seller's refund. The real-provisioning qualification modules make the runbook's observations 2, 4, 5 and 6 against a configured real-provisioning target and payments target: those of observations 2, 4 and 5 extend those purchases, adding only the real-host stages, and observation 6's makes no deal, reapplying registrations on the stack their purchases populated ([`TESTING.md`, "Locally verifiable and external-topology scenarios"](../../../docs/development/TESTING.md#locally-verifiable-and-external-topology-scenarios)). The scenarios are the method a candidate's qualification reaches for first; the operator-run method above remains accepted beside them.

A purchase scenario checks each transaction against its records — bound to its Agreement, its receipt over that mandate, its snapshot naming the configured payer and payee with gross equal to the Agreement's price — and checks the payer's account by a balance sum: the drop in the payer's `available` balance, read through the payments kit's `get_balance` with the buyer's own token, from before its first purchase to after its last approval, equals the sum of its own transactions' debits. The sum proves the scenario's debits account for the drop, not that nothing else debited the account, so it rests on a precondition the scenario cannot check: the payer account is dedicated to the run, which is the deployment's guarantee, stated beside the result. Proving exclusivity would need a payer-scoped debit listing, which the payments service does not offer. Funding and its proof are the deployment's, joined to the run by transaction identifiers.

An `arkhai.payments.v1` option is published only with an accepted dispute authority, and every mandate names that authority's account. A deployment running the qualification pins an authority identity whose account is real at its payments target, and nothing needs to answer at its origin: servicing records an unanswered authority and continues. The lanes' registries recommend one nobody answers, so the locally verifiable purchases exercise the same path on every run. The bare-metal buyer's teardown files a delivery-end case with it, which records `Unknown`; the scenarios neither fail on that filing nor read it as delivery, access-end or refund evidence.

## Current limits

The e2e harness predominantly uses HTTP clients and explicit test seams, but it is not yet completely external to service packages and a few scenarios retain private-client dependencies. Compute pipeline scenarios advance only by their own steps ([spec](spec.md#requirement-pipeline-scenarios-advance-only-by-their-own-steps)); the API-credit lane steps its storefront's chain probe and listing seed but holds none of its loops, so an unstepped timer can still run beside its stages; the real-host scenarios, which run outside every pipeline lane, still poll the hardware they drive. The architecture therefore states the desired boundary only where current tests establish it and treats full harness extraction as separate work.

Repository-wide typed-client ownership, universal sync/async parity, and a closed list of raw-HTTP exceptions are not established baseline guarantees.

## Related contracts

- [Deployment and state](../deployment-state/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
