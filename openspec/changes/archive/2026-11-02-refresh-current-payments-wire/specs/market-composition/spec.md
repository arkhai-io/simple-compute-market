## MODIFIED Requirements

### Requirement: Arkhai payments authority remains external

`kit/arkhai-payments` MUST consume the payments service's published HTTP and JSON Schema contract, vendored with its conformance vectors and identified by content hash rather than by source location, and generate its Python wire models from it, rather than importing the service implementation or copying a TypeScript contract. The payments service MUST remain the authority for its ledger, account credentials, fees, hold release, dispute attachment, and payment-provider operations.

#### Scenario: Payments service owns the ledger

- **WHEN** a marketplace domain composes `arkhai.payments.v1`
- **THEN** it uses the external payments API and signed receipt as authority and keeps no local ledger, payment-provider integration, or settlement daemon

#### Scenario: Published payment snapshots contain an effective end or zero gross

- **WHEN** the selected published contract permits an effective part end or a zero gross amount in a payment snapshot or receipt
- **THEN** the generated consumer accepts those fields and values without accepting unknown fields or weakening unrelated constraints

#### Scenario: A contract publication is refreshed

- **WHEN** the payment consumer selects a newer standalone JSON Schema and producer conformance vectors
- **THEN** it records their content hashes, regenerates reproducible strict models, verifies current producer signatures and transaction identities, and preserves historical raw signed-byte verification separately

#### Scenario: Nullable required values remain distinct from optional omissions

- **WHEN** a published mandate includes a required nullable duration or an omitted optional end
- **THEN** serialization retains the required null and omits an unset optional end consistently for the approval body, canonical transaction identity and receipt verification
