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

### Requirement: Stripe-backed hosted settlement system evidence
Hosted settlement system E2E MUST compose the marketplace with one exact ordinary signed production hosted release and Stripe test mode. Marketplace-owned stages MUST exercise publication, discovery, negotiation, materialization, buyer action, funding, fulfillment evidence, collection or reclaim, status, restart, and recovery through released public clients and network contracts. Claims about Checkout, connected-account readiness, webhook signatures, provider retrieval, charges, transfers, refunds, declines, or authentication MUST come from supported Stripe test-mode behavior and MUST NOT be satisfied by a local provider substitute.

#### Scenario: Real Stripe collection succeeds
- **WHEN** an authorized protected run completes Checkout with a Stripe test payment method, delivers the signed webhook, and satisfies the accepted fulfillment condition
- **THEN** the ordinary authority worker converges to collected and authoritative retrieval identifies exactly one related payment and destination transfer with the expected amount, currency, connected destination, transfer group, source transaction, stable idempotency identity, and marketplace operation identity

#### Scenario: Real Stripe reclaim succeeds
- **WHEN** a distinct paid test-mode obligation remains unfulfilled until pre-transfer reclaim is eligible
- **THEN** buyer-authorized reclaim converges to exactly one related Stripe refund, recovery under the original operation identity creates no second refund, and no transfer exists for that obligation

#### Scenario: Missed webhook is reconciled
- **WHEN** real Checkout completes while webhook forwarding or the reconciliation worker is stopped and ordinary processes later restart against preserved authority state
- **THEN** authoritative Stripe retrieval converges the accepted obligation without recreating Checkout or payment and any transfer or refund uses the original operation identity exactly once

### Requirement: Deterministic hosted recovery is tested at the provider port
Deterministic tests for timeout placement, unknown acknowledgement, delayed authoritative visibility, provider unavailability, exact-attempt failures, and duplicate or out-of-order normalized events MUST inject declared outcomes at the hosted service's internal financial-provider or webhook-inbox boundary. They MUST exercise the production operation journal, immutable request fingerprints, leases, retry policy, idempotency, reconciliation, webhook inbox, and lifecycle logic without exposing a provider-compatible API, reproducing Stripe objects, requiring provider credentials, or packaging the collaborator with production artifacts. Assertions MUST describe Arkhai state, calls, and effects under a scripted provider outcome; every assertion presented as Stripe behavior MUST be covered separately by Stripe test-mode evidence.

#### Scenario: Submission acknowledgement is unknown
- **WHEN** a test-only scripted provider records one immutable effect and returns an unknown acknowledgement before bounded retrieval exposes it
- **THEN** the production journal records uncertainty, reconciliation retrieves the original effect through the provider interface, and retry retains one operation identity and one effect

#### Scenario: Provider failure is prescribed
- **WHEN** a test prescribes a timeout, retryable failure, terminal failure, delayed visibility, or unavailability at a named provider-interface operation
- **THEN** it asserts only Arkhai's resulting state transition, retry, reconciliation, and idempotency behavior and makes no claim that Stripe produces the failure in that way

### Requirement: Public and protected hosted checks remain distinct
Default builds, test discovery, public CI, and fork workflows MUST run without Stripe credentials, connected-account identifiers, webhook secrets, Checkout actions, provider payloads, or private hosted source. They MUST include credential-free client conformance, adapter, provider-port integration, packaging, configuration, release-verification, and marketplace orchestration coverage at their owning repositories. Explicit protected system execution MUST require the exact verified production release, test-mode Stripe access, network connectivity, loopback webhook forwarding, Chromium, and an allowlisted ready connected account; a missing prerequisite MUST be reported before publication or financial mutation rather than replaced by local simulation or a silent skip.

#### Scenario: Contributor runs public checks
- **WHEN** no Stripe credential or protected hosted release access is present
- **THEN** default collection and execution succeed without probing provider controls or attempting hosted financial E2E

#### Scenario: Explicit protected run lacks a prerequisite
- **WHEN** an operator selects hosted Stripe system E2E without one required release, credential, network, webhook, browser, or connected-account prerequisite
- **THEN** preflight reports the exact unmet prerequisite before payment creation and does not cite focused or simulated output as Stripe evidence

