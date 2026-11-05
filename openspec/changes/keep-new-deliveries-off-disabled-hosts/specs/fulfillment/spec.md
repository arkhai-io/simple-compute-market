## MODIFIED Requirements

### Requirement: Scheduling applies the pool provider's host requirement

Settlement scheduling SHALL treat a candidate as ineligible when the provider of
the candidate's pool needs a host and the candidate's capacity declaration has no
usable host: it names no host, or names one that does not take new delivery
because it is disabled or has no registration. Scheduling SHALL read the hosts
taking new delivery in its own transaction, and SHALL treat a provider identity
absent from the supplied requirement as needing a host. Exclusion SHALL apply to
every candidate, including the declaration backing the reservation being
scheduled, and SHALL occur before policy selection, capacity rebinding, cursor
advancement, or assignment. An explicit resource constraint naming such a
candidate SHALL be rejected as having no eligible resource, without invoking
policy or advancing cursors.

An existing assignment SHALL keep the host it was placed on and SHALL NOT be
re-placed, whether or not that host still takes new delivery; dispatch remains
the final check that an assignment's host is registered and, for a create,
enabled. An existing assignment that records no host, in a pool whose provider
needs one, SHALL be refused as having no eligible resource rather than returned;
it remains assigned until its reservation is released or expires, which abandons
it.

#### Scenario: Automatic selection encounters a candidate naming no host

- **GIVEN** eligible candidates in a pool whose provider needs a host, one of
  whose declarations names no host
- **WHEN** scheduling selects automatically
- **THEN** that candidate is never selected, and if no other candidate is
  eligible, scheduling reports no eligible resource without rebinding capacity,
  advancing the cursor, or creating an assignment

#### Scenario: Automatic selection encounters a candidate naming a disabled host

- **GIVEN** eligible candidates in a pool whose provider needs a host, one of
  whose declarations names a disabled host
- **WHEN** scheduling selects automatically
- **THEN** that candidate is never selected

#### Scenario: A hold's own backing lost its host after admission

- **GIVEN** a pool-scoped reservation held against a declaration whose host was
  disabled after the hold was admitted
- **AND** another declaration in an eligible pool can serve the reservation
- **WHEN** the reservation is scheduled
- **THEN** it is placed on the other declaration, its capacity rebound there

#### Scenario: An explicit constraint names a candidate that names no host

- **WHEN** a scheduling request constrains placement to a Physical Resource whose
  declaration names no host, in a pool whose provider needs one
- **THEN** scheduling rejects the request as having no eligible resource and no
  provider is invoked

#### Scenario: An explicit constraint names a candidate whose host has no registration

- **WHEN** a scheduling request constrains placement to a Physical Resource whose
  declaration names a host with no registered host record, in a pool whose
  provider needs one
- **THEN** scheduling rejects the request as having no eligible resource, without
  invoking policy or advancing cursors

#### Scenario: An existing assignment's host is disabled

- **GIVEN** an assignment placed on a host that has since been disabled
- **WHEN** an equivalent scheduling request is retried
- **THEN** the existing assignment is returned unchanged, and its create is
  refused at dispatch until the host is enabled

#### Scenario: An existing assignment records no host

- **GIVEN** an assignment, placed before placement refused declarations naming
  no host, that records no host in a pool whose provider needs one
- **WHEN** an equivalent scheduling request is retried
- **THEN** scheduling reports no eligible resource instead of returning the
  assignment
- **AND** the assignment remains assigned until its reservation ends

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
read in the caller's session. A lower layer receiving it SHALL NOT import the host
registry to obtain it.

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
  through the host authority is absent from it in the next transaction that reads
  it
