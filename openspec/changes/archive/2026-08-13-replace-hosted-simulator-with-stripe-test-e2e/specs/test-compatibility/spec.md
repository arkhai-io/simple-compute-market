## REMOVED Requirements

### Requirement: Artifact-bound hosted settlement system evidence

**Reason**: The requirement makes a private durable simulator and its release identity part of hosted system acceptance. Stripe behavior will instead be accepted only through the ordinary hosted production release connected to Stripe test mode; deterministic collaborator failures belong below E2E.

**Migration**: Replace hermetic hosted targets and reports with the protected Stripe system evidence requirement below. Move simulator-only recovery cases to provider-port integration tests under the deterministic hosted recovery requirement. Preserve exact production release verification and marketplace-owned cross-service scenarios.

### Requirement: Public test entry points exclude private hosted fixtures

**Reason**: Private simulator fixtures, manifests, controls, and images are removed rather than conditionally excluded.

**Migration**: Replace this boundary with the public/protected hosted test separation below. Default and fork workflows continue to run without hosted provider credentials, while protected Stripe system acceptance is explicit.

## ADDED Requirements

### Requirement: Stripe-backed hosted settlement system evidence

Hosted settlement system E2E MUST compose the ordinary signed production hosted release with the marketplace and Stripe test mode. Marketplace-owned stages MUST exercise publication, discovery, negotiation, materialization, buyer action, funding, fulfillment evidence, collection or reclaim, status, restart, and recovery through released public clients and network contracts. Assertions about Checkout, Connect readiness, webhook signatures, provider retrieval, charges, transfers, refunds, declines, or authentication MUST come from supported Stripe test-mode behavior and MUST NOT be satisfied by a local Stripe-compatible simulator.

#### Scenario: Real Stripe collection succeeds

- **WHEN** an authorized protected run completes Checkout with a Stripe test payment method, delivers the signed webhook, and satisfies the accepted fulfillment condition
- **THEN** the ordinary authority worker converges to collected and authoritative evidence identifies exactly one matching Checkout payment and destination transfer with the expected amount, currency, connected account, transfer relation, idempotency identity, and marketplace operation identity

#### Scenario: Real Stripe reclaim succeeds

- **WHEN** a distinct paid test-mode obligation remains unfulfilled until reclaim eligibility and has not transferred funds
- **THEN** buyer-authorized reclaim converges to exactly one Stripe refund, repeated recovery creates no second refund, and no transfer exists for that obligation

#### Scenario: Missed webhook is reconciled

- **WHEN** a real Checkout payment completes while webhook forwarding or the reconciliation worker is stopped and the ordinary authority processes later restart against preserved authority state
- **THEN** authoritative Stripe retrieval converges the accepted obligation without recreating Checkout or payment and any later transfer or refund uses the original stable operation identity exactly once

### Requirement: Deterministic hosted recovery is tested at the provider port

Deterministic tests for timeout placement, unknown acknowledgement, delayed authoritative visibility, provider unavailability, exact-attempt failures, and arbitrary event ordering MUST inject declared outcomes at the hosted service's internal financial-provider interface. They MUST exercise the production operation journal, idempotency, reconciliation, webhook inbox, and lifecycle logic without exposing a Stripe-compatible API, reproducing Stripe objects, or claiming Stripe behavior. Every outcome asserted as Stripe behavior MUST remain covered separately by Stripe test-mode evidence.

#### Scenario: Submission acknowledgement is unknown

- **WHEN** an integration test's provider collaborator records one immutable transfer effect and returns an unknown acknowledgement before retrieval exposes that effect
- **THEN** the production operation journal records uncertainty, reconciliation retrieves the original effect through the provider interface, and retry retains one operation identity and one effect

#### Scenario: Provider failure is prescribed

- **WHEN** an integration test prescribes a timeout, retryable failure, terminal failure, delayed visibility, or unavailability at a named provider-interface operation
- **THEN** the test asserts only Arkhai's resulting state transition, retry, reconciliation, and idempotency behavior and makes no claim that Stripe produces that failure in the same way

### Requirement: Public and protected hosted checks remain distinct

Default builds, test discovery, public CI, and fork workflows MUST run without Stripe credentials, connected-account identifiers, webhook secrets, Checkout actions, provider payloads, or private hosted source. They MUST include the focused adapter, provider-port integration, packaging, configuration, and marketplace orchestration coverage that does not require provider mutation. Explicit protected system execution MUST require test-mode credentials, network connectivity, verified webhook forwarding, and a ready connected account and MUST report a missing prerequisite rather than substitute local simulation or silently skip.

#### Scenario: Contributor runs public checks

- **WHEN** no Stripe credential or protected hosted release access is present
- **THEN** default collection and execution succeed without importing provider controls or attempting hosted financial E2E

#### Scenario: Explicit protected run lacks a prerequisite

- **WHEN** an operator explicitly selects hosted system E2E without test-mode credentials, Stripe connectivity, webhook forwarding, or connected-account readiness
- **THEN** preflight reports the exact unmet prerequisite before payment creation and does not run or cite simulator evidence

### Requirement: Protected hosted failures are attributable

Protected hosted E2E MUST distinguish product-contract failures from test-account/readiness failures, external environment failures, and bounded convergence timeouts. Setup and read-only observation MAY retry within declared bounds; financial mutations MUST use the original durable idempotency identity and MUST NOT be blindly retried under a new identity. Reports MUST contain allowlisted release, consumer, scenario, operation, normalized amount/currency/state, and failure-class evidence and MUST exclude credentials, action URLs, customer/card data, raw webhook bodies, and unrestricted provider payloads.

#### Scenario: Stripe becomes unreachable during setup

- **WHEN** a protected run cannot reach Stripe before any marketplace or financial mutation
- **THEN** it reports an external environment failure rather than a product failure and records no secret or provider payload

#### Scenario: Terminal state violates the contract

- **WHEN** Stripe is reachable and the observed payment, transfer, refund, amount, relation, signature, or marketplace state contradicts the accepted scenario
- **THEN** the run reports a product-contract failure with bounded sanitized evidence and does not hide it behind an infrastructure classification
