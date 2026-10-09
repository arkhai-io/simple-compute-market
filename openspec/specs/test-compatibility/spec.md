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

Credential-free SCM tests MUST prove generated wire contracts, JCS hashes, mandate policy, signed-receipt rejection, exact Agreement and settlement-data persistence, selected-mechanism dispatch, retryable pending, and idempotent domain delivery through deterministic ports. They MUST NOT claim live ledger or provider behavior, which remains producer-owned evidence.

#### Scenario: Local payment smoke uses controlled collaborators

- **WHEN** a local VM smoke drives pending to provisioning to ready with controlled HTTP and delivery
- **THEN** its evidence establishes SCM receipt gating and one delivery, not live payment-service or hardware acceptance

#### Scenario: API-credit payment is retried

- **WHEN** seller progress is nonterminal after an issuance acknowledgement is lost
- **THEN** focused domain tests use the same transaction and grant identity and assert no duplicate balance or quota mutation

### Requirement: External payment qualification names its target

External qualification MUST identify the actual payments target and consumer revision, check readiness before mutations, and report unavailable prerequisites rather than substitute another mechanism. Payment-service ledger, hold release, fees, disputes, top-ups, payouts, and provider recovery remain the payments service's evidence.

#### Scenario: Bare-metal qualification lacks hardware

- **WHEN** a disposable selected-site host is unavailable
- **THEN** local deterministic tests do not claim authenticated access, revocation, or physical teardown

### Requirement: Signed receipts in tests come from the kit fixture

A test that needs a signed receipt over its own Agreement MUST sign it through the payments kit's receipt fixture with an injected signer. The fixture ships no key material, and a kit unit test reproduces the published receipt vector byte for byte.

#### Scenario: A storefront test needs a verified receipt

- **WHEN** an integration test settles a payments deal
- **THEN** it builds the receipt with the kit's fixture and a test signer, and the vector test proves the fixture signs what the service signs

### Requirement: A deployable domain's deal runs on every end-to-end run

Every market domain intended for deployment MUST have a complete-deal scenario that runs
on every run of the end-to-end pipeline, against running services using that domain's
ordinary local or test authorities. A domain whose delivery crosses compute provisioning
MUST run provisioning in its mock profile. The scenario MUST hold every storefront loop
it depends on, preview each transition it advances through that loop's or route's dry
run where one exists, and advance it explicitly. That scenario proves the services
compose into a working deal. Mocked delivery MUST NOT be reported as evidence of real
delivery: where a domain's release acceptance requires a real external resource, that
remains a separate protected lane.

#### Scenario: Bare metal runs its deal in the pipeline

- **WHEN** the bare-metal end-to-end lane runs
- **THEN** a whole-host deal completes through discovery, negotiation, Alkahest
  settlement, mock-provisioned delivery, lease expiry, and teardown, observed through
  typed clients, with every dry-run stage VM's deal runs
- **AND** the site releases the Physical Resource's reservation, the storefront receives
  the capacity-released callback, and the next publication pass reopens the listing

#### Scenario: Buyer teardown is repeated

- **WHEN** the bare-metal lane's second deal requests teardown twice
- **THEN** both requests return the same lease release operation and the site releases
  the reservation once

#### Scenario: Real access is required

- **WHEN** release acceptance requires observing real access and its revocation
- **THEN** the mock-provisioned deal does not satisfy it, and the protected lane's
  requirement stands

### Requirement: The canonical compute deal's shared stages are defined once

The compute family's canonical complete deal, settled through Alkahest and delivered
through the provisioning mock profile, MUST take each stage its domains run identically
from one shared definition. A domain MUST subclass a shared stage without replacing its
body and MUST supply its differences through fixtures and a per-domain driver. A domain
MAY insert stages of its own; a stage whose body differs between domains is not shared.

#### Scenario: A shared stage changes

- **WHEN** a shared stage's preview, advance, or assertion changes
- **THEN** every compute lane that runs the canonical deal runs the changed stage without
  a per-domain edit

#### Scenario: A domain's part of a shared stage

- **WHEN** a shared stage needs supply seeding, provision terms, mock rules and their
  release, the lease view, settlement-preview expectations, the settlement's dispatch,
  result and access assertions, or the claim that re-reserves released supply and its
  release
- **THEN** the domain's driver supplies it and the stage's body is unchanged

#### Scenario: A deal outside the canonical deal

- **WHEN** a compute scenario settles another way, or a domain outside the compute family
  runs a complete deal
- **THEN** it keeps its own stages

#### Scenario: A compute domain differs in negotiation

- **WHEN** a compute domain would need its own negotiation stage
- **THEN** the difference is resolved in its storefront composition, not in the stage

### Requirement: Each domain runs in its own lane

The end-to-end pipeline MUST run each market domain's scenarios in a lane of its own, as
a pipeline job separate from every other domain's lane, so a failure in one domain's
lane cannot hide or stand in for another's evidence. Each lane MUST build the images its
own stack runs and compose only its own services, including every registry its
scenarios read.

#### Scenario: The pipeline runs

- **WHEN** the end-to-end pipeline runs
- **THEN** the VM, bare-metal, and API-credit lanes each build their own stack's images
  and run their own stack and scenarios, in parallel
- **AND** the VM lane's stack does not include the API-credit services

#### Scenario: A scenario reads a registry of another schema

- **WHEN** a lane's scenario discovers across registries of more than one schema
- **THEN** the lane deploys each of those registries in its own stack, and the scenario
  reads them from that lane's settings

#### Scenario: A compute lane provisions through the mock profile

- **WHEN** a compute lane runs
- **THEN** its provisioning services run their mock profile because the run selects mock
  provisioning, not because the lane's local overlay or stack hard-codes it
- **AND** no storefront in the lane carries a provisioning mode

### Requirement: Bare-metal storefront restart recovery is proven at integration level

Bare-metal storefront restart recovery MUST be proven by integration tests that rebuild
the production application over the same database. After a rebuild following settlement
commit or teardown acceptance, the buyer MUST retrieve the same operation without a
second obligation, mechanism selection, or physical teardown, and duplicate polling and
result reads MUST be idempotent. The end-to-end lane starts from empty state and does
not restart services.

#### Scenario: Process stops after settlement commit

- **WHEN** the settlement authority committed the recorded operation but the buyer did not receive its response
- **THEN** after the rebuild, resume retrieves the same operation and continues without a second obligation or mechanism selection

#### Scenario: Process stops while the lease is active

- **WHEN** the storefront is rebuilt while a delivered lease is active
- **THEN** repeated status, result, access, and settlement-status reads return what they returned before, with no second reservation or fulfillment start

#### Scenario: Process stops after teardown acceptance

- **WHEN** teardown was accepted before the response was lost
- **THEN** after the rebuild, a repeated teardown returns the same lease release operation and the site releases capacity once
