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
- **THEN** the operation is refused before any effect

### Requirement: Backing is declared by the projected pool

A storefront MUST resolve a listing's backing from the declared value on the
projected pool it derives from, read live from the current projection and never
persisted into storefront-local storage. Backing MUST NOT be inferred from absent
capacity data, an empty projection, or a stale generation.

A projection whose producer declares backing for no pool it projects predates the
declaration. Every pool in such a projection MUST resolve as capacity-backed under
an explicit, logged compatibility rule, because every pool was admissible before
the declaration existed. A projection declaring backing for some pools and omitting
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
from it, and a changed declared shape MUST update them deterministically.

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

#### Scenario: An unbacked listing's declared shape changes

- **WHEN** the declared shape behind an unbacked listing changes
- **THEN** the published listing is updated deterministically without entering capacity-availability reconciliation

#### Scenario: Capacity deltas do not reach an unbacked listing

- **WHEN** capacity-availability reconciliation runs
- **THEN** no unbacked listing is closed, reopened, or resized by it

### Requirement: Site-pinned claim routing applies to capacity-backed listings

The requirement that a trusted listing mapping routes to exactly one site for claim
construction MUST apply to capacity-backed listings. An unbacked listing constructs
no reservation claim, so it has no claim to route.

#### Scenario: An unbacked listing is queried for a claim route

- **WHEN** claim construction is attempted for an unbacked listing
- **THEN** no claim is constructed and the attempt is refused

### Requirement: Published capacity on an unbacked listing is declared, not available

A capacity-backed listing's published capacity is bounded by what its site can
currently admit. An unbacked listing has no availability, so its published capacity
MUST be the quantity its source declaration carries, and the listing MUST identify
it as declared rather than currently available.

A source declaration behind an unbacked listing that carries no quantity is
defective. Derivation MUST refuse it rather than substituting a default, because a
substituted quantity is indistinguishable from a declared one.

#### Scenario: An unbacked listing publishes capacity

- **WHEN** a storefront derives a listing from an unbacked pool whose capacity resource declares a quantity
- **THEN** the published capacity is that declared quantity, identified as declared rather than currently available

#### Scenario: A source declaration carries no quantity

- **WHEN** a source declaration behind an unbacked listing carries no quantity
- **THEN** derivation refuses the candidate rather than publishing a substituted default

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
