# Testing and Compatibility Specification

## Purpose

Define test-level ownership, shared contract fixtures, deterministic e2e staging, and client rollout behavior.

## Requirements

### Requirement: Layered behavioral verification
Unit, integration, smoke, and end-to-end tests MUST each defend the narrowest observable contract appropriate to their level and MUST NOT rely on e2e alone for component behavior.

#### Scenario: Service API behavior changes
- **WHEN** a route contract changes
- **THEN** focused unit/integration coverage pins the route behavior and e2e verifies only the cross-service flow

### Requirement: Shared contract fixtures
Cross-language or cross-package implementations of the same protocol MUST consume canonical fixtures that encode observable requests, responses, and state transitions.

#### Scenario: API-credit middleware port changes
- **WHEN** Python, TypeScript, or Rust middleware behavior is updated
- **THEN** each implementation reproduces the shared conformance session

### Requirement: Dependency-aware e2e stages
The end-to-end stage that violates an observable contract MUST fail; downstream stages MUST explicitly declare consumed prior state and skip with the exact missing state field rather than failing for an unrelated symptom.

#### Scenario: Required deal state is absent
- **WHEN** a downstream stage lacks a prerequisite produced by an earlier stage
- **THEN** the skip reason names the missing `DealState` field

### Requirement: Exact e2e state dependencies
Every staged e2e state field MUST use one exact producer/consumer name, and every field introduced for downstream behavior MUST have at least one explicit `require_state` consumer.

#### Scenario: Test author adds staged state
- **WHEN** a test adds a field to `DealState`
- **THEN** a downstream stage consumes that exact attribute name and coverage verifies the transition

### Requirement: Buyer profile compatibility is deterministic across domains

Focused tests MUST exercise versioned profile creation/import/selection/update/rotation/retirement/deletion, every exact credential provider, strict ownership and permissions, malformed and interrupted stores, missing secrets, principal mismatch, duplicate profile/principal, rotation overlap, run and binding blockers, and coordinated multi-run migration rollback.

The VM and API-credit plugins MUST run against the same selected-primary and retained-recovery matrix. Secret canaries MUST be absent from JSONL, TOML, stdout/stderr, exception and object reprs, Compose/Helm renders, ConfigMaps, images, wheels, and evidence.

#### Scenario: One plugin attempts legacy fallback

- **WHEN** an installed buyer plugin lacks the resolved-identity injection contract or reads direct identity configuration
- **THEN** conformance fails before the plugin performs discovery or an authenticated effect

#### Scenario: A migration candidate fails after an earlier replacement

- **WHEN** coordinated profile/run-log migration cannot validate or replace every candidate
- **THEN** tests observe complete profile and run-log restoration, no partial activation, and an actionable unresolved-manifest failure

### Requirement: Multi-domain storefront selection has focused compatibility coverage

Deterministic focused tests MUST cover frozen registry validation, immutable listing/thread binding, publication mode enforcement, domain-envelope matching, selected-site routing, settlement/fulfillment contexts, migration, restart recovery, result decoding, and teardown under both VM and bare-metal contracts. Duplicate, missing, unknown, unsupported, mismatched, and cross-swapped modes/identities/versions MUST fail before an unselected policy, persistence mutation, capacity call, provider call, or decoder runs.

#### Scenario: One and two registrations use the same shell

- **WHEN** focused composition runs with one explicit registration and with VM plus bare-metal registrations
- **THEN** both use the same common routes, repository, publication runner, and lifecycle carriers without a singleton or domain-specific control-flow copy

#### Scenario: Unknown binding is injected at a lifecycle boundary

- **WHEN** publication, opening, continuation, settlement, fulfillment, result, recovery, or teardown receives an unknown or mismatched binding
- **THEN** the owning boundary rejects it and its mutation/network spies remain untouched

#### Scenario: Installed-artifact deployment is inspected

- **WHEN** clean staged wheels render the combined image, Compose, and Helm configuration
- **THEN** both enabled contributions are discoverable, disabled domains leave no wait/source path, and signer/provider/SSH/private-result canaries are absent from public artifacts

#### Scenario: Full live proof is requested

- **WHEN** the production bare-metal contribution or selected-site POOLS-7 lifecycle is unavailable
- **THEN** the real multi-domain E2E remains explicitly blocked rather than recording fake publication, fulfillment, teardown, or capacity-restoration success

### Requirement: Per-domain end-to-end deal path

Every market domain intended for deployment MUST have an end-to-end scenario
proving discovery, negotiation, settlement, delivery, and domain-defined
teardown against running services. Scenarios MUST use the shared
domain-neutral state, profile/config, event-order, and client helpers rather
than copying a VM scenario or interpreting another domain's listing,
fulfillment result, private authority state, or teardown carrier.

#### Scenario: A domain is deployed

- **WHEN** a market domain is intended for deployment
- **THEN** its release-qualified scenario observes one complete deal through the ordinary public buyer and seller boundaries

#### Scenario: Another domain needs a deal path

- **WHEN** its listing, result, or teardown semantics differ from VM
- **THEN** the scenario supplies domain codecs and assertions to shared helpers without adding a domain guess, default route, or copied orchestration

#### Scenario: An external authority is unavailable

- **WHEN** a live seller, site/provisioning authority, chain, payments authority, credential, or real access target required by the selected scenario is absent
- **THEN** that exact live assertion remains blocked or unavailable and static composition is not reported as end-to-end success

### Requirement: Payment evidence is attributed at its owning boundary

Credential-free SCM tests MUST prove generated wire contracts, JCS hashes, mandate policy, signed-receipt rejection, exact Agreement and settlement-data persistence, selected-mechanism dispatch, retryable pending, and idempotent domain delivery through deterministic ports. They MUST NOT claim live ledger or provider behavior. Payment-service ledger, hold release, fees, disputes, top-ups, payouts, and provider recovery remain producer-owned evidence. External qualification MUST identify the actual payments target and consumer revision, check readiness before mutations, and report unavailable prerequisites rather than substitute another mechanism. A test that needs a signed receipt over its own Agreement signs it through the payments kit's receipt fixture with an injected signer; the fixture ships no key material, and a kit unit test reproduces the published receipt vector byte for byte.

#### Scenario: Local payment smoke uses controlled collaborators

- **WHEN** a local VM smoke drives pending to provisioning to ready with controlled HTTP and delivery
- **THEN** its evidence establishes SCM receipt gating and one delivery, not live payment-service or hardware acceptance

#### Scenario: Bare-metal qualification lacks hardware

- **WHEN** a disposable selected-site host is unavailable
- **THEN** local deterministic tests do not claim authenticated access, revocation, or physical teardown

#### Scenario: API-credit payment is retried

- **WHEN** seller progress is nonterminal after an issuance acknowledgement is lost
- **THEN** focused domain tests use the same transaction and grant identity and assert no duplicate balance or quota mutation

#### Scenario: A storefront test needs a verified receipt

- **WHEN** an integration test settles a payments deal
- **THEN** it builds the receipt with the kit's fixture and a test signer, and the vector test proves the fixture signs what the service signs

