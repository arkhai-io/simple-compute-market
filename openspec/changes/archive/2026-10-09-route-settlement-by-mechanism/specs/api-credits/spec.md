## MODIFIED Requirements

### Requirement: Idempotent credit issuance

The credits service MUST own API-key hashes, balances, grants and consumption records. A new key MUST be derived through issuance, store only a hash of its bearer secret and bind the canonical owner. A grant MUST be unique by deterministic fulfillment identity derived uniformly from negotiation ID; exact issuance retries MUST NOT grant or reserve quota twice. An unused new-key retry MAY rotate its secret; a retry after use MUST NOT reveal one.

#### Scenario: Issuance is retried

- **WHEN** the same deterministic fulfillment identity and immutable authorization are issued more than once
- **THEN** balance and quota change only once while any replacement secret follows the unused-key rule

### Requirement: Verified settlement fulfillment

The storefront MUST authorize issuance only after its selected settlement stage produces verified SettlementEvidence. Pending progress MUST authorize no grant. Successful delivery MUST persist fulfillment identity and private buyer credentials; public results MUST omit bearer secrets. If a stage's downstream attestation fails after issuance, that stage MUST attempt compensating balance adjustment and revoke a key newly created by the failed operation.

#### Scenario: Settlement evidence is invalid

- **WHEN** accepted escrow or payment evidence fails its stage's verification
- **THEN** the storefront authorizes no issuance and creates no credit grant

#### Scenario: New-key issuance succeeds

- **WHEN** verified settlement produces a successful issuance job
- **THEN** the storefront persists credentials for buyer retrieval and exposes a secret-free public fulfillment result

#### Scenario: Attestation fails after issuance

- **WHEN** the selected Alkahest stage fails its post-issuance on-chain fulfillment
- **THEN** its continuation attempts balance compensation and new-key revocation without making common issuance compare mechanism IDs

### Requirement: Payment grants are principal-bound and exact once

The accepted Agreement MUST bind service, positive quantity, key mode and optional key ID, canonical parties, amount, asset and selected policy. The storefront's stage MUST verify authoritative settlement evidence before creating an immutable issuance authorization. The credits authority MUST key grants by negotiation-derived fulfillment identity and reject changed reuse against its request digest without recognizing settlement mechanisms. Key ownership, balance and quota remain authority-owned.

#### Scenario: Issuance acknowledgement is lost

- **WHEN** the authority commits a grant but the storefront did not record its response
- **THEN** retry retrieves or resumes the same grant without creating another key or increasing balance again

#### Scenario: Existing key belongs to another principal

- **WHEN** a top-up targets a key owned by a different canonical principal
- **THEN** the authority rejects issuance without changing quota or balance

### Requirement: Payment progress and credentials remain separate

The storefront MUST re-drive nonterminal issuance using accepted negotiation, verified evidence and deterministic grant identity. Public progress MUST omit bearer secrets; credentials MUST use authenticated private results. Pending or unverified settlement MUST authorize no issuance. Progress and re-drive MUST read evidence and domain state rather than compare mechanism IDs or treat an escrow-shaped row as authorization.

#### Scenario: Buyer retries provisioning state

- **WHEN** seller state is nonterminal after verified settlement
- **THEN** settlement resumes or retrieves the same issuance instead of returning pending forever

## ADDED Requirements

### Requirement: API-credit role tables own settlement dispatch

The API-credit buyer and seller MUST each compose one supported-mechanism table. Buy, standalone negotiation (including `--from`), accepted-run settlement, seller acceptance hooks and seller settlement MUST use the corresponding entry. Mechanism-specific option, mandate, expiry and post-issuance behavior MUST stay inside entries rather than controllers, negotiation orchestration or common credit issuance.

#### Scenario: Both payment and Alkahest are supported

- **WHEN** accepted API-credit Agreements select either supported mechanism
- **THEN** the same role declaration selects its stage and common issuance receives verified evidence without a mechanism switch

#### Scenario: Payment-only standalone negotiation

- **WHEN** `market credits negotiate` selects an advertised payment option
- **THEN** its buyer entry supplies the payer account and unscaled payment prices without requiring wallet, chain or token inputs
- **AND** the run retains exact Agreement bytes and settlement data for accepted-run settlement

#### Scenario: Standalone negotiation resumes

- **WHEN** an interrupted round loop resumes after fresh mechanism admission changes
- **THEN** it retains the recorded selection, provision terms and scaled opening/ceiling without reselecting a mechanism or scaling prices again

### Requirement: Credits service consumes issuance authorization only

The credits service MUST receive the storefront's existing authenticated immutable issuance command, not raw settlement evidence, a mechanism ID or an escrow reference. The command MUST bind negotiation-derived fulfillment identity, canonical owner, service, quota resource, quantity, key target and request digest. The service MUST validate identity/digest and repeat authoritative quota and key checks before granting.

#### Scenario: A new settlement mechanism authorizes the same purchase

- **WHEN** its storefront stage produces verified evidence and constructs a valid authorized issuance command
- **THEN** the credits service commits the grant without importing that mechanism, parsing its evidence or updating a mechanism allowlist

#### Scenario: Authorization is changed on replay

- **WHEN** an existing fulfillment identity is reused with changed owner, service, resource, quantity or key target
- **THEN** the authority rejects the conflict before key, balance or quota mutation

#### Scenario: Operational quota hold changes

- **WHEN** an expired negotiation hold is replaced while the immutable authorization intent is unchanged
- **THEN** issuance rechecks authoritative capacity and retains the same grant identity and intent digest

### Requirement: API-credit settlement evidence has independent persistence

The storefront MUST persist accepted-Agreement-bound SettlementEvidence and negotiation-scoped issuance progress independently of escrow rows, signed issuance evidence and private credentials. Mechanism, Agreement digest and an established reference MUST be conflict-protected; verified status and source/delivery payload MUST NOT be downgraded or replaced. Incompatible evidence/grant schemas MUST require explicit database reset; startup MUST NOT adopt old grants or translate old issuance payloads.

#### Scenario: Pending evidence exists

- **WHEN** a pending settlement record exists without verified authoritative source evidence
- **THEN** it authorizes no grant and its progress remains retryable without creating a payment escrow

#### Scenario: A verified grant is published as issuance evidence

- **WHEN** delivery produces signed issuance evidence for an Alkahest condition
- **THEN** it is stored separately from the pre-issuance settlement gate and contains no bearer secret

#### Scenario: A fresh credits schema is created

- **WHEN** the introducing storefront and service migrations bootstrap empty databases
- **THEN** evidence/progress and negotiation-derived grant identities exist without copying legacy escrow/grant populations

#### Scenario: Verified receipt recovery survives unavailable polling

- **WHEN** a payment grant acknowledgement is lost after verified evidence was persisted and payment polling is unavailable
- **THEN** the stage revalidates the stored signed receipt and resumes the same issuance without replacing verified evidence with pending state

#### Scenario: Prepared Alkahest delivery is issued

- **WHEN** preparation has verified the authoritative escrow and saved matching delivery facts
- **THEN** delivery consumes those facts without a second preparation inside terminal failure handling
