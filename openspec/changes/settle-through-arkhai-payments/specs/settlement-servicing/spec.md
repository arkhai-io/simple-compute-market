## REMOVED Requirements

### Requirement: Hosted obligation pins profile and authorization

**Reason**: `fiat.stripe.v1` funding profiles and operation-scoped Stripe authorizations are removed.

**Migration**: Accepted Arkhai payments agreements carry their own settlement option and transaction identity; no hosted profile is translated.

### Requirement: Authoritative profile funding precedes every domain effect

**Reason**: The Stripe hosted funding state and profile-availability gate are removed.

**Migration**: `arkhai.payments.v1` uses its signed transaction receipt as settlement evidence; Alkahest retains its mechanism-owned escrow checks.

### Requirement: Profile-specific reclaim and loss remain authority-owned

**Reason**: Stripe return, loss, reclaim, and provider-recovery behavior is removed.

**Migration**: A seller refund through Arkhai payments uses the transaction's `reverse` operation; Alkahest retains its own reclaim semantics.

### Requirement: Legacy card obligations recover without public alias

**Reason**: The old Stripe card-only obligation format has no production state to migrate and is not accepted by the new mechanism.

**Migration**: Remove legacy card configuration and recovery branches; do not relabel them as Arkhai payments.

### Requirement: Hosted financial authority lifecycle

**Reason**: The hosted Stripe authority and its conditional-escrow adapter are removed.

**Migration**: Use the Arkhai payments transaction contract for charge-first settlement, or Alkahest's own escrow lifecycle.

### Requirement: Provider-neutral conditional escrow client

**Reason**: A shared conditional-escrow adapter contract would impose escrow verbs on charge-first mechanisms.

**Migration**: Alkahest owns its escrow client internally. Each settlement mechanism exposes its own API to the domains that compose it.

### Requirement: Versioned hosted condition input

**Reason**: The hosted settlement condition descriptor is removed with `fiat.stripe.v1`.

**Migration**: Encode Alkahest condition data in `alkahest.v1` parameters; Arkhai payments settles against its mandate and signed receipt.

### Requirement: Hosted adapter validation and state projection

**Reason**: Stripe adapter, profile validation, and hosted state projection are removed.

**Migration**: Each mechanism validates and projects its own state and evidence through its domain composition.

### Requirement: Fulfillment and reclaim exclusion

**Reason**: The requirement defines the removed hosted reclaim race and authority-funding lifecycle.

**Migration**: Alkahest owns its collect/reclaim exclusion; Arkhai payments refunds use `reverse` while the transaction hold remains active.

### Requirement: Hosted client owns hosted identity wire

**Reason**: The exact hosted settlement client and its payer/profile contract are removed.

**Migration**: The Arkhai payments kit uses the payments service's published API and caller credentials; it does not copy the old client contract.

### Requirement: Configuration composes one settlement runtime

**Reason**: A single mechanism-neutral conditional-escrow runtime is not the settlement API for the composed stages.

**Migration**: Domains compose the selected settlement mechanism's own stage with their provisioning stage; Alkahest keeps its escrow lifecycle within its mechanism boundary.

### Requirement: Bare-metal hosted servicing orders funding, access, and collection

**Reason**: The hosted Stripe servicing path is removed from bare-metal composition.

**Migration**: Bare-metal composes an applicable settlement stage with its site-specific provisioning stage and admits provisioning only on that stage's evidence.

### Requirement: API-credit hosted servicing orders financial and domain effects

**Reason**: The hosted Stripe funding and shared-operation-journal path is removed from API-credit composition.

**Migration**: API-credit composes an applicable settlement stage with its credits issuance stage and gates issuance on settlement evidence.

### Requirement: Negotiation-to-plan handoff

**Reason**: Negotiation now emits an explicit Agreement for the selected settlement stage rather than a shared Settlement Plan.

**Migration**: Pass the accepted Agreement to its selected settle stage before domain provisioning, as required below.

