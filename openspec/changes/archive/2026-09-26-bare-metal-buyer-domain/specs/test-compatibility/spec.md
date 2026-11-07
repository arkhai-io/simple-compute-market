## ADDED Requirements

### Requirement: Bare-metal buyer passes shared and domain-focused conformance

The bare-metal buyer MUST pass the shared buyer-domain conformance suite for contract identity/version, identity injection, command registration, provision-term construction, policy composition, result decoding, and package boundaries. Domain-focused tests MUST cover exact demand validation, listing/terms/resource binding, settlement selection, transcript/run recovery, transient actions, strict result/evidence decoding, separate access retrieval, teardown idempotency, and secret redaction using authenticated producer-contract fixtures rather than seller/provisioner implementation imports.

#### Scenario: Shared buyer contract changes

- **WHEN** the core domain contract or resolved-identity injection contract changes
- **THEN** the bare-metal plugin runs the same conformance case as every shipped buyer domain and fails until its declared contract and hooks agree

#### Scenario: Loose result payload is returned

- **WHEN** a fixture adds an unknown `details`, provider, credential, access endpoint, or raw executor field to public bare-metal result/evidence
- **THEN** consumer tests prove strict decoding rejects it and no diagnostic or snapshot captures the value

#### Scenario: Direct implementation dependency is introduced

- **WHEN** runtime or type-only import checks find a seller, site, fulfillment/provisioning implementation, sibling buyer, provider SDK, e2e helper, or test package in the wheel dependency graph
- **THEN** the package-boundary suite fails

### Requirement: Recovery matrix proves exact profile, agreement, and operation reuse

Deterministic integration coverage MUST interrupt every durable boundary after discovery, negotiation creation, seller acceptance, settlement operation reservation, materialization acknowledgement uncertainty, transient action, funded/escrowed state, lease readiness, access retrieval, and teardown acceptance. On restart, the buyer MUST reuse the recorded profile/principal, authority, negotiation/agreement, settlement option/obligation, fulfillment/access reference, and teardown operation and MUST not duplicate negotiation, payment, fulfillment, access grant, collection, or teardown.

#### Scenario: Process stops after settlement commit

- **WHEN** the settlement authority committed the recorded operation but the buyer did not receive its response
- **THEN** resume retrieves the same operation and continues without a second obligation or mechanism selection

#### Scenario: Process stops after teardown acceptance

- **WHEN** teardown was accepted before the response was lost
- **THEN** recovery observes or resumes the same teardown and later proves authoritative access revocation

#### Scenario: Profile rotates before restart

- **WHEN** the selected buyer profile rotates after an interrupted run
- **THEN** the matrix proves recovery uses the retained run-recorded principal while fresh work uses the replacement primary

### Requirement: Installed-artifact end-to-end evidence uses real whole-host effects

Release qualification MUST install only staged wheels and ordinary deployment artifacts, discover the bare-metal plugin through entry-point metadata, and complete a buyer-to-runnable-storefront flow using authoritative selected-site fulfillment. It MUST observe successful SSH access using the buyer-owned private key, verify the host and agreement bindings, request or await teardown through the storefront, then observe access revocation and authoritative capacity/lease teardown. A success flag, pre-seeded result, no-op provisioner, injected lifecycle port, direct database mutation, unsigned response, hard-coded site/resource, or direct provisioner call MUST NOT satisfy the scenario.

#### Scenario: Hosted-only whole-host purchase

- **WHEN** an Ed25519 buyer with no wallet or chain configuration selects an advertised hosted option, completes any transient action, and funding becomes authoritative
- **THEN** the ordinary installed CLI reaches real lease-ready evidence, retrieves authenticated SSH connection data, accesses the selected whole host, and later observes teardown/revocation without provider data or credentials entering portable evidence

#### Scenario: Alkahest regression

- **WHEN** the same plugin selects an Alkahest alternative under explicit wallet/chain configuration
- **THEN** discovery, exact negotiation, settlement, access, recovery, and teardown remain functional through the same domain/lifecycle contracts

#### Scenario: Credential isolation is inspected

- **WHEN** run JSONL, profile metadata, TOML, generated deployment state, logs, diagnostics, public evidence, staged wheels, and release artifacts are scanned after the E2E flow
- **THEN** none contains marketplace seeds, SSH private material, wallet keys, passwords, bearer tokens, action URLs, hosted/provider data, or raw access responses

### Requirement: Prerequisite evidence fails closed

Before buyer implementation or E2E acceptance, a prerequisite check MUST identify the permanent requirement/architecture heading, installed distribution/API version, focused producer test, and integration evidence for each required identity, domain-routing, seller, fulfillment/result/access/teardown, and settlement seam. Any missing or contradictory column MUST block dependent work and MUST NOT be replaced by a mock or active-change completion claim.

#### Scenario: Active task is checked but permanent contract is absent

- **WHEN** a prerequisite change reports completion but its behavior is absent from permanent documentation or installed-artifact evidence
- **THEN** the buyer prerequisite check remains failed and the dependent implementation/E2E task does not proceed
