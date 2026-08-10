## ADDED Requirements

### Requirement: Service calls are authenticated by counterparty signature

A provisioning authority MUST authenticate an inbound service call by verifying a
signature against a registered counterparty identity, and MUST sign its own outbound
calls with material no counterparty holds. Authentication material that both
authenticates a caller and signs that authority's own outbound calls MUST NOT be used,
so that compromising one party cannot let it sign as another. Verification MUST bound
replay, and MUST NOT require a network call to an external service.

#### Scenario: An inbound service call is authenticated

- **WHEN** a storefront calls a provisioning authority
- **THEN** the authority verifies the request signature against the storefront's
  registered identity, rather than comparing a shared secret

#### Scenario: A counterparty is compromised

- **WHEN** a storefront's credentials are compromised
- **THEN** the attacker cannot sign calls that appear to originate from the authority,
  because the authority's signing material was never shared

#### Scenario: A signed request is replayed

- **WHEN** a previously valid signed request is replayed outside the accepted freshness
  bound
- **THEN** it is rejected

#### Scenario: Verification runs without external dependencies

- **WHEN** a signature is verified
- **THEN** verification completes locally, without a call to a chain node or other
  external service

### Requirement: Counterparty identities rotate without coordinated downtime

A verifying service MUST accept more than one valid identity for a counterparty at a
time, so a counterparty's signing material can be introduced, adopted, and retired as
independent steps rather than a simultaneous change on both sides.

#### Scenario: A counterparty rotates its signing material

- **WHEN** a counterparty introduces new signing material while its previous material is
  still in use
- **THEN** calls signed with either are accepted until the previous identity is retired

#### Scenario: A retired identity is used

- **WHEN** a counterparty signs with material that has been retired
- **THEN** the call is rejected