### Requirement: Principal-bound settlement evidence and authority

**Reason**: The old shared claimant/reclaim requirements do not describe Arkhai charge-first approval and refund authority.

**Migration**: Preserve canonical marketplace parties, use the buyer or seller account's own payment credential for Arkhai calls, and keep Alkahest claimant authority within its mechanism parameters.

### Requirement: Chain credentials are mechanism-scoped

**Reason**: The hosted-condition examples are removed, while the underlying mechanism-scoped resource boundary remains.

**Migration**: Require EVM resources only for mechanisms whose own effects use EVM; Arkhai payments uses its HTTP API.
## MODIFIED Requirements


### Requirement: Mechanism-neutral plan carrier

Core settlement carriers MUST retain only mechanism-neutral participant and value fields plus a tagged `{mechanism, params}` envelope. They MUST NOT define `claimant`, `claimant_principal`, `expiration_unix`, or `conditions` as universal lifecycle fields. Core MUST treat mechanism-specific values in `params` as opaque.

#### Scenario: New settlement mechanism is added

- **WHEN** a composition registers a client for a new mechanism
- **THEN** the shared carrier transports its opaque parameters without importing the mechanism kit or imposing escrow lifecycle fields

#### Scenario: Charge-first settlement is selected

- **WHEN** an Agreement selects `arkhai.payments.v1`
- **THEN** settlement uses the mandate and transaction receipt without creating an escrow obligation

### Requirement: Durable idempotent servicing

The Alkahest servicing path MUST bind one immutable fulfillment reference, persist each condition/effect attempt under a stable operation identity, retry transient or pending outcomes, and avoid duplicate successful collection across restarts.

#### Scenario: Collection succeeds before a restart

- **WHEN** the Alkahest servicing path resumes the same obligation
- **THEN** it observes the durable terminal state and does not collect twice

#### Scenario: Condition remains pending across restart

- **WHEN** Alkahest returns pending with updated opaque mechanism state
- **THEN** that state is persisted before backoff and supplied to the next authoritative status or condition check

### Requirement: Mechanism clients own mechanism vocabulary

Each settlement mechanism MUST own the schema and API for its state and effects. Alkahest-specific plan, status, arbiter, collection, and reclaim encoding MUST live inside the Alkahest kit. `ConditionalEscrowClient` MUST NOT be a shared mechanism adapter contract.

#### Scenario: Runtime evaluates an Alkahest obligation

- **WHEN** Alkahest needs mechanism-specific status, readiness, collection, or reclaim behavior
- **THEN** its own client handles the escrow operations with the stable operation reference and prior durable mechanism state

### Requirement: Durable independent obligation lifecycle

Alkahest servicing MUST derive stable repository identity for every ordered plan obligation and persist materialization, condition evaluation, collection, reclaim, attempt, uncertain-acknowledgement, and receipt state independently. Equivalent retries MUST reuse one operation identity; changed reuse MUST fail closed. Alkahest collection and reclaim MUST reserve one mutually exclusive compare-and-swap winner before mechanism I/O.

#### Scenario: Plan contains obligations in both directions

- **WHEN** an accepted Alkahest plan contains buyer-funded and seller-funded obligations
- **THEN** each obligation is materialized by its payer and collected by its claimant without interpreting list position as direction

#### Scenario: One obligation fails after a sibling completes

- **WHEN** an operation requires retry or manual repair after another Alkahest obligation reached a terminal effect
- **THEN** the completed sibling remains terminal and operator status identifies the affected obligation without replaying the completed effect

#### Scenario: Acknowledgement is uncertain across restart

- **WHEN** an Alkahest mutation may have succeeded before its acknowledgement was lost
- **THEN** retry uses the same obligation and operation identity

#### Scenario: Collection races reclaim

