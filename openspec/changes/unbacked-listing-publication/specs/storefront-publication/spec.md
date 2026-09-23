## ADDED Requirements

### Requirement: A listing's origin site is not its admission authority

Every storefront listing binding MUST record the site the listing originated from
and, separately, whether an admission authority stands behind it. The origin site
is populated for every listing including an unbacked one, because an unbacked
listing is projected from a site like any other.

The durable binding MUST carry an explicit backing discriminator rather than
encoding the category as an absent site or an absent field. The discriminator MUST
be covered by the binding's immutability guarantee so a listing cannot change
category after binding, and a binding written without it MUST be refused rather
than classified by a default.

Publication provenance MUST separate common listing identity — origin site,
offering mode, and source declaration identity — from admission provenance. Only
operations that reserve, commit, release, schedule, or dispatch MUST require the
capacity-backed admission variant; operations that compare, copy, or carry listing
identity MUST accept either.

#### Scenario: An unbacked listing binds

- **WHEN** a storefront publishes a listing derived from a pool declaring no admission authority
- **THEN** the durable binding records the origin site, the offering mode, the source declaration identity, and an explicit unbacked discriminator
- **AND** the binding is otherwise indistinguishable in shape from a capacity-backed listing's

#### Scenario: A binding names no backing

- **WHEN** a writer inserts a listing binding without a backing discriminator
- **THEN** the insert is refused rather than recorded as either value

#### Scenario: A bound listing's backing is changed

- **WHEN** a writer attempts to change a recorded binding's backing discriminator
- **THEN** the change is refused and the binding is unchanged

#### Scenario: An unbacked listing enters a negotiation

- **WHEN** a buyer opens a negotiation against an unbacked listing
- **THEN** the durable listing binding is copied to the negotiation thread with its origin site, offering mode, domain identity, and contract version
- **AND** no step of the negotiation lifecycle refuses the listing for lacking an admission authority

#### Scenario: A capacity operation receives an unbacked listing

- **WHEN** a reservation, commit, release, scheduling, or dispatch operation is attempted for an unbacked listing
- **THEN** the operation is refused before any effect, so no reservation record is created with no authority behind it

### Requirement: Backing is declared by the projected pool

A storefront MUST resolve a listing's backing from the declared value on the
projected pool it derives from, reading that projected tag live at each point of
need and never caching it as storefront-local inventory. The backing discriminator
recorded on a listing's durable binding is derived from that value at publication
and is immutable; it is a storefront fact about a bound listing rather than a cached
copy of a site fact, and the two MUST NOT be conflated. Backing MUST NOT be inferred
from absent capacity data, an empty projection, or a stale generation.

A storefront MUST judge a projection's declarations jointly, per site and per
projection generation. A generation in which no projected pool carries either the
backing or the advertisement declaration comes from a producer that predates them:
every pool in it MUST resolve as capacity-backed with delivery authorization serving
as advertisement authorization, reproducing the contract that applied before the
declarations existed, under one compatibility rule that is logged and reported in
the storefront's system status. That rule is retained until a future change acquires
a reliable signal that no producer relies on it; self-hosted sites may lag without
bound, so no release count is a meaningful removal condition.

In any other generation, a pool whose declarations are absent, malformed, or
violate a cross-declaration rule is unresolvable. An unresolvable pool MUST yield no
new listing candidates, and its existing listings MUST be neither closed nor
refreshed until it resolves, because an unknown declaration is not a withdrawn one.
Each unresolvable pool MUST be reported in the storefront's system status with the
reasons it could not be resolved.

#### Scenario: A producer predates the declarations

- **WHEN** a storefront ingests a site's projection generation in which no pool declares backing or advertisement authorization
- **THEN** every pool resolves as capacity-backed with delivery authorization serving as advertisement authorization
- **AND** the compatibility rule is logged and reported in system status
- **AND** listings previously derived from that site continue to publish unchanged

#### Scenario: A producer omits a declaration for one pool

- **WHEN** a projection generation declares backing and advertisement for some pools and omits them for another it projects
- **THEN** the omitting pool is unresolvable rather than resolving to either value

#### Scenario: A producer emits only one of the two declarations

- **WHEN** a projection generation carries a backing declaration on some pool but no advertisement declaration on any
- **THEN** the generation is not read as an older producer's, and every pool lacking either declaration is unresolvable

#### Scenario: A declared backing value is unrecognized

