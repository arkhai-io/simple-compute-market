## ADDED Requirements

### Requirement: Kit-owned storefront authentication and domain-only persistence

Storefront request authentication — seller, administrator, buyer, service-peer, and
signed responses — MUST be one core- or kit-owned middleware set applied by the
shell, and a domain MUST NOT carry authentication middleware of its own. Market
state MUST be persisted by core; a domain's persistence MUST hold only the tables its
contract introduces and MUST NOT reimplement access to core-owned market state.

#### Scenario: A request reaches any domain's route

- **WHEN** a seller, administrator, buyer, or service peer calls a storefront route
- **THEN** the shared middleware set authenticates it identically in every domain,
  with the principals taken from the storefront's configuration

#### Scenario: A domain persists state

- **WHEN** a domain's contribution writes state
- **THEN** market state goes through core's client and only the domain's own tables
  go through the domain's