- **WHEN** claimant collection and payer reclaim concurrently target one Alkahest obligation
- **THEN** exactly one reservation may invoke the mechanism and the other observes a busy or terminal outcome

### Requirement: Aggregate and per-obligation status

Alkahest operator-facing settlement status MUST derive the plan aggregate from every authoritative obligation row and MUST include each obligation's lifecycle state. Aggregate status MUST be `complete` only when every obligation has a successful collection or reclaim, `manual_required` when any obligation needs repair, `partial` when only some obligations are terminal, and `active` otherwise.

#### Scenario: Mixed terminal and active obligations

- **WHEN** one Alkahest obligation is collected while a sibling remains pending
- **THEN** aggregate status is partial and both independent states are visible

### Requirement: Secret-free fulfillment projection

The VM domain MUST encode only the versioned evidence allowed by the accepted mechanism's condition. Generic fulfillment results, tenant credentials, SSH material, connection details, arbitrary provider fields, URLs, and headers MUST NOT enter fulfillment references, settlement-stage evidence, settlement rows, logs, or generated fixtures.

#### Scenario: VM fulfillment contains connection credentials

- **WHEN** a condition evidence projection is generated from a successful fulfillment result
- **THEN** credentials and connection fields are absent and a canary test rejects any projection that would include them

### Requirement: Mechanism configuration cannot reinterpret durable plans

Mechanism configuration and readiness MAY govern new option publication and admission, but an accepted Agreement MUST retain its exact settlement mechanism, selected option, and parameters. Recovery MUST use the accepted Agreement and mechanism-owned operation identity even when that mechanism is no longer preferred or enabled for new deals.

#### Scenario: Payment mechanism is disabled after acceptance

- **WHEN** reconciliation resumes an existing Arkhai transaction after operators disable new Arkhai payment options
- **THEN** the transaction continues under its accepted mechanism and exact ID rather than switching or being abandoned

## ADDED Requirements

### Requirement: Agreement-to-settlement-stage handoff

Negotiation MUST emit one explicit Agreement containing only accepted deal terms, and the selected settlement stage MUST consume that Agreement before domain provisioning begins. A successful negotiation is not evidence of funding or settlement. A mechanism may produce its own settlement evidence from the Agreement; the domain provisioning stage MUST receive that evidence before its protected provisioning effect.

#### Scenario: Arkhai payments agreement is accepted

- **WHEN** negotiation accepts an Agreement selecting `arkhai.payments.v1`
- **THEN** the seller derives the mandate from that Agreement and provisioning remains blocked until the seller verifies a matching signed transaction receipt

### Requirement: Principal-bound marketplace actions use exact actors

Settlement Agreements, accepted fulfillment references, heartbeats, payment approvals, status/refund requests, and mechanism operation authorization MUST bind the canonical scheme-tagged principals authorized by the accepted negotiation and the selected mechanism. A bare address, identifier, hosted account reference, provider identifier, or API credential MUST NOT replace the authorized marketplace principal. The marketplace MUST treat principals as opaque and MUST NOT infer or persist wallet or private-key aliases from them.

#### Scenario: Heartbeat uses the wrong scheme

- **WHEN** a heartbeat identifier matches the recorded buyer text but its principal scheme differs
- **THEN** the storefront rejects the heartbeat and does not update evidence or reclaim timing

#### Scenario: Arkhai buyer approves with its owner credential

- **WHEN** an authorized buyer approves an `arkhai.payments.v1` mandate using its owner's WorkOS user-scoped API credential
- **THEN** approval is bound to the buyer's Arkhai account and does not resolve wallet or chain settings

#### Scenario: Buyer and seller poll one transaction

- **WHEN** the buyer and seller poll the same accepted Arkhai transaction
- **THEN** both use the transaction ID derived from the accepted mandate, and the seller provisions only after receipt verification

### Requirement: Mechanism credentials remain scoped