- **WHEN** a projected pool declares a backing value outside the accepted set
- **THEN** that pool is unresolvable rather than falling back to a structural default

#### Scenario: An unresolvable pool has published listings

- **WHEN** a pool with open listings becomes unresolvable
- **THEN** no new listing is derived from it, its existing listings stay as they are, and system status names the pool and its problems
- **AND** when the pool resolves again its listings are reconciled against the resolved declarations

### Requirement: A listing advertises only a mode its pool authorizes

A listing derived from a Resource Pool MUST offer only an offering mode that pool
declares advertisable, whether the listing is capacity-backed or unbacked. The
listing's offering mode continues to resolve from the frozen contribution
registration, and the public offer's mode MUST continue to equal the recorded
offering mode.

The pool's delivery authorization MUST continue to be rechecked at reservation,
scheduling, and provider dispatch, and those rechecks apply only to capacity-backed
listings because only they reach those layers.

#### Scenario: A pool authorizes advertisement but not delivery

- **WHEN** an unbacked pool declares a mode advertisable that its provider configuration does not prove deliverable
- **THEN** a listing derived from that pool may offer that mode
- **AND** no reservation, scheduling, or dispatch path is reachable for that listing

#### Scenario: A listing offers a mode its pool does not authorize

- **WHEN** candidate derivation would produce a listing offering a mode its pool does not declare advertisable
- **THEN** the candidate is refused rather than published

### Requirement: A listing's identity is the physical resource it offers

A listing's identity MUST be the physical resource it offers: the supply it draws
from (site, and pool or Physical Resource), what the resource is (offering mode,
resource type and subtype, and categorical attributes), where it is (region), and how
much of it one listing offers (the enumerated quantity and every other declared
dimension the listing publishes). Every other published field — price and pricing
hints, settlement options, maximum duration, and service level — is a term of sale.

A listing commits only to the fields it publishes. A field a listing does not publish
is no commitment. Reconciliation MUST NOT add an identity field to a listing that did
not publish one, because that would make a new commitment under an existing listing
identity.

A change to a term of sale MUST update the listing in place and retain its identity. A
change to an identity field MUST NOT be applied to an existing listing in place. Where
the listing's derivation identity captures the changed field, the existing listing
closes and a newly derived listing is published. Where it does not, the existing
listing MUST close and MUST NOT reopen while its published value differs from its
source, and the refusal MUST be logged naming the source and the differing fields.

Capacity backing is not an identity field under this requirement: it is recorded on
the binding at creation and governed by the backing requirements.

#### Scenario: A term of sale changes

- **WHEN** the price or settlement options behind an open listing change
- **THEN** the listing is updated in place at the storefront and every registry, and retains its listing identity and derivation key

#### Scenario: An identity field outside derivation identity changes

- **WHEN** a declaration behind an open listing changes a published categorical attribute that the listing's derivation identity does not capture
- **THEN** the listing closes and is not reopened while the published value differs from the declaration
- **AND** the refusal is logged naming the declaration and the differing attribute

#### Scenario: A newly published field is absent from an existing listing

- **WHEN** publication begins emitting an identity field that an existing listing did not publish
- **THEN** the existing listing is neither closed nor updated to carry the field, because it made no commitment about it
- **AND** listings published afterwards carry the field

#### Scenario: A pool returns with the opposite backing

- **WHEN** a site's pool is recreated under an existing pool ID with backing opposite to the discriminator on listings bound from it
- **THEN** those listings close and are not reopened, and no replacement listing binds under their derivation identity

### Requirement: Source publication and capacity availability reconcile separately

Source-publication reconciliation MUST apply to every listing regardless of backing:
a removed or disabled source declaration MUST close the listings derived from it, and
a changed source declaration MUST be reflected in what is published according to the
listing identity requirement. Source-publication reconciliation MUST re-derive open
listings and compare them with what is published, so that a change to a term of sale
reaches an open listing.

Capacity-availability reconciliation and its close-before-reopen sequencing MUST
apply only to capacity-backed listings. An unbacked listing's quantity is bounded by
what its source declares, never by availability, which is what its inexhaustibility
means; it is not an exemption from having its published state follow its
declaration.

An unbacked listing MUST be derived only from the site projection. No
storefront-local table may source its shape or capacity; its storefront-local records
are its listing row and its immutable binding. That prohibition does not exempt it
from source-publication reconciliation.

#### Scenario: An unbacked listing's source declaration is removed

