## ADDED Requirements

### Requirement: Agreement-settlement responses are strict on both sides

The client MUST refuse an agreement-settlement or refund response missing a required field, and each storefront MUST validate its payment payload through the core response models before returning it.

#### Scenario: A drifted settlement response is refused

- **WHEN** an agreement-settlement or refund response omits a required field
- **THEN** the client raises a storefront client error rather than returning a partial result

### Requirement: No payment mutation before accepted terms

Discovery, filtering, preference, and proposal construction MUST use advertised options and local configuration only. Mandate approval MUST NOT occur until exact seller-accepted Agreement bytes and settlement data are durably recorded.

#### Scenario: Negotiation exits before acceptance

- **WHEN** the buyer declines, times out, or reaches a pricing limit
- **THEN** it creates no payment transaction or domain delivery operation

### Requirement: Payment buyers approve and settle by negotiation

The buyer MUST supply its Arkhai account as `payer_account`, validate the mandate against the Agreement and local payment policy, approve with owner-scoped WorkOS credentials, poll the deterministic transaction ID, and call seller settlement with only the negotiation ID. Marketplace requests MUST use the recorded profile signer and storefront trust, independently of payment credentials.

#### Scenario: Payment and marketplace credentials stay separate

- **WHEN** a payment buyer approves a mandate and then settles
- **THEN** the approval uses the owner's WorkOS credential, and the settle request is signed by the recorded profile signer and carries only the negotiation ID

### Requirement: Payment buyers preserve accepted state

VM, bare-metal, and API-credit buyers selecting `arkhai.payments.v1` MUST retain exact Agreement bytes, the advertised option, opaque settlement selection parameters, and seller-derived `settlement_data`. Resume MUST reuse that accepted state and transaction identity, not current priority or an incomplete reconstructed listing.

#### Scenario: Payment buyer resumes after approval

- **WHEN** the accepted run is resumed after an approval acknowledgement is lost
- **THEN** it validates and reuses the same mandate and transaction, then retrieves or resumes the same domain result without renegotiation

#### Scenario: Bare-metal buyer retrieves access

- **WHEN** the recorded buyer retrieves an active selected-site lease result
- **THEN** authenticated transient access coordinates are delivered separately from public payment state and never enter the run log

#### Scenario: API-credit buyer retrieves a grant

- **WHEN** a verified payment has issued credits but the buyer did not observe credentials
- **THEN** it retrieves the same grant through the authenticated seller boundary rather than approving or issuing again

### Requirement: The typed client settles Agreement deals apart from EVM deals

The typed storefront client MUST settle an Agreement-settled deal with `settle_agreement(negotiation_id)`, which sends only the negotiation ID and the signer's principal; EVM settlement is the separate `settle_evm`, so EVM arguments never appear on the agreement path. Both use the settle route contract, and the storefront dispatches on the accepted Agreement's mechanism.

#### Scenario: A buyer settles a payments deal through the typed client

- **WHEN** a buyer settles an accepted Arkhai payments deal with `settle_agreement`
- **THEN** the request carries the negotiation ID and the buyer's principal and no EVM fields

## MODIFIED Requirements

### Requirement: Buyer config template is role-appropriate

Generated buyer configuration MUST use the shared `[Settlement]` vocabulary while omitting seller-only publication, authority administration, onboarding, and provider fields. Mechanism-specific buyer constraints MAY appear only in the owning typed subsection.

#### Scenario: Payments-only buyer initializes configuration

- **WHEN** the user generates an Ed25519 payment buyer config
- **THEN** the output contains profile-store and settlement preference inputs but no private identity or wallet/chains

### Requirement: Buyer consumes common settlement preference

Buyer orchestration MUST filter advertised options by installed/enabled mechanisms and use the canonical configured priority as policy input before accepted Terms. It MUST resolve mechanism-specific prerequisites only after a concrete option is selected and MUST NOT treat priority as permission to switch an accepted obligation.