A settlement mechanism MAY require an EVM address, wallet, RPC endpoint, chain ID, or deployed contract only when its selected effect performs that EVM operation. Generic settlement carriers and non-EVM mechanisms MUST NOT require or infer those values from marketplace principals.

#### Scenario: Arkhai payment uses no EVM credentials

- **WHEN** an `arkhai.payments.v1` Agreement is settled through the external HTTP service
- **THEN** approval, polling, receipt verification, and `reverse` require no EVM credential or RPC dependency

#### Scenario: Alkahest condition requires an EVM subject

- **WHEN** an Alkahest obligation selects a condition whose contract requires an EVM subject or transaction
- **THEN** the Alkahest kit validates the explicitly tagged EVM input without reinterpreting an Ed25519 principal
### Requirement: Alkahest owns escrow semantics

For `alkahest.v1`, escrow claimant, claimant principal, expiration, and condition semantics MUST be carried in Alkahest-owned option and obligation parameters. The Alkahest kit MUST own interpretation and servicing of those fields, including its `ConditionalEscrowClient`; core carriers and other settlement mechanisms MUST NOT depend on that escrow API.

#### Scenario: Core transports an Alkahest obligation

- **WHEN** a core settlement carrier contains an Alkahest obligation
- **THEN** the claimant, claimant principal, expiration, and conditions are encoded in `alkahest.v1` parameters and core does not interpret them

#### Scenario: A charge-first mechanism is composed

- **WHEN** a domain composes `arkhai.payments.v1`
- **THEN** it uses that mechanism's mandate, transaction, receipt, and refund API without implementing Alkahest collect or reclaim verbs

### Requirement: Arkhai payments settles charge-first from an agreement

The `arkhai.payments.v1` seller kit MUST derive a mandate from the exact accepted Agreement. Its `deal` MUST be `sha256(JCS(agreement))`, and its transaction ID MUST be `sha256(JCS(mandate))`. The mandate MUST identify the buyer's Arkhai account as `from`, the payee account declared by the selected option as `to`, and one `once` part for the agreed amount and asset. The hold MUST cover `(start_utc - accepted_at) + duration_seconds +` the option's declared window. The mandate MUST use the service's published fee policy, authorize `start` and `stop` for the buyer and seller and `reverse` for the seller and Arkhai dispute authority (never the buyer), and use the fixed nonce defined by the design. The seller MUST return the mandate and Agreement so both parties know the transaction ID before approval.

The buyer kit MUST check the mandate against the exact Agreement and buyer policy before approving it with the owner's WorkOS user-scoped API credential. Approval MAY attach the Agreement for dispute handling. If the seller option enables agreement deposit and the transaction snapshot has no Agreement, the seller kit MUST attach it. Both parties MUST poll the same transaction ID. The seller MUST NOT provision until it verifies an Arkhai-signed receipt matching that transaction and the Agreement's `deal`. A seller refund MUST use `reverse`; the payments service releases an un-reversed hold without a settlement-service call.

#### Scenario: Seller derives a mandate before approval

- **WHEN** negotiation accepts an Agreement selecting `arkhai.payments.v1`
- **THEN** the seller returns the Agreement and its derived mandate, and both parties compute the same transaction ID before the buyer approves

#### Scenario: Buyer approves with an optional Agreement attachment

- **WHEN** the buyer approves the exact mandate with its owner's credentials
- **THEN** it attaches the exact Agreement only when selected by buyer policy, while the seller's advertised deposit setting remains visible to the buyer

#### Scenario: Seller provisions only on a matching signed receipt

- **WHEN** the seller polls the transaction ID and receives a receipt
- **THEN** it verifies the Arkhai signature and matching transaction and Agreement deal before provisioning, and rejects an invalid, absent, or mismatched receipt

#### Scenario: Seller reverses a held payment

- **WHEN** the seller determines the deal must be refunded before the hold releases
- **THEN** it requests `reverse` for the same transaction, while a hold without a reverse releases in the payments service without a settlement-service daemon
