## ADDED Requirements

### Requirement: Capacity backing is interpreted by one delegate

A pool's declared `capacity_backing` label MUST select one backing delegate, and every
decision that differs between backed and unbacked supply MUST be made by that delegate:
the pool declaration rules, admission of a capacity effect, hold placement, judging a
listing against availability, the scope of availability reconciliation, settlement
option admissibility, the backing an older producer's pools resolve to, and the
backing an admitted reservation implies. No consumer MAY compare the label or test a
binding's type to make one of these decisions.

The label MUST remain the value pool declarations, listing bindings, the resource-pool
projection, and published listings carry. A label with no delegate MUST be
unresolvable, as an unrecognized value is.

#### Scenario: A consumer decides by backing

- **WHEN** a storefront, a site, or a pool authority needs a decision that differs between backed and unbacked supply
- **THEN** it asks the delegate the pool's or binding's label selects, and holds no branch of its own on the label

#### Scenario: A label has no delegate

- **WHEN** a pool declaration or a durable binding carries a backing label no delegate is registered for
- **THEN** it is refused as unresolvable rather than read as either backing

#### Scenario: The label is carried unchanged

- **WHEN** a pool is projected, a listing is bound, or a listing is published
- **THEN** each carries the declared `capacity_backing` label, not a representation of the delegate

## MODIFIED Requirements

### Requirement: Shared resolution of advertisement and backing declarations

The shared resource-pool capability MUST expose one domain-neutral resolver that
turns a pool's policy tags into typed advertisable modes and the backing delegate the
pool's `capacity_backing` label selects, sharing its implementation with write-side
validation. It MUST fail rather than resolve to a default for a malformed value of
either tag, a backed pool whose advertisable set exceeds its deliverable set, and an
unbacked pool with a non-empty deliverable set. It MUST report an absent tag
distinctly from a malformed one, so a consumer can apply a producer-version rule to a
producer that emits a tag for no pool while failing a single omitting pool closed.

Any reader of projected pool declarations MUST resolve them through this resolver,
so the site that writes a declaration and every consumer that reads it agree on
what a valid declaration is.

#### Scenario: A projected backed pool advertises beyond what it delivers

- **WHEN** the resolver receives policy tags declaring `capacity_backing: backed` with an advertisable set exceeding the deliverable set
- **THEN** it fails for that pool rather than returning either set

#### Scenario: A projected backing value is malformed

- **WHEN** the resolver receives a `capacity_backing` value outside `backed` and `unbacked`
- **THEN** it fails for that pool rather than resolving to either value

#### Scenario: A projected pool omits a declaration

- **WHEN** the resolver receives policy tags carrying neither `advertisable_modes` nor `capacity_backing`
- **THEN** it reports each tag as absent, distinctly from malformed, and returns no default

#### Scenario: A projected pool resolves

- **WHEN** the resolver receives valid declarations
- **THEN** it returns the advertisable modes and the backing delegate the declared label selects
