## ADDED Requirements

### Requirement: Kit-owned single settlement runtime

The mechanism-neutral commercial-settlement lifecycle MUST live in a foundation kit and
MUST be composed by role/domain roots. It MUST use one stable per-obligation identity and
one operation journal for materialization, authoritative status reconciliation, condition
checking, collection, expired reclaim, retries, and uncertain acknowledgements. A domain
MUST supply accepted-plan semantics, fulfillment, configuration, status projection, and
real failure actions; a mechanism kit MUST supply the conditional-escrow adapter. Neither
core carrier packages nor the runtime kit may import a concrete domain or deployed
service.

#### Scenario: A domain settles a deal

- **WHEN** a composing domain accepts and fulfills a settlement obligation
- **THEN** lifecycle transitions and idempotency come from the shared runtime, while the
  domain supplies only its plan, fulfillment, projection, configuration, and actions

#### Scenario: A second settlement mechanism is installed

- **WHEN** a composition registers another conditional-escrow adapter
- **THEN** it uses the same obligation records, operation leases, worker, and aggregate
  status rather than introducing a mechanism-specific lifecycle

#### Scenario: Settlement is interrupted and resumed

- **WHEN** a process stops after an operation is reserved or its acknowledgement is
  uncertain
- **THEN** recovery reloads the exact obligation and stable operation identity and
  reconciles or retries without guessing an obligation or duplicating a financial effect

#### Scenario: A domain has no fulfillment authority

- **WHEN** a domain can verify settlement but cannot produce a real immutable fulfillment
  reference
- **THEN** composition exposes that verified-only boundary and does not install a no-op
  executor, synthetic fulfillment, or collectable claim

### Requirement: No parallel settlement lifecycle

A production composition MUST NOT retain an escrow-UID claim engine, dual-write claim
projection, domain-local settlement orchestration copy, or compatibility alias that can
advance the same obligation outside the shared runtime.

#### Scenario: Legacy claim state is migrated

- **WHEN** existing claim rows are converted into stable obligation records
- **THEN** every immutable snapshot is validated before one atomic conversion, conflicts
  roll back the conversion, and subsequent writes use only the shared runtime

#### Scenario: Domain compensation differs

- **WHEN** VM provisioning, API-credit issuance, or another domain effect fails
- **THEN** the shared ordered dispatcher invokes that domain's registered real actions at
  the existing side-effect boundary and does not interpret domain payloads or invent a
  generic money-movement action
