## ADDED Requirements

### Requirement: Principal-bound settlement evidence and authority

Settlement plans, accepted fulfillment references, heartbeats, start/status/reclaim requests, claims, and operation-journal authorization MUST bind payer, claimant, storefront, and service actors as canonical scheme-tagged principals. Matching a bare address, identifier, hosted account reference, or provider identifier MUST NOT grant settlement authority.

#### Scenario: Heartbeat uses the wrong scheme

- **WHEN** a heartbeat identifier matches the recorded buyer text but its principal scheme differs
- **THEN** the storefront rejects the heartbeat and does not update evidence or reclaim timing

#### Scenario: Hosted buyer reclaims without a wallet

- **WHEN** an authorized Ed25519 payer requests reclaim after the hosted obligation becomes eligible
- **THEN** the mechanism-neutral runtime and hosted client submit the stable operation without resolving wallet or chain settings

### Requirement: Chain credentials are mechanism-scoped

A settlement adapter MAY require an EVM address, wallet, RPC endpoint, chain ID, or deployed contract only for an obligation whose selected mechanism or condition performs that EVM effect. Generic settlement carriers and hosted non-EVM obligations MUST NOT require or infer those values from marketplace principals.

#### Scenario: Hosted condition is non-EVM

- **WHEN** a `fiat.stripe.v1` obligation uses an admitted built-in or signed non-EVM condition
- **THEN** materialization, check, collect, reclaim, and reconciliation run with no EVM credential or RPC dependency

#### Scenario: EAS condition is selected

- **WHEN** a hosted or Alkahest obligation selects a condition whose contract requires an EVM subject or transaction
- **THEN** the owning adapter validates the explicitly tagged EVM input without reinterpreting an Ed25519 principal

### Requirement: Hosted client owns hosted identity wire

The hosted settlement adapter MUST pass an injected marketplace signer through the exact manifest-pinned hosted client identity interface and MUST NOT duplicate hosted canonicalization, headers, scheme implementations, response verification, account-link behavior, or provider models.

#### Scenario: Hosted release lacks the required identity capability

- **WHEN** storefront startup or publication preflight sees a hosted manifest that does not advertise the configured principal scheme and contract version
- **THEN** hosted settlement remains unavailable and no fiat option is published
