## ADDED Requirements

### Requirement: The site authority reads pool facts through an injected port

A site authority SHALL obtain every Resource Pool fact it decides on — whether the pool
exists, whether it is enabled, the offering modes it delivers, and whether its
declarations need a host — through a pool-facts reader its composition root supplies,
and SHALL NOT read the pool authority's persistence or import the pool capability. The
reader SHALL be required: no site authority is constructed without one. Every read SHALL
take the session of the transaction making the decision, so a decision is judged against
the pool state that transaction sees.

The port's values SHALL be structural, so a reader satisfies it without importing the
site authority. A pool the reader does not find SHALL be reported as not existing, not
enabled, with unreadable deliverable modes, and as needing a host exactly when its
composition supplies a host requirement.

#### Scenario: Admission reads pool facts in its own transaction

- **WHEN** a claim is reserved against a declaration in a pool
- **THEN** the pool's enablement, deliverable modes, and host need are read through the
  composition's reader in the session that creates the reservation

#### Scenario: Registration names a pool the reader does not find

- **WHEN** a capacity registration names a pool the reader reports as not existing
- **THEN** the registration is refused and no declaration is written or changed

#### Scenario: The offered read meets a pool the reader does not find

- **GIVEN** a composition supplying a host requirement
- **WHEN** the offered read reaches a declaration whose pool the reader reports as not
  existing
- **THEN** the declaration is judged as one in a backed pool whose provider needs a
  host: it is offered enabled only when it has a usable host, as admission judges it

#### Scenario: The site authority is installed without the pool capability

- **WHEN** the site authority's package is inspected
- **THEN** it neither imports nor declares the pool authority or its contracts
  distribution
