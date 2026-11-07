## ADDED Requirements

### Requirement: External payment qualification names its target

External qualification MUST identify the actual payments target and consumer revision, check readiness before mutations, and report unavailable prerequisites rather than substitute another mechanism. Payment-service ledger, hold release, fees, disputes, top-ups, payouts, and provider recovery remain the payments service's evidence.

#### Scenario: Bare-metal qualification lacks hardware

- **WHEN** a disposable selected-site host is unavailable
- **THEN** local deterministic tests do not claim authenticated access, revocation, or physical teardown

### Requirement: Payment evidence is attributed at its owning boundary

Credential-free SCM tests MUST prove generated wire contracts, JCS hashes, mandate policy, signed-receipt rejection, exact Agreement and settlement-data persistence, selected-mechanism dispatch, retryable pending, and idempotent domain delivery through deterministic ports. They MUST NOT claim live ledger or provider behavior, which remains producer-owned evidence.

#### Scenario: Local payment smoke uses controlled collaborators

- **WHEN** a local VM smoke drives pending to provisioning to ready with controlled HTTP and delivery
- **THEN** its evidence establishes SCM receipt gating and one delivery, not live payment-service or hardware acceptance

#### Scenario: API-credit payment is retried

- **WHEN** seller progress is nonterminal after an issuance acknowledgement is lost
- **THEN** focused domain tests use the same transaction and grant identity and assert no duplicate balance or quota mutation

### Requirement: Signed receipts in tests come from the kit fixture

A test that needs a signed receipt over its own Agreement MUST sign it through the payments kit's receipt fixture with an injected signer. The fixture ships no key material, and a kit unit test reproduces the published receipt vector byte for byte.

#### Scenario: A storefront test needs a verified receipt

- **WHEN** an integration test settles a payments deal
- **THEN** it builds the receipt with the kit's fixture and a test signer, and the vector test proves the fixture signs what the service signs

## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: Bare-metal hosted evidence is attributed by layer

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Consumer fault cases preserve exact identity

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Deterministic hosted recovery is tested at the provider port

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Expanded hosted consumer behavior is tested at owned boundaries

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Hosted API-credit evidence is attributed at its owning boundary

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Protected hosted evidence is attributable and sanitized

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Public and protected hosted checks remain distinct

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Stripe-backed hosted settlement system evidence

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.
