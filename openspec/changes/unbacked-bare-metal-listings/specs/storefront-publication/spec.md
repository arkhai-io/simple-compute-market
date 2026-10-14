## ADDED Requirements

### Requirement: Bare-metal publication derives unbacked listings

Bare-metal publication MUST derive a listing from every enabled Physical Resource
that enables bare-metal publication in an enabled pool advertising `bare_metal`,
whatever the pool's backing, and bind it with the backing its pool declares. An
unbacked candidate MUST come from the site's bare-metal view of the resource, MUST
NOT be judged against availability, and MUST follow the region, asking-rate,
override, and shape rules every bare-metal candidate follows. An unbacked
bare-metal listing MUST never be reserved, held, scheduled, or fulfilled.

#### Scenario: An unbacked pool advertises bare metal

- **WHEN** a pool advertising `bare_metal` declares itself unbacked, and one of its
  enabled Physical Resources enables bare-metal publication with no host named
- **THEN** bare-metal publication derives a listing for that resource and publishes it
  with `capacity_backing: unbacked`

#### Scenario: A resource in an unbacked pool does not opt in

- **WHEN** a Physical Resource in an unbacked pool advertising `bare_metal` does not
  enable bare-metal publication
- **THEN** no bare-metal listing is derived from it

#### Scenario: An unbacked resource's capacity is consumed

- **WHEN** availability for an unbacked resource's capacity reads as consumed
- **THEN** its listing stays open, because an unbacked listing is not judged against
  availability

#### Scenario: An unbacked bare-metal listing is accepted

- **WHEN** a negotiation against an unbacked bare-metal listing is accepted
- **THEN** no capacity is reserved and the deal settles by introduction, revealing the
  contact of the listing's origin seller

### Requirement: A bare-metal listing carries delivery terms only when backed

A bare-metal listing's delivery terms — its host identity, physical host identity,
and access methods — MUST be present and non-empty when the listing is capacity-backed
and absent when it is unbacked, as its backing delegate decides. An unbacked listing
MUST NOT publish a host or access methods even where its declaration names them, and
no delivery term MUST be published by default.

#### Scenario: An unbacked declaration names a host

- **WHEN** a Physical Resource in an unbacked pool names a host and declares access
  methods
- **THEN** its listing publishes neither the host identity nor the access methods

#### Scenario: A backed listing omits its host

- **WHEN** a capacity-backed bare-metal listing would be published without a host
  identity or access methods
- **THEN** the listing is refused rather than published

### Requirement: A bare-metal candidate with no settlement option yields no listing

Bare-metal publication MUST refuse a candidate, whatever its backing, whose payload
carries no settlement option and no accepted escrow, and MUST record a `refuse`
entry in the publication report naming the candidate and the readiness blockers.

#### Scenario: An unbacked candidate's origin has no contact

- **WHEN** an unbacked candidate's only admissible mechanism is contact exchange and its
  origin site has no configured contact
- **THEN** no listing is derived and the publication report records a refusal naming
  the candidate

#### Scenario: No backed mechanism is ready

- **WHEN** a capacity-backed candidate's configured mechanisms are all unready
- **THEN** no listing is derived and the publication report records a refusal naming
  the readiness blockers

### Requirement: A deal settled by introduction has no fulfillment

The bare-metal fulfillment routes MUST resolve a deal's accepted settlement stage
before building fulfillment or loading a fulfillment context, and MUST answer a deal
whose stage does not fulfil through capacity with a not-found refusal naming that it
settled by introduction and has no fulfillment. This MUST hold whether or not the
storefront composes fulfillment at all.

#### Scenario: A buyer asks for an introduction deal's fulfillment

- **WHEN** a buyer requests fulfillment status, access, result, or teardown for a deal
  settled by introduction
- **THEN** the storefront answers not found, naming that the deal has no fulfillment

#### Scenario: A storefront composes introductions only

- **WHEN** a storefront composed with no fulfillment receives a fulfillment request for
  an introduction deal
- **THEN** it answers not found rather than failing

## MODIFIED Requirements

### Requirement: A bare-metal listing sells one whole unit

A capacity-backed bare-metal listing MUST be held by exclusive allocation of one unit
of its Physical Resource. Its capacity claim MUST request exactly one `units` and MUST
carry its shape's attributes, so that admission matches the published attributes. Its
shape's quantities describe what that unit contains, and MUST NOT be requested
dimension by dimension. An unbacked bare-metal listing constructs no capacity claim.

The claimed attributes MUST come from the storefront's trusted record of the accepted
listing, never from buyer input.

#### Scenario: A declaration changes model after acceptance

- **WHEN** a buyer accepts a capacity-backed bare-metal listing published with
  `gpu_model: H200`, and its Physical Resource's declaration is changed to another model
  before reservation
- **THEN** the site refuses the reservation

#### Scenario: An unbacked listing is accepted

- **WHEN** a buyer accepts an unbacked bare-metal listing
- **THEN** no capacity claim is constructed

### Requirement: Bare-metal opening rechecks its listing against its source

Whenever a bare-metal storefront rechecks a listing against its source, it MUST
re-derive the listing's shape and region from the resource-pool projection it holds for
the listing's own site, at its bound pool and Physical Resource, and MUST NOT fetch that
projection from the site to do so. It MUST refuse with a declared-match reason when any
of these hold:

- the shape digest differs from the binding's;
- the region differs from the published region;
- the Physical Resource is absent or disabled.

For a capacity-backed listing it MUST refuse with the availability reason when the
site's capacity snapshot shows the Physical Resource taken; an unbacked listing is
never refused for availability. It MUST refuse as retryable, for either backing, when
the projection it holds for the site has no value, or no site authority is configured.

#### Scenario: A declaration shrinks beneath its listing

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose Physical Resource now
  declares fewer GPUs than it published
- **THEN** the opening is refused with a declared-match reason

#### Scenario: The Physical Resource is taken

- **WHEN** a buyer opens a negotiation on a capacity-backed bare-metal listing whose
  Physical Resource is reserved by another deal
- **THEN** the opening is refused with the availability reason

#### Scenario: The site's projection is not held

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose site's projection the
  storefront does not hold
- **THEN** the opening is refused as retryable, and the site is not called

#### Scenario: An unbacked listing's resource moves to another pool

- **WHEN** a buyer opens a negotiation on an unbacked bare-metal listing whose Physical
  Resource the held projection now places in a pool other than its bound pool
- **THEN** the opening is refused with a declared-match reason

## REMOVED Requirements

### Requirement: An unbacked pool yields no bare-metal listing

**Reason**: Bare-metal publication now derives unbacked listings from unbacked pools,
bound and published as unbacked, so the refusal no longer holds.
**Migration**: None. Pools previously refused begin yielding unbacked listings on the
first bare-metal publication run after this change.