- **WHEN** a capacity resource or pool an unbacked listing derives from is removed or disabled
- **THEN** the published listing closes

#### Scenario: An unbacked source is re-enabled

- **WHEN** a disabled declaration behind closed unbacked listings is enabled again with the same declared shape
- **THEN** those listings reopen under their original listing identities

#### Scenario: A declared shape change alters derivation identity

- **WHEN** a source declaration changes a field the derivation source envelope carries
- **THEN** the existing listing closes and a newly derived listing is published with a different derivation key
- **AND** the original binding row is unmodified

#### Scenario: Capacity deltas do not reach an unbacked listing

- **WHEN** capacity-availability reconciliation runs, including after a settlement against an unbacked listing
- **THEN** no unbacked listing is closed, reopened, or resized by it

### Requirement: The seller's inventory guard checks a listing against its own source

Before a seller agrees terms, seller negotiation policy MUST recheck every published
field of the listing that is sourced from its declaration or pool against that
source: the listing's own site and pool or Physical Resource, never a resource
elsewhere. A categorical field MUST equal its source and a quantity MUST fit the
declared capacity. Fields whose authority is the storefront are not rechecked.

Seller policy MUST additionally check that the listing's published quantity is
available only for a capacity-backed listing. For an unbacked listing it MUST NOT
consult availability or contact a site authority.

A declared-match failure MUST be reported with a reason distinct from an availability
failure, so a buyer and an operator can tell a shape the seller no longer declares
from capacity that is temporarily taken.

#### Scenario: An unbacked listing matches its declaration

- **WHEN** a buyer negotiates against an unbacked listing whose published fields match its enabled source declaration
- **THEN** the declared match passes without any availability read or site call

#### Scenario: A declaration no longer supports its listing

- **WHEN** a buyer negotiates against a listing whose source declaration has shrunk below, or been disabled beneath, its published shape
- **THEN** seller policy rejects with a declared-match reason rather than an availability reason

#### Scenario: Matching capacity exists only elsewhere

- **WHEN** a listing's own source no longer supports it but another pool or site holds matching available capacity
- **THEN** seller policy rejects the listing

#### Scenario: A backed listing matches but capacity is taken

- **WHEN** a capacity-backed listing matches its declaration but its published quantity is not available
- **THEN** seller policy rejects with the availability reason

### Requirement: A listing's published shape comes from its source declaration

A listing's published compute shape is derived from the shape its source
declaration carries, for capacity-backed and unbacked listings alike. Nothing in
publication verifies that shape against hardware, and this requirement makes no
claim that it does.

Derivation MUST NOT substitute a value for a quantity a declaration does not carry. A
declaration that omits the quantity a domain enumerates listings by MUST yield no
listing, and the omission MUST be reported to the operator naming the declaration. A
declaration that declares that quantity as zero MUST yield no listing without a
report. A declaration whose quantity is malformed MUST be treated as unresolvable:
it yields no new listing and its existing listings are held.

Where a listing is capacity-backed, the published quantity is additionally bounded
by the availability its site projects, so it moves as capacity is reserved and
released. An unbacked listing has no availability to bound it and no reservation
consumes it; that difference is carried by the listing's published backing and MUST
NOT be encoded a second time in a separate published field.

#### Scenario: A declaration omits the enumerated quantity

- **WHEN** a source declaration carries no GPU count
- **THEN** no VM listing is derived from it, listings previously derived from it close, and the operator is told which declaration omits it

#### Scenario: A declaration declares zero

- **WHEN** a source declaration declares a GPU count of zero
- **THEN** no VM listing is derived from it and no report is made

#### Scenario: An unbacked listing's published quantity does not move

- **WHEN** any number of buyers settle against an unbacked listing
- **THEN** its published quantity is unchanged, because no reservation consumes it

### Requirement: A backing change closes and republishes

A listing's backing is fixed for the life of its durable binding. Where the supply
behind a listing moves between backed and unbacked, the existing listing MUST close
and a new listing MUST bind with its own durable identity and its own backing
discriminator.

An implementation MUST NOT attempt an in-place update of a listing's backing, in
either the durable binding or the published payload. Because the pool a listing
derives from carries backing that is itself fixed at creation, a supply move is a
move between pools, and the republished listing's derivation identity differs by
construction.

#### Scenario: Supply moves from unbacked to backed

- **WHEN** the supply behind an unbacked listing is moved to a pool declaring capacity backing
- **THEN** the unbacked listing closes and a new listing binds with a distinct durable identity and a capacity-backed discriminator
- **AND** the original binding row is unmodified

