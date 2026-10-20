## ADDED Requirements

### Requirement: An Alkahest section that cannot settle makes Alkahest unready

A configured `[Settlement.alkahest]` section that parses but under which no deal could be
settled MUST make the Alkahest mechanism unready, with a configuration blocker naming the
setting, and MUST NOT stop the storefront, whether or not the section is enabled. That
covers an oracle-gated section with no trusted oracle; a trusted or interruptible oracle
equal to the seller wallet; an interruptible section with no interruptible oracle; a
missing seller wallet address, whatever clients the storefront composes; and a release
model the storefront's domain cannot deliver. A release condition MUST NOT fall back to
the seller wallet as its oracle. A section that does not parse MUST stop startup, as any
configuration does.

#### Scenario: An oracle-gated section names no oracle

- **WHEN** a storefront starts with an oracle-gated Alkahest section that lists no trusted
  oracle
- **THEN** it starts, Alkahest is unready with a configuration blocker naming the missing
  oracle, and its other mechanisms publish

#### Scenario: The oracle is the seller's own wallet

- **WHEN** a storefront's Alkahest section names the seller wallet as its trusted oracle
- **THEN** Alkahest is unready with a configuration blocker, and no candidate is refused
  per cycle for it

#### Scenario: The seller wallet has no address

- **WHEN** a VM or API-credit storefront composes Alkahest clients but its seller wallet
  has no address
- **THEN** Alkahest is unready with a configuration blocker, and no listing advertises a
  release condition with no recipient

### Requirement: Readiness blockers state their kind

Every mechanism's readiness blocker MUST state whether it is a configuration blocker,
which the storefront's own configuration causes and only an operator can clear, or a
reachability blocker, raised because a dependency the mechanism needs — a chain, a
service, a contract probe — could not be reached to determine readiness. Each
mechanism's preflight MUST set the kind on every blocker it reports, and status MUST
report it.

#### Scenario: A chain cannot be reached

- **WHEN** Alkahest's contract probe cannot reach its chain
- **THEN** its blocker is a reachability blocker

#### Scenario: A wallet is missing

- **WHEN** Alkahest's seller wallet has no address
- **THEN** its blocker is a configuration blocker
