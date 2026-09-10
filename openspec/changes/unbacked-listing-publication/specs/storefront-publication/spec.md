## ADDED Requirements

### Requirement: A listing's origin site is not its admission authority

Every storefront listing binding MUST record the site the listing originated from
and, separately, whether an admission authority stands behind it. The origin site
is populated for every listing including an unbacked one, because an unbacked
listing is projected from a site like any other.

The durable binding MUST carry an explicit backing discriminator rather than
encoding the category as an absent site or an absent field, and that discriminator
MUST be covered by the binding's existing immutability guarantee so a listing
cannot change category after binding.

Publication provenance MUST separate common listing identity — origin site,
offering mode, and source declaration identity — from admission provenance. Only
operations that reserve, commit, release, schedule, or dispatch MUST require the
capacity-backed admission variant; operations that compare, copy, or carry listing
identity MUST accept either.

#### Scenario: An unbacked listing binds

- **WHEN** a storefront publishes a listing derived from a pool declaring no admission authority
- **THEN** the durable binding records the origin site, the offering mode, the source declaration identity, and an explicit unbacked discriminator
- **AND** the binding is otherwise indistinguishable in shape from a capacity-backed listing's

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
copy of a site fact, and the two MUST NOT be conflated. Backing MUST NOT be inferred from absent
capacity data, an empty projection, or a stale generation.

A projection whose producer declares backing for no pool it projects predates the
declaration. Every pool in such a projection MUST resolve as capacity-backed under an explicit,
logged compatibility rule, because every pool was admissible before the declaration
existed. That rule is retained until a future change acquires a reliable signal that
no producer relies on it; self-hosted sites may lag without bound, so no release count
is a meaningful removal condition. A projection declaring backing for some pools and omitting
it for another it projects is malformed, and the omitting pool MUST fail closed. A
declared value outside the accepted set MUST fail that pool closed.

The same compatibility shape applies to a projected pool's advertisement
authorization: where a producer declares it for no pool, delivery authorization
serves as advertisement authorization, reproducing the contract that applied before
the declaration existed.

#### Scenario: A producer predates the declarations

- **WHEN** a storefront ingests a projection whose producer declares neither backing nor advertisement authorization for any pool
- **THEN** every pool resolves as capacity-backed with delivery authorization serving as advertisement authorization
- **AND** the compatibility rule is logged
- **AND** listings previously derived from that site continue to publish unchanged

#### Scenario: A producer omits a declaration for one pool

- **WHEN** a storefront ingests a projection declaring backing for some pools and omitting it for another it projects
- **THEN** the omitting pool fails closed rather than resolving to either value

#### Scenario: A declared backing value is unrecognized

- **WHEN** a projected pool declares a backing value outside the accepted set
- **THEN** that pool fails closed rather than falling back to a structural default

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

### Requirement: Source publication and capacity availability reconcile separately

Source-publication reconciliation MUST apply to every listing regardless of
backing: a removed or disabled source declaration MUST close the listings derived
from it, and a changed source declaration MUST be reflected deterministically in
what is published.

How a change is reflected depends on whether it alters the listing's derivation
identity. A change to a field the derivation source envelope carries produces a
different derivation key, and the durable binding is immutable, so such a change
MUST close the existing listing and publish a newly derived one. A change confined
to payload outside the derivation identity MAY update the existing listing in place.
An implementation MUST NOT attempt an in-place update for an identity-bearing
change: the binding cannot record it, so the published listing and its durable
identity would disagree.

Capacity-availability reconciliation and its close-before-reopen sequencing MUST
apply only to capacity-backed listings. An unbacked listing has no availability to
track, which is what its inexhaustibility means; it is not an exemption from having
its published state follow its declaration.

An unbacked listing MUST have no storefront-local source-inventory record — no
derived-listing row and no local resource table. That prohibition does not exempt
it from source-publication reconciliation.

#### Scenario: An unbacked listing's source declaration is removed

- **WHEN** a capacity resource or pool an unbacked listing derives from is removed or disabled
- **THEN** the published listing closes

#### Scenario: A declared shape change alters derivation identity

- **WHEN** a source declaration changes a field the derivation source envelope carries
- **THEN** the existing listing closes and a newly derived listing is published with a different derivation key
- **AND** the original binding row is unmodified

#### Scenario: A source change outside derivation identity

- **WHEN** a source declaration changes only fields outside the derivation source envelope
- **THEN** the existing listing is updated in place and retains its derivation identity

#### Scenario: An unbacked listing's source changes

- **WHEN** the declaration behind an unbacked listing changes
- **THEN** the change is reflected without entering capacity-availability reconciliation

#### Scenario: Capacity deltas do not reach an unbacked listing

- **WHEN** capacity-availability reconciliation runs
- **THEN** no unbacked listing is closed, reopened, or resized by it

### Requirement: Site-pinned claim routing applies to capacity-backed listings

The requirement that a trusted listing mapping routes to exactly one site for claim
construction MUST apply to capacity-backed listings. An unbacked listing constructs
no reservation claim, so it has no claim to route.

Refusing claim construction for an unbacked listing is a fail-closed guard against
a reservation record with no authority behind it. It is not a control on what a
seller may publish, and no requirement in this capability verifies a seller's
claims.

#### Scenario: An unbacked listing is queried for a claim route

- **WHEN** claim construction is attempted for an unbacked listing
- **THEN** no claim is constructed and the attempt is refused

### Requirement: A listing's published shape comes from its source declaration

A listing's published compute shape is derived from the shape its source
declaration carries, for capacity-backed and unbacked listings alike. Nothing in
publication verifies that shape against hardware, and this requirement makes no
claim that it does.

A source declaration carrying no quantity where the derivation needs one is
defective. Derivation MUST refuse the candidate rather than substituting a
default, because a substituted quantity is indistinguishable in the published
listing from a declared one.

Where a listing is capacity-backed, the published quantity is additionally bounded
by the availability its site projects, so it moves as capacity is reserved and
released. An unbacked listing has no availability to bound it and no reservation
consumes it; that difference is carried by the listing's published backing and
MUST NOT be encoded a second time in a separate published field.

#### Scenario: A source declaration carries no quantity

- **WHEN** a source declaration behind a listing carries no quantity and the derivation needs one
- **THEN** derivation refuses the candidate rather than publishing a substituted default

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
