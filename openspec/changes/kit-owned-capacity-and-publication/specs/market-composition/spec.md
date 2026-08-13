## ADDED Requirements

### Requirement: Kit-owned capacity client and publication runtime

The storefront-side capacity client and the listing publication runtime MUST live in the
kit layer and be composed by a market domain. A domain MUST supply its claim
construction, its listing derivation, its registry schema identity, and its
configuration, and MUST NOT reimplement the client's reserve, commit, and release
handling or the publication runtime's reconciliation. Every domain implementing either
MUST be composed onto the kit implementation, and a domain that lacked one MUST gain it
by composition.

#### Scenario: A domain reserves capacity

- **WHEN** a market domain reserves, commits, or releases capacity at a site authority
- **THEN** it uses the kit-owned client, supplying its own claim construction and
  configuration

#### Scenario: A domain publishes listings

- **WHEN** a market domain publishes listings to a registry
- **THEN** the publication runtime is the kit implementation, with the domain supplying
  listing derivation and schema identity

#### Scenario: A domain has neither

- **WHEN** a domain without its own capacity client or publication runtime is composed
- **THEN** it can reserve capacity and publish listings through the kit implementations

#### Scenario: Domain-specific capacity behavior is required

- **WHEN** a domain's capacity handling differs in control flow rather than in claim
  construction or configuration
- **THEN** that behavior stays domain-owned rather than being generalized into kit
