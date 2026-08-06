## ADDED Requirements

### Requirement: Cross-cutting storefront runtime is kit-owned

Storefront functionality that differs between market domains only in which domain codecs
it invokes and which configuration values it reads MUST live in the kit layer and be
composed by a domain, not reimplemented in the domain layer. A domain MUST supply its
contract, its configuration, and its domain-specific semantics to that runtime, and MUST
NOT reimplement its control flow, persistence interaction, retry behavior, or lifecycle.
Kit-owned storefront runtime MUST depend downward only and MUST NOT depend on a domain
package or a deployed service.

#### Scenario: Two domains need the same storefront mechanism

- **WHEN** two market domains require a storefront mechanism that differs only in codecs
  and configuration
- **THEN** the mechanism lives in kit and each domain composes it

#### Scenario: A mechanism differs in control flow between domains

- **WHEN** two domains' implementations of a concern differ in control flow rather than
  only in codecs and configuration
- **THEN** the differing behavior stays domain-owned, or the divergence is resolved
  deliberately with the chosen behavior recorded

#### Scenario: A new domain needs storefront runtime

- **WHEN** a market domain is added
- **THEN** it obtains the cross-cutting storefront runtime by composition, without
  reimplementing it

#### Scenario: Kit runtime reaches for a domain

- **WHEN** kit-owned storefront runtime would need a domain package or deployed service
- **THEN** the dependency is inverted through what the domain supplies at composition,
  rather than imported

### Requirement: An extracted concern leaves no domain-local implementation

When a storefront concern moves into the kit layer, every domain that implemented it
MUST be composed onto the kit implementation within the same change, and every
domain-local implementation of it MUST be removed. A domain that did not implement the
concern MUST gain it by composition.

#### Scenario: A concern is extracted

- **WHEN** a concern moves into kit
- **THEN** no domain retains its own implementation of that concern

#### Scenario: A domain lacked the concern

- **WHEN** a domain had no implementation of a concern being extracted
- **THEN** it obtains the concern by composing the kit implementation

#### Scenario: Extraction would leave one domain behind

- **WHEN** extracting a concern for one domain would leave another domain on its own
  implementation
- **THEN** the extraction is not complete, since the number of implementations has grown
  rather than shrunk