#### Scenario: Arkhai payments is preferred

- **WHEN** a compatible Arkhai payment and Alkahest option are both advertised and `arkhai.payments.v1` is first in buyer priority
- **THEN** the buyer policy may select Arkhai payments without resolving wallet, chain, RPC, token, or gas inputs

#### Scenario: Preferred option is incompatible

- **WHEN** the first-priority mechanism has no compatible advertised option
- **THEN** policy may evaluate the next configured mechanism before negotiation acceptance, but it does not rewrite a seller option or invent fallback after acceptance

### Requirement: Buyer mechanism utilities are namespaced

Raw mechanism-specific setup, inspection, and mutation commands MUST live below `market settlement <mechanism>`. Payment approval is an internal accepted-run step, not payer-profile administration. Normal `market buy`, `market settle`, resume, and accepted-obligation lifecycle commands MUST derive mechanism inputs from the selected option, persistent buyer profile, and accepted run and MUST NOT accept chain-, token-, provider-, raw payer-ref-, or browser-specific override flags.

#### Scenario: Accepted Alkahest run is resumed

- **WHEN** `market settle --from <run>` resumes Terms containing an Alkahest obligation
- **THEN** the command derives chain, token, decimals, and escrow identity from accepted state and typed configuration without legacy override flags

### Requirement: Identity-first buyer orchestration

The core buyer role MUST receive one injected marketplace signer for discovery-authenticated actions, negotiation, storefront settlement, heartbeat, and recovery. The signer-provided buyer identity MUST be the exact canonical `{scheme, identifier}` principal; identifier equality under a different scheme MUST NOT authorize the buyer. Core orchestration MUST resolve wallet and chain settings only when the selected domain or settlement adapter declares an EVM effect, and it MUST NOT name or pass private-key strings through schema-opaque orchestration.

#### Scenario: Buyer chooses Arkhai payments

- **WHEN** an Ed25519 buyer selects a compatible `arkhai.payments.v1` option
- **THEN** core negotiation and settlement use that signer while wallet, chain, RPC, token-balance, and gas checks are not invoked

#### Scenario: Buyer chooses Alkahest

- **WHEN** the selected obligation requires an Alkahest transaction
- **THEN** the Alkahest adapter separately resolves and validates its EVM wallet and chain inputs before the chain effect

### Requirement: Mechanism-neutral constrained preference

Buyer orchestration MUST normalize legacy escrow entries and settlement options into immutable preference candidates only after installed/enabled compatibility and authoritative resource constraints. Explicit repeatable settlement clauses MUST be evaluated in command order before configured-policy ranking, and every predicate in one clause MUST match the same advertised option. Policy output MUST NOT introduce an unadvertised or incompatible choice. When no explicit clause is supplied, configured mechanism priority remains the pre-acceptance policy input.

#### Scenario: Buyer requests Arkhai payments
- **WHEN** a Arkhai payment clause and supported asset leave several payment options
- **THEN** buyer policy ranks only those matching payment options and exact deterministic fallback applies if it expresses no preference

#### Scenario: Buyer selects Alkahest
- **WHEN** an Alkahest clause or interactive choice selects an existing compatible Alkahest option
- **THEN** the existing escrow creation/submission path and run-log fields remain unchanged and no payments API is called

#### Scenario: Several clauses match
- **WHEN** more than one explicit settlement clause has compatible candidates
- **THEN** the earliest matching clause wins before configured mechanism priority and no later clause is considered after acceptance

## REMOVED Requirements

### Requirement: API-credit hosted buys share accepted-state transport

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Bare-metal buyers preserve accepted hosted authority

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Buyer payer-profile utilities are direct and namespaced

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Delayed bank state is resumable and provider-neutral

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Exact purchase authorization precedes storefront start

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Hosted buyer action handling

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: No provider call before accepted terms

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Off-session automation is buyer-owned and obligation-exact

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Storefront-mediated hosted buyer action

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.
