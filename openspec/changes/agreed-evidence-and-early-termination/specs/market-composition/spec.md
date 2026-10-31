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
- **THEN** it stores the payment authority's event sequence and the dispute authority's record sequence as its cursors and stores no balance or settled amount of its own

### Requirement: Arkhai payments authority remains external

`kit/arkhai-payments` MUST consume the payments service's published HTTP and JSON Schema contract, vendored with its conformance vectors and identified by content hash rather than by source location, and generate its Python wire models from it, rather than importing the service implementation or copying a TypeScript contract. The payments service MUST remain the authority for its ledger, account credentials, fees, hold release and hold extensions, and payment-provider operations. Cases and their outcomes MUST belong to the agreement's dispute authority, an independent party that acts at the payments service only through its own authorities and answers parties in its own protocol.

#### Scenario: Payments service owns the ledger

- **WHEN** a marketplace domain composes `arkhai.payments.v1`
- **THEN** it uses the external payments API and signed receipt as authority and keeps no local ledger, payment-provider integration, or settlement daemon

#### Scenario: A case is filed on a hosted deal

- **WHEN** a buyer files a case on an `arkhai.payments.v1` deal
- **THEN** it files with the agreement's dispute authority, and the payments service records only that authority's `extend`, `lift` and outcome effects
