## MODIFIED Requirements

### Requirement: Schema-opaque core orchestration

Core role packages MUST own discovery and negotiation control flow without importing a concrete market domain or settlement mechanism. Core MUST expose the accepted Agreement, settlement-option carriers, a mechanism-to-stage table carrier and SettlementEvidence, but MUST NOT impose a shared mechanism-stage API, actor order or escrow lifecycle on mechanism and domain compositions.

#### Scenario: Installing core without a domain plugin

- **WHEN** the core buyer CLI runs without a domain entry-point plugin
- **THEN** it exposes generic discovery and negotiation behavior and no concrete market verbs or settlement implementation

### Requirement: Pre-terms mechanism dispatch is registration-owned

The settlement mechanism for a deal MUST be resolved exactly once, from the buyer's settlement selection or the existing legacy flat-proposal coercion. Pre-terms option interpretation MUST use that registration and the domain's corresponding supported-stage entry. Domain composition MUST dispatch the accepted Agreement through its role table; mechanism-specific validation, mandate construction and settlement translations belong to that entry, not schema-opaque core or common delivery.

#### Scenario: A third mechanism is composed

- **WHEN** a new mechanism registration and supporting role stage are added to a domain and enabled in `[Settlement]`
- **THEN** its options use the registration and its accepted Agreements use that domain's declared stage without another mechanism conditional

#### Scenario: A mechanism conditional is sought in domain code

- **WHEN** the pre-terms path of any composed domain is inspected
- **THEN** concrete-mechanism dispatch exists only in its role table, and any mechanism-specific validation is inside the selected entry's owned hooks

### Requirement: Deals compose negotiate, settle, and provision stages

Negotiation MUST pass its exact accepted Agreement to the domain's selected settlement stage. Protected delivery MUST consume that stage's verified SettlementEvidence rather than compare mechanism IDs or infer payment from an escrow's presence. Core MUST NOT prescribe the actors' order or require separate buyer-confirm and seller-verify steps. Domains MUST compose only supported stages; settlement and delivery MAY be fused.

#### Scenario: Arkhai payment gates domain provisioning

- **WHEN** the seller settles an accepted Agreement through `arkhai.payments.v1`
- **THEN** VM, bare-metal or API-credit delivery remains blocked until its stage verifies a signed receipt matching the transaction ID and Agreement deal hash and produces verified evidence

#### Scenario: A domain composes two settlement mechanisms

- **WHEN** a domain advertises both Alkahest and Arkhai payment options
- **THEN** its role table routes each accepted Agreement to the selected stage and compatible delivery reads normalized evidence without a new core or delivery mechanism conditional

#### Scenario: A settlement mechanism also provides the service

- **WHEN** a deal selects `contact-exchange.v1`
- **THEN** the composed stage may fuse settlement and delivery, produce its introduction evidence and invoke no payment or physical-provisioning phase

#### Scenario: A mechanism requires seller action first

- **WHEN** a supporting domain composes a stage whose first effect belongs to the seller
- **THEN** core dispatches that role's entry without requiring a prior buyer deposit, confirmation or escrow proposal

### Requirement: Buyer dispatch preserves Agreement-only settlement

Core buyer settlement MUST select the composing domain's role-table entry using `Agreement.settlement.mechanism` and pass the accepted outcome unchanged. It MUST NOT choose a path from escrow-proposal presence, infer escrow terms, synthesize an obligation or select a replacement mechanism. A missing accepted entry MUST fail before settlement effects.

#### Scenario: Payments outcome has no escrow proposal

- **WHEN** an accepted Agreement selects Arkhai payments and its outcome contains no escrow proposal
- **THEN** the declared Arkhai buyer entry receives the exact accepted outcome

#### Scenario: Alkahest outcome contains its proposal

- **WHEN** an accepted Agreement selects Alkahest
- **THEN** its declared buyer entry reads the proposal from the outcome and core does not use that field to choose the entry

#### Scenario: Accepted mechanism has no stage

- **WHEN** accepted durable work names an unavailable role-table entry
- **THEN** settlement fails actionably before a mutation and never falls through to another mechanism

## ADDED Requirements

### Requirement: One settlement declaration per domain role

Each settlement-capable domain role MUST declare one immutable table from canonical mechanism ID to domain-owned stage. Core MUST require only the table and evidence carrier, not shared stage methods. Mechanism IDs MUST NOT select behavior elsewhere in domain orchestration; mechanism-owned input validation inside an entry remains permitted. Fresh admission MUST expose only supported entries.

#### Scenario: Role support differs

- **WHEN** a domain's seller supports several stages but its buyer supports one
- **THEN** each role exposes exactly its declared support and neither role inherits another role's stage or default

#### Scenario: Composition is incomplete

- **WHEN** a settlement-capable role supplies no valid table or duplicate/invalid entry identities
- **THEN** composition rejects it before publication, negotiation or settlement effects

### Requirement: Core evidence shape and domain payload ownership

SettlementEvidence MUST carry `negotiation_id`, `mechanism`, opaque `settlement_ref`, domain-defined `status` and domain-owned `evidence`. Core MUST preserve identities and validate shared shape without interpreting the payload, prescribing status transitions or treating a mechanism ID as delivery permission. Stages MUST keep credentials out of evidence.

#### Scenario: Evidence crosses the domain delivery boundary

- **WHEN** a selected stage hands evidence to delivery
- **THEN** the accepted negotiation and established reference remain unchanged and only the domain interprets its validated payload

#### Scenario: Buyer progress is not seller authorization

- **WHEN** a buyer reports local settlement completion but the seller has not verified authoritative evidence
- **THEN** seller protected delivery remains blocked

### Requirement: Mechanism continuation stays stage-owned

Mechanism-specific post-delivery attestation, claim binding, compensation and source-evidence revalidation MUST remain in the selected stage's continuation. Common delivery and restart runtimes MUST consume validated evidence and domain results without comparing mechanism IDs. Recovery MUST resolve the stage from accepted state, not current priority or serialized executable objects.

#### Scenario: Physical delivery needs an Alkahest attestation

- **WHEN** common physical delivery returns its result to an Alkahest stage
- **THEN** that stage handles its attestation and claim binding while the common delivery runtime recognizes no mechanism ID

#### Scenario: Receipt-backed work resumes

- **WHEN** a payment stage resumes delivery after restart
- **THEN** it revalidates its stored receipt before passing evidence to common recovery and reuses accepted operation identities
