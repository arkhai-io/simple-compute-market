## ADDED Requirements

### Requirement: Durable independent projection generations

A storefront MUST persist the last accepted complete resource-pool and capacity-bucket projection generations independently for each operator-configured site binding. Each stored generation MUST retain its authority-local revision, digest, freshness, and stale state; refresh failure MUST NOT replace it with an empty or partial value.

#### Scenario: Storefront restarts with cached projections

- **WHEN** a storefront restarts after accepting complete generations from several sites
- **THEN** it restores each family and site independently as stale until polling confirms or replaces that generation

#### Scenario: One projection family fails to refresh

- **WHEN** a resource-pool refresh fails while the capacity-bucket family advances
- **THEN** the storefront retains the previous resource-pool generation as stale and commits the capacity-bucket replacement independently

### Requirement: Publication-safe resource-pool metadata

The site resource-pool projection MUST include stable pool identity, enabled state, and allowlisted non-secret metadata required for commercial mapping and domain-owned publication hints. Credentials and provider secrets MUST NOT appear in the projection, and metadata changes MUST advance its revision and digest.

#### Scenario: Pool hint changes

- **WHEN** an operator changes a projected publication hint or enabled state
- **THEN** the next complete resource-pool projection has a new identity and contains no provider credential material
