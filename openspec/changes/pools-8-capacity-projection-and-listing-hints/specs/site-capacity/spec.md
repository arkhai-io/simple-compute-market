## ADDED Requirements

### Requirement: Per-site projection load-state visibility

A storefront MUST report, per configured site and per independent projection family (resource-pool, capacity-bucket), whether that projection has ever successfully loaded, is currently loaded, is stale, or is unavailable. This state MUST be visible on the storefront's existing operator status surface. A storefront MUST NOT persist projection generations durably across restart; retry-until-success plus this observable status is the accepted mechanism for a site being unreachable at storefront startup.

#### Scenario: A configured site is unreachable at storefront startup

- **WHEN** the storefront starts and one configured site's projection load has not yet succeeded
- **THEN** operator status reports that site/family as not-yet-loaded rather than presenting an empty projection as authoritative, and the storefront continues retrying without blocking readiness for other configured sites

#### Scenario: One projection family fails to refresh after a successful load

- **WHEN** a resource-pool refresh fails while the capacity-bucket family advances
- **THEN** the storefront retains the previous resource-pool generation in memory as stale, reports that state on the status surface, and commits the capacity-bucket replacement independently

### Requirement: Publication-safe resource-pool metadata

The site resource-pool projection MUST include stable pool identity, enabled state, and allowlisted non-secret metadata required for commercial mapping and domain-owned publication hints. Credentials and provider secrets MUST NOT appear in the projection, and metadata changes MUST advance its revision and digest.

#### Scenario: Pool hint changes

- **WHEN** an operator changes a projected publication hint or enabled state
- **THEN** the next complete resource-pool projection has a new identity and contains no provider credential material
