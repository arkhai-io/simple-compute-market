## MODIFIED Requirements

### Requirement: Deals compose negotiate, settle, and provision stages

Negotiation MUST pass its exact accepted Agreement to the domain's selected settlement stage. The settle stage MUST be the post-commitment handoff by which the seller learns of the mechanism's commitment and verifies it; it is not a protocol step. Protected delivery MUST consume that stage's verified SettlementEvidence rather than compare mechanism IDs or infer payment from an escrow's presence. Core MUST NOT prescribe the actors' order or require separate buyer-confirm and seller-verify steps. Domains MUST compose only supported stages; settlement and delivery MAY be fused.

#### Scenario: Arkhai payment gates domain provisioning

- **WHEN** a VM seller receives `commit` for an Agreement settled through `arkhai.payments.v1`
- **THEN** delivery remains blocked until its stage verifies a signed receipt matching the transaction ID and Agreement deal hash and produces verified evidence

### Requirement: Marketplace roles hold no payment ledger

Marketplace roles MUST NOT own ledger state or implement cash movement, Stripe top-ups, payouts, or provider recovery. Mechanism kits MUST keep no settlement servicing state or daemon; headless callers supply owner-scoped credentials per request and verify service-signed receipts through the identity kit. A storefront MAY keep lifecycle observation state (watch cursors, funding timers, the end-service journal, and evidence records), which records what an authority reported and never a balance.

#### Scenario: A headless caller checks a payment

- **WHEN** a buyer or seller process checks a payment
- **THEN** it supplies its owner-scoped credential for that request and verifies the service-signed receipt through the identity kit, keeping no servicing state between calls

#### Scenario: A storefront watches a deal

- **WHEN** a storefront watches a hosted deal
- **THEN** it stores the authority's event sequence as its cursor and stores no balance or settled amount of its own
