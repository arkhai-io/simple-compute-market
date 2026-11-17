## MODIFIED Requirements

### Requirement: A provider declares whether its delivery needs a host

Every registered fulfillment provider SHALL declare whether its delivery needs a
host. A provisioning composition SHALL collect those declarations, keyed by
provider identity, into one host requirement and SHALL supply that same
requirement to site admission and to settlement scheduling as plain data. A lower
layer receiving it SHALL NOT import a provider to obtain it. Composition SHALL refuse
to start when the supplied requirement does not name exactly its registered provider
identities, or when a registered provider declares differently from it.

A composition that supplies a host requirement and registers hosts SHALL also
supply the site authority, for admission and for its projections, and settlement
scheduling one report of the hosts taking new delivery: the identifiers of registered, enabled hosts,
less any host the composition withholds from new delivery, read in the caller's
session. The compute composition withholds every host placed in, or with a
declaration in, a pool referencing a disabled relay. A lower layer receiving the
report SHALL NOT import the host registry, or what the composition withholds by,
to obtain it.

#### Scenario: Composition collects every registered provider's declaration

- **WHEN** a provisioning composition registers its fulfillment providers
- **THEN** the host requirement it supplies names every registered provider
  identity with that provider's declaration

#### Scenario: The supplied requirement disagrees with a registered provider

- **WHEN** the requirement supplied to composition omits a registered provider, names
  an unregistered one, or states a different need than a registered provider declares
- **THEN** composition refuses to start

#### Scenario: A provider needs a host

- **WHEN** a provider's delivery connects to a host
- **THEN** it declares that it needs one

#### Scenario: The compute composition reports the hosts taking new delivery

- **WHEN** the compute provisioning composition is built
- **THEN** the site authority and settlement scheduling each receive the same
  report of hosts taking new delivery, and a host disabled
  through the host authority, or placed or declared in a pool whose relay is
  disabled, is absent from it in the next transaction that reads it
