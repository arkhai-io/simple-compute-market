## ADDED Requirements

### Requirement: A service refuses to start while a stored pool names an unserved provider

A service hosting the pool authority MUST refuse to start while any stored Resource
Pool names a provider no registered configuration handler serves, naming each such
pool and its provider and the providers that are registered. The check MUST run after
any pool document import, beside the refusal of stored pools whose declarations are
invalid. A running service therefore never holds a pool it cannot read, and no pool
read, export, or fulfillment fails for a missing handler.

#### Scenario: A stored pool's provider has no handler

- **WHEN** the provisioning service starts with a stored pool whose provider is not one
  its composition registers a handler for
- **THEN** it refuses to start, naming the pool, its provider, and the registered
  providers

#### Scenario: A disabled pool's provider has no handler

- **WHEN** the stored pool naming an unserved provider is disabled
- **THEN** startup is refused all the same, because its records are still read

## MODIFIED Requirements

### Requirement: Capacity backing is interpreted by one delegate

A pool's declared `capacity_backing` label MUST select one backing delegate, and every
decision that differs between backed and unbacked supply MUST be made by that delegate:
the pool declaration rules, admission of a capacity effect, hold placement, judging a
listing against availability, the scope of availability reconciliation, settlement
option admissibility, whether a listing carries its delivery terms, the backing an
older producer's pools resolve to, and the backing an admitted reservation implies. No
consumer MAY compare the label or test a binding's type to make one of these decisions.

The label MUST remain the value pool declarations, listing bindings, and the
resource-pool projection carry, and the value a published listing carries wherever its
market's registry schema publishes backing; no surface MAY carry a representation of
the delegate in its place. Whether a market's listings publish backing is its registry
schema's decision. A label with no delegate MUST be unresolvable, as an unrecognized
value is.

A listing's delivery terms are the fields that commit the marketplace to delivering
something, such as a host identity or access methods: a capacity-backed listing stands
behind them and nothing stands behind them on an unbacked one. A domain MUST name its
own delivery terms, and the delegate MUST decide whether they are carried through two
operations:

- carrying delivery terms, where a publication view or payload is built: the
  capacity-backed delegate passes the terms through and the unbacked delegate carries
  none of them;
- constraining delivery terms, where a model validates: the capacity-backed delegate
  requires every term present and non-empty and the unbacked delegate requires every
  term absent.

No delivery term MAY be given a default value, because a default would publish a
commitment nothing stands behind.

#### Scenario: A consumer decides by backing

- **WHEN** a storefront, a site, or a pool authority needs a decision that differs between backed and unbacked supply
- **THEN** it asks the delegate the pool's or binding's label selects, and holds no branch of its own on the label

#### Scenario: A label has no delegate

- **WHEN** a pool declaration or a durable binding carries a backing label no delegate is registered for
- **THEN** it is refused as unresolvable rather than read as either backing

#### Scenario: The label is carried unchanged

- **WHEN** a pool is projected, a listing is bound, or a listing is published under a registry schema that carries backing
- **THEN** each carries the declared `capacity_backing` label, not a representation of the delegate

#### Scenario: An unbacked view is built

- **WHEN** a domain builds a publication view for a resource in an unbacked pool and
  passes its delivery terms to the pool's backing delegate
- **THEN** the view carries none of those terms, whatever the declaration names

#### Scenario: A backed listing is validated without its terms

- **WHEN** a capacity-backed listing or view omits one of its domain's delivery terms, or
  carries it empty
- **THEN** its validation refuses it

#### Scenario: An unbacked listing is validated with a term

- **WHEN** an unbacked listing or view carries one of its domain's delivery terms
- **THEN** its validation refuses it
