## MODIFIED Requirements

### Requirement: Kit-owned capacity and publication lifecycle

The storefront-side multi-site capacity source, exact site projection,
capacity-event reconciliation loop, registry publication, durable publication
result recording, and close/reopen mechanics MUST be owned by one foundation
kit. A composing domain MUST contribute only schema-opaque publication
candidates, listing codecs, candidate reconciliation policy, and durable
binding lookup hooks. The kit MUST NOT import a concrete domain, provider, or
deployed service, and a composing domain MUST NOT retain a parallel capacity or
publication lifecycle.

Every publication candidate MUST carry one exact durable
`PublicationBinding(site_id, offering_mode, source_id, backing)`: trusted
`site_id`, pool-declared `offering_mode`, opaque domain-owned `source_id`, and the
backing delegate its pool's declared label selects. Every domain MUST build it from
the durable listing binding through the kit's one constructor, never from a
published payload. The public offer's mode MUST equal the binding's mode.
Reservation, commit, release, lease truncation, close, reopen, and restart recovery
MUST reload and compare the same binding and MUST NOT infer a home site, default an
offering mode, choose an authority from response data, or fan out after a binding
is recorded. Every storefront capacity effect MUST go through the kit's capacity
effects, whose guard is the binding's backing delegate, whether a domain composes the
kit's capacity runtime or its own aggregate capacity client.

#### Scenario: A domain publishes a capacity-backed candidate

- **WHEN** the domain derives a schema-valid candidate from a trusted site
  projection
- **THEN** the kit publishes it only after the domain hook confirms that its
  exact site, source, advertised offering mode, and backing equal durable local
  state

#### Scenario: An authenticated seller creates a capacity-backed listing

- **WHEN** the seller submits a schema-valid public offer with its exact
  trusted site and pool or Physical Resource source
- **THEN** the storefront verifies that the source identity, GPU quantity,
  configured site, and offering mode match the offer and atomically persists
  the listing and immutable binding before registry publication

#### Scenario: Seller source provenance disagrees with the offer

- **WHEN** the submitted site is unconfigured or the source pool, Physical
  Resource, GPU quantity, or offering mode differs from the public offer
- **THEN** listing creation fails before local listing persistence or registry
  publication

#### Scenario: Capacity changes after publication

- **WHEN** a configured site emits a consuming, releasing, or mixed-direction
  capacity delta
- **THEN** the kit obtains exact site-keyed projections, asks the domain hooks
  for the affected candidates, and executes deterministic close-before-reopen
  reconciliation over the listings whose backing is reconciled by availability

#### Scenario: Recovery loses an in-memory routing cache

- **WHEN** commit, release, or fulfillment resumes after restart
- **THEN** the effect is sent only to the site in the persisted binding, through
  the kit's capacity effects, and a missing or unconfigured binding fails closed
  without authority fan-out

#### Scenario: A pool cannot deliver the advertised mode

- **WHEN** a candidate's selected Resource Pool does not declare the candidate
  offering mode or its listing codec projects another mode
- **THEN** publication is rejected before registry or capacity effects

#### Scenario: Two bindings differ only in backing

- **WHEN** a supplied binding equals a persisted binding in site, mode, and source
  but carries a different backing
- **THEN** the two are unequal, and the kit refuses to publish, close, or reopen
  under the persisted binding