### Requirement: Protected hosted evidence is attributable and sanitized
Protected hosted E2E MUST classify terminal outcomes as `product`, `account`, `environment`, or `timeout`. Every report MUST identify the marketplace consumer repository and exact commit separately from the hosted production manifest digest, client wheel version and hash, service image digest, and signed release repository, workflow reference, and hosted source commit. The protected producer workflow run identity MUST be recorded separately as orchestration evidence and MUST NOT be presented as a signed-manifest field. The report MUST also contain only an allowlisted scenario and stage, unique run identity, opaque durable operation identity, normalized state, amount, currency, cardinality, and bounded diagnostics. Reports and process output MUST exclude credentials, action or onboarding URLs, account/customer/card data, raw webhook bodies, unrestricted provider payloads, and unrelated provider objects. Setup and read-only observation MAY retry within declared bounds; financial mutations MUST retain the original production idempotency identity and MUST NOT be reissued by the harness under a new identity.

#### Scenario: Stripe is unavailable during setup
- **WHEN** a protected run cannot reach Stripe before any marketplace or financial mutation
- **THEN** it reports an `environment` failure with separately identified consumer and hosted release coordinates and records no secret or provider payload

#### Scenario: Connected account is not ready
- **WHEN** the allowlisted test connected account fails its ownership, capability, or readiness checks
- **THEN** preflight reports an `account` failure before publishing the hosted option or creating payment state

#### Scenario: Terminal state violates the contract
- **WHEN** prerequisites are valid and the observed signature, state, amount, relation, cardinality, or marketplace transition contradicts the accepted scenario
- **THEN** the run reports a `product` failure with bounded sanitized evidence and does not hide it behind an environment or timeout classification

#### Scenario: A valid observation does not converge
- **WHEN** prerequisites remain valid but a named observable state does not arrive within its declared bound
- **THEN** the run reports a `timeout` failure under the original operation identity without issuing a replacement mutation

### Requirement: Buyer profile compatibility is deterministic across domains

Focused tests MUST exercise versioned profile creation/import/selection/update/rotation/retirement/deletion, every exact credential provider, strict ownership and permissions, malformed and interrupted stores, missing secrets, principal mismatch, duplicate profile/principal, rotation overlap, run and binding blockers, and coordinated multi-run migration rollback.

The VM and API-credit plugins MUST run against the same selected-primary and retained-recovery matrix. Secret canaries MUST be absent from JSONL, TOML, stdout/stderr, exception and object reprs, Compose/Helm renders, ConfigMaps, images, wheels, and evidence.

#### Scenario: One plugin attempts legacy fallback

- **WHEN** an installed buyer plugin lacks the resolved-identity injection contract or reads direct identity configuration
- **THEN** conformance fails before the plugin performs discovery or an authenticated effect

#### Scenario: A migration candidate fails after an earlier replacement

- **WHEN** coordinated profile/run-log migration cannot validate or replace every candidate
- **THEN** tests observe complete profile and run-log restoration, no partial activation, and an actionable unresolved-manifest failure

### Requirement: Injected storefront contracts have boundary-owned evidence

Focused tests MUST prove that one caller-supplied compatible domain contract reaches the application, lifespan/container, repository, publication, negotiation, settlement, and fulfillment boundaries by identity, and that incompatible type, identity, version, declaration, or hook-set inputs fail before startup side effects. Existing package and integration tests MUST continue to own observable VM listing, negotiation, settlement, Alkahest, restart, and accepted-row parity.

#### Scenario: A distinct compatible contract is injected

- **WHEN** a composition test supplies a compatible `compute.v1` contract object distinct from the ordinary default
- **THEN** application state, dependencies, codecs, settlement, fulfillment, and repository assertions observe that exact object

#### Scenario: Import-boundary evidence runs

- **WHEN** architecture tests inspect production modules and installed package metadata
- **THEN** they reject module-global contract access, concrete cross-domain imports, source-tree-only dependencies, and missing lower-layer contract declarations

## Evidence

- Layer ownership: package unit/integration suites, role-level E2E scenarios, and the independently released hosted producer's financial-provider and webhook-inbox integration suites.
- Cross-language API-credit protocol behavior: `middleware/conformance/session.json` and the Python, TypeScript, and Rust conformance runners.
- Explicit staged dependencies: `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`, scenario `require_state` calls, and `e2e-tests/tests/e2e/roles/README.md`.
- Protected hosted system evidence: the canonical `hosted-stripe-test` target and workflow, their schema-validated sanitized report, and the exact ordinary hosted production release recorded by that report.

Additive/optional client coexistence during a staged rollout is not established as a general baseline contract; registry rollout work remains proposed in `migrate-registry-to-postgres`.