## MODIFIED Requirements

### Requirement: Commercial mapping identity
A VM listing's commercial mapping between an authoritative capacity identity and the published listing MUST be its immutable common listing binding. VM publication, reconciliation, close, and reopen MUST NOT read or write `derived_compute_listings`; a closed listing is found again by its candidate's derivation key in the common binding. A domain that still keeps its own mapping table (`derived_bare_metal_listings`) MUST NOT duplicate it as a separate schema. Pricing, settlement terms, and seller policy MUST continue to live on the generic `listings` table, addressed by `listing_id` — no mapping carries commercial fields of its own. Each derivation key MUST include the owning `site_id`, since a pool or resource identifier is only unique within one site, never globally. A derivation key MUST be collision-resistant by construction against any values its constituent fields (`site_id`, `pool_id`, `resource_id`) may take — these are operator-chosen strings with no character restrictions, so a naive delimiter-joined encoding is not sufficient.

#### Scenario: Two sites name a pool identically
- **WHEN** two different sites each have a pool sharing the same operator-chosen `pool_id`
- **THEN** their listing bindings have distinct derivation keys and neither binding is silently overwritten by the other's

#### Scenario: An operator-chosen identifier contains a delimiter character
- **WHEN** a `site_id`, `pool_id`, or `resource_id` value contains a character that would otherwise separate fields in a naively joined key
- **THEN** the resulting derivation key remains distinct from any other combination of values that could produce the same joined string

#### Scenario: Two specific-resource candidates share a pool
- **WHEN** a multi-member pool publishes more than one `specific_resource` candidate, each naming a different physical resource
- **THEN** each candidate's derivation key is resource-keyed and distinct, and binding one candidate does not overwrite another's

#### Scenario: A closed listing's slice becomes publishable again
- **WHEN** a closed VM listing's candidate is derived again with the same derivation identity
- **THEN** the listing bound under that derivation key reopens, rather than a new listing being bound under a colliding key

### Requirement: Site-pinned claim routing
A capacity claim for a capacity-backed listing with a known site mapping MUST be routed to exactly that site, with no fallback to a different site on refusal or error — this applies to every such listing, whether the underlying capacity is fungible (pool-derived) or pinned to a specific physical resource, never only to resource-pinned listings. A capacity-backed listing with no recorded site mapping MAY be routed by placement policy across configured sites. An unbacked listing constructs no capacity claim, so it has no claim to route; refusing claim construction for it is a fail-closed guard against a reservation record with no authority behind it, not a control on what a seller may publish.

#### Scenario: A mapped listing's site would lose to placement policy
- **WHEN** a capacity-backed listing is mapped to one site but placement policy would otherwise prefer a different configured site with more available capacity
- **THEN** the claim is routed only to the listing's mapped site, regardless of what placement policy would have chosen for an unmapped claim

#### Scenario: A mapped site refuses or errors
- **WHEN** a capacity-backed listing's mapped site refuses the claim or the request to that site fails
- **THEN** the claim is not retried against a different configured site

#### Scenario: An unbacked listing is queried for a claim route
- **WHEN** claim construction is attempted for an unbacked listing
- **THEN** no claim is constructed and the attempt is refused

### Requirement: Trusted listing mappings route to one site

A capacity-backed listing with a durable site mapping MUST route all capacity claims to exactly that configured site and pinned authority. Refusal, outage, missing trust, or mode disagreement at that site MUST fail closed and MUST NOT fan out to another site. An unbacked listing's durable site mapping records its origin and routes no capacity claim.

#### Scenario: A normalized listing disagrees with its binding

- **WHEN** a normalized domain listing projects an `offering_mode` different from its registration or durable binding
- **THEN** publication is refused rather than publishing a listing whose public mode disagrees with its provenance

#### Scenario: A published shape is submitted under the retired key

- **WHEN** a listing is submitted carrying the published shape under `offer_resource` or `offer`
- **THEN** it is rejected rather than accepted under a second spelling

#### Scenario: Another site could satisfy the claim

- **WHEN** the bound site refuses a capacity-backed listing's claim while another configured site has compatible capacity
- **THEN** the storefront reports the bound-site refusal and the other site receives zero calls

#### Scenario: An unbacked listing's origin site is unreachable

- **WHEN** the origin site recorded on an unbacked listing's binding is unreachable
- **THEN** no capacity claim is attempted at it or at any other site
