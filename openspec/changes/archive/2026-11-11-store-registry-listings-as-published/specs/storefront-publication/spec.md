## ADDED Requirements

### Requirement: A listing's listing-level prices are published in one pricing object

A compute storefront MUST publish a listing's listing-level prices in one top-level
`pricing` object, on creation, refresh, reopen and registry repair: the listing's asking
rate as `pricing.asking_rate`, and, for a VM listing whose prices derive from resolved
family rates, that structure as `pricing.rate_structure`. Neither MUST be placed in the
listing's capacity description, and a listing stating neither MUST publish no `pricing`.
A settlement option's price stays with the option it prices.
The published structure MUST match the durable rates the storefront serves and uses to
derive shape prices. The registry engine MUST NOT interpret either. The storefront's own
view of a listing keeps the asking rate beside the shape it prices.

#### Scenario: A shape-priced listing is published

- **WHEN** a storefront derives a listing with resolved family rates and an asking rate
- **THEN** the registry publication carries both in `pricing`, and its capacity
  description carries neither
- **AND** buyers can verify them against retained seller publication evidence

#### Scenario: Family rates or an asking rate change or are withdrawn

- **WHEN** reconciliation refreshes a listing with changed or absent prices
- **THEN** the complete republication replaces the previous `pricing` accordingly, and a
  listing left with no price publishes none

#### Scenario: A listing reopens

- **WHEN** the storefront reopens a previously closed listing
- **THEN** it republishes its current durable prices before reopening discovery

### Requirement: Registry repair republishes the domain's candidate

When a publication pass republishes an open listing to a registry whose recorded outcome
disagrees with it, the storefront MUST send the publication candidate its domain builds
for that listing, as first publication and reopen do, and never the stored row as it is
held. It MUST first check the candidate's binding against the listing's durable binding
and validate the candidate as publication does; a listing that fails either stays
unrepaired at that registry and is reported, rather than republished.

#### Scenario: A registry missed a VM listing's publication

- **WHEN** the next publication pass repairs a VM listing at a registry that missed it
- **THEN** that registry receives the same document first publication sent, its prices in
  `pricing` and no null capacity attribute

#### Scenario: A repaired listing's binding disagrees

- **WHEN** a listing's candidate carries a binding other than the listing's durable
  binding
- **THEN** no registry is sent the listing and it remains diverged

## MODIFIED Requirements

### Requirement: A shape-priced listing records the rates that could price a revised shape

A shape-priced listing MUST record, on the storefront's generic listing record, every family's
resolved rate list for the listing — including families its own shape omits — and the storefront's
listing read MUST return it; a flat-priced listing records none. The record is a term of sale: a
change MUST refresh the listing in place, and the record MUST NOT be hashed into the listing's
identity, its shape digest, or any settlement option's identity. A settlement option's identity
MUST continue to cover its rates, so a change that alters a listing's composed rate changes that
option's identity while the listing's identity is unchanged. Publication to a registry MUST carry
each settlement option's composed rate for the listing's own shape in its option, and the recorded
rates as the listing's `pricing.rate_structure`, under the requirement that a listing's
listing-level prices are published in one pricing object.

#### Scenario: A family rate changes

- **WHEN** a shape-priced listing's composed rate changes while its shape and source do not
- **THEN** the listing keeps its identity, its options carry the new composed rate under new
  option identities, and its storefront listing read returns the new rates

#### Scenario: A rate changes for a family the listing's shape omits

- **WHEN** a GPU-only shape-priced listing's resolved memory rate changes
- **THEN** the listing is refreshed in place with the new recorded rate, and its composed rate and
  option identities are unchanged

#### Scenario: A listing is published to a registry

- **WHEN** a shape-priced listing is published
- **THEN** the registry receives the listing's settlement options with their composed rates in the
  existing option fields, and every recorded family's rates in `pricing.rate_structure`

### Requirement: A listing's asking rate is declared per shape

A compute listing MAY publish the rate its seller is asking for the listing's shape,
as an `asking_rate` object in the listing's published `pricing`, carrying `amount`,
`asset`, and `period`. The rate prices one listing shape: listings of different
shapes from the same pool carry independently declared rates, and a rate MUST NOT be
decomposed per capacity dimension.

The rate MUST resolve through this precedence, highest first:

1. The storefront's site-scoped pool override for the listing's site, pool, and
   offering mode, when it states asking rates.
2. Otherwise, the `asking_rates` declaration on the Resource Pool the listing derives
   from, read from the site's projection.
3. Otherwise, no asking rate.

Each tier states rates as a list of entries, each naming the capability shape it
prices. An entry applies to the listing whose shape has the same canonical digest.
An override's list MUST replace the pool's list as a whole; an empty override list
MUST be accepted and MUST mean that no listing of that pool publishes an asking rate.
An override is available for a pool at any site the storefront publishes for.

No storefront configuration default MAY supply an asking rate. Every published rate
is either the declaration of the listing's origin pool or an explicit override for
that site and pool, so a storefront publishing for several seller sites never
advertises its own blanket price as another site's.

A listing whose shape no applicable entry prices MUST publish normally with no
asking rate. An entry naming a shape the pool does not publish has no effect and MUST
be reported in the storefront's system status.

A storefront MUST publish only a complete rate: all three fields present, `amount`
exact positive decimal text without an exponent, `asset` a trimmed non-empty opaque
identifier, and `period` a unit this version accepts, which is `hour` alone.

The asking rate MUST NOT participate in any shape digest or derivation identity.

#### Scenario: A pool prices each of its shapes

- **WHEN** a pool publishes a 1-GPU and an 8-GPU shape and declares a rate for each
- **THEN** each listing publishes the rate declared for its own shape

#### Scenario: A shape is priced nowhere

- **WHEN** a pool publishes a shape that neither its declaration nor an override prices
- **THEN** that listing publishes normally with no asking rate

#### Scenario: The storefront overrides a remote site's rate

- **WHEN** the storefront's override for a pool at a site other than its first
  configured site states an asking rate for one of the pool's shapes
- **THEN** that listing publishes the override's rate and not the pool's declaration

#### Scenario: The storefront withholds every rate

- **WHEN** the storefront's override for a pool states an empty asking-rate list
- **THEN** no listing of that pool publishes an asking rate, whatever the pool declares

#### Scenario: A storefront configures pricing defaults

- **WHEN** a pool declares no asking rates, no override states any, and the storefront
  configures negotiation-floor or settlement defaults
- **THEN** no listing of that pool publishes an asking rate
