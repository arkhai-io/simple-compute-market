## ADDED Requirements

### Requirement: A pool's listing shapes are chosen by its site and its storefront

A pool MAY be listed in chosen shapes. Each shape is a family-grouped capability shape in the
domain's vocabulary. A pool's shapes MUST come from exactly one source: the storefront's
override for that site and pool when it states shapes; otherwise the pool's own
`listing_shapes` hint for the listing's offering mode. The storefront's list MUST replace the
pool's list as a whole. A pool with a shape list MUST publish exactly its listed shapes and
MUST NOT also enumerate listings by quantity. A pool with no shape list from either source
MUST publish exactly as it would without shapes.

A shaped listing MUST publish every quantity and attribute its shape declares, flattened
through the domain's schema. It MUST NOT publish a quantity its shape does not declare. A
shape omitting an optional family makes no commitment about it. The capacity claim built
from a shaped listing MUST request exactly the shape's quantities, so a shaped listing
reserves and provisions its shape.

How many of a shape a pool can serve MUST be derived from its capacity declarations. It MUST
NOT be declared, and MUST NOT be published.

For the VM domain every shape MUST name a GPU count and a GPU model. A fungible pool MUST
publish one listing per shape. A specific-resource pool MUST publish one listing per member
per shape that member can hold.

#### Scenario: A site declares shapes for a pool

- **WHEN** a pool's projected `listing_shapes` hint lists two VM shapes and the storefront
  has no override for that site and pool
- **THEN** the storefront publishes one listing per shape, each carrying its shape's GPU
  count, GPU model, and every other declared quantity, and publishes no GPU-count slices for
  the pool

#### Scenario: The storefront replaces a pool's shapes

- **WHEN** the storefront's override for a site and pool states one shape while the pool's
  hint states two
- **THEN** only the override's shape is published for that pool

#### Scenario: A pool states no shapes

- **WHEN** neither the storefront's override nor the pool's hint states shapes for a pool
- **THEN** the pool's listings are identical to those it published without shapes, and none
  carries a dimension beyond GPU count

#### Scenario: A shape omits memory

- **WHEN** a VM shape declares GPU count, GPU model, and vCPU count but no memory family
- **THEN** its listing publishes no `ram_gb` and its capacity claim requests no memory

#### Scenario: Eight single-GPU VMs from one host

- **WHEN** a fungible pool whose one member declares eight GPUs lists a one-GPU shape
- **THEN** the storefront publishes one listing for that shape, and successive reservations
  against it each reserve one GPU and the shape's other quantities until the member cannot
  admit another

### Requirement: A listing shape is published only where its source can hold it

A shape MUST be publishable only where a member of its source can admit the capacity claim
its listing would produce:

- for a fungible pool, some single enabled member;
- for a specific-resource pool, that member.

Fit MUST be judged by the site authority's own exported claim predicate, evaluated against
the member's declared capacity. For a capacity-backed listing the shape MUST additionally be
admissible against the member's currently available dimensions, for every dimension of the
shape. A member whose projection reports no availability is unknown rather than empty, and
MUST be treated as its declared capacity. An unbacked listing MUST be judged on declared
capacity alone.

A shape that fits no member MUST yield no listing and MUST be reported in the storefront's
system status, naming the site, the pool, the shape, and what did not fit. Publication MUST
NOT shrink a shape to fit. It MUST NOT substitute the pool's own shapes for an override that
does not fit, and MUST NOT substitute quantity enumeration. A pool whose shape hint the domain
cannot read MUST yield no new shaped listing, MUST be reported, and its existing shaped
listings MUST be held rather than closed.

The seller's inventory guard MUST apply the same fit to a shaped listing's declared match.

#### Scenario: An override names a model the pool does not have

- **WHEN** a storefront override lists a shape whose GPU model no enabled member of the pool
  declares
- **THEN** no listing is published for that shape and system status reports it, naming the
  model as what did not fit

#### Scenario: A declaration shrinks beneath a published shape

- **WHEN** a member's declared memory falls below the memory of a shape published from it
  and no other member can hold the shape
- **THEN** the shaped listing closes through source reconciliation and the unfit shape is
  reported

#### Scenario: A backed shape's memory is taken

- **WHEN** a capacity-backed shape's GPUs are free on a member but the member's available
  memory is below the shape's
- **THEN** the shape is not publishable from that member

#### Scenario: A pool's shape hint cannot be read

- **WHEN** a pool's `listing_shapes` hint for the VM mode contains a family or field outside
  the VM vocabulary
- **THEN** no new shaped listing is derived from the pool, its existing shaped listings are
  held, the pool does not fall back to quantity enumeration, and system status reports the
  problem

### Requirement: A shaped listing's derivation identity includes its shape

A shaped listing's derivation identity MUST include a canonical digest of its shape, taken
over the family-grouped form rather than the flattened field names. Its durable binding MUST
record the shape in a source envelope version distinct from that of listings enumerated by
quantity. A stored shaped listing's derivation identity MUST be read from its binding rather
than recomputed from its published fields. A change to a pool's shape MUST therefore close
listings under the old shape and publish listings under the new one. Listings enumerated by
quantity MUST keep their existing derivation identities.

#### Scenario: A shape is edited

- **WHEN** a pool's only listed shape changes its memory from 64 to 96 GiB
- **THEN** the listing for the 64 GiB shape closes and a listing with a distinct derivation
  key is published for the 96 GiB shape, leaving the original binding row unmodified

#### Scenario: A storefront adopts this behaviour

- **WHEN** a storefront whose pools declare no shapes is upgraded
- **THEN** every existing listing keeps its derivation key and binding, and none is closed or
  republished

### Requirement: Storefront pool overrides are site-scoped and durable

A storefront's per-pool overrides MUST be stored durably, keyed by site and pool. An override
MAY state SLA, pricing, settlement clauses, and listing shapes. An override MUST NOT state
region, offering mode, or capacity backing. A field an override leaves unset MUST fall
through to the next precedence tier. Listing shapes and settlement clauses MUST each replace
the lower tier's list as a whole, and an empty shape list MUST be refused.

Within the storefront-override tier, a value in the site-scoped store MUST take precedence
over the home-site legacy override record. While a legacy value is in effect for a pool, the
storefront's system status MUST report it.

An override MUST outlive the projection of its pool. While the pool is absent from its site's
projection the override has no effect and MUST be reported as orphaned. When the pool returns,
the override MUST apply again.

#### Scenario: Two sites name a pool identically

- **WHEN** overrides are stored for pool `gpu` at site `a` and at site `b`
- **THEN** each applies only to listings derived from its own site's pool

#### Scenario: A pool at a non-home site is overridden

- **WHEN** an override states an SLA for a pool at a site other than the storefront's first
  configured site
- **THEN** listings derived from that pool publish the overridden SLA

#### Scenario: An override is deleted over a legacy value

- **WHEN** an override's SLA is deleted for a home-site pool whose legacy override record
  also states an SLA
- **THEN** the legacy SLA applies and system status reports that a legacy value is in effect
  for the pool

#### Scenario: A pool disappears and returns

- **WHEN** a pool with an override leaves its site's projection and later reappears
- **THEN** the override is retained and reported as orphaned while the pool is absent, and
  applies again once the pool is projected

### Requirement: Storefront pool overrides are written against the site's live projection

A storefront MUST expose authenticated administrator operations to replace, read, list, and
delete a pool override. They MUST address the site and pool in the request body or query
rather than the path, and MUST bind them into the signed resource with an unambiguous
encoding. Replacement MUST replace the whole record. Deletion MUST be idempotent.

Before accepting a replacement, the storefront MUST refuse:

- a site it has not configured;
- a structurally invalid record, including a shape outside the domain's vocabulary.

It MUST then fetch that site's resource-pool projection live through the site's
authenticated client, not from its cache:

- a pool absent from the live projection MUST be refused;
- an unreachable site, or a response that does not verify, MUST be refused as retryable,
  with a reason distinct from an absent pool;
- a pool present in the live projection MUST be accepted even when its declarations are
  unresolvable.

A shape that fits no member of the live projection MUST NOT cause refusal. The response MUST
report fit per shape against that live projection and identify the projection generation it
used. After accepting a write, the storefront MUST cause its cached projection to refresh
and its publication loop to run, without writing the live result into the cache itself.

#### Scenario: The pool is unknown to the site

- **WHEN** an administrator writes an override for a pool the site's live projection does
  not contain, while the storefront's cached projection still lists it
- **THEN** the write is refused and nothing is stored

#### Scenario: The site is unreachable

- **WHEN** an administrator writes an override while the named site cannot be reached
- **THEN** the write is refused as retryable, naming the site as unavailable rather than the
  pool as unknown

#### Scenario: An override's shape fits nothing

- **WHEN** an administrator writes an override whose only shape fits no member of the live
  projection
- **THEN** the override is stored, the response reports the shape as fitting no member, and
  the next publication cycle publishes no listing for it

#### Scenario: A shape outside the vocabulary

- **WHEN** an administrator writes an override whose shape names a family or field the
  domain does not define
- **THEN** the write is refused without contacting the site

## MODIFIED Requirements

### Requirement: A listing's published shape comes from its source declaration

A listing's published compute shape is derived from its source declaration, for
capacity-backed and unbacked listings alike. For a listing enumerated by quantity it is the
shape its declaration carries. For a shaped listing it is the chosen shape, bounded by what
its source declares. Nothing in publication verifies that shape against hardware, and this
requirement makes no claim that it does.

Derivation MUST NOT substitute a value for a quantity a declaration does not carry. A
declaration that omits the quantity a domain enumerates listings by MUST yield no
listing, and the omission MUST be reported to the operator naming the declaration. A
declaration that declares that quantity as zero MUST yield no listing without a
report. A declaration whose quantity is malformed MUST be treated as unresolvable:
it yields no new listing and its existing listings are held. In a fungible pool one
unresolvable member holds every listing derived from the pool, because the pool's range
cannot be computed without it; in a specific-resource pool it holds only its own.

Where a listing enumerated by quantity is capacity-backed, the published quantity is
additionally bounded by the availability its site projects, so it moves as capacity is
reserved and released. An unbacked fungible pool's enumerated listings range up to the
largest single member's declared quantity, never a sum across members, because a
reservation would land on one member. A shaped listing's quantities never move: whether it
is publishable follows the shape-fit requirement instead. An unbacked listing has no
availability to bound it and no reservation consumes it; that difference is carried by the
listing's published backing and MUST NOT be encoded a second time in a separate published
field.

#### Scenario: A declaration omits the enumerated quantity

- **WHEN** a source declaration carries no GPU count
- **THEN** no VM listing is derived from it, listings previously derived from it close, and the operator is told which declaration omits it

#### Scenario: A declaration declares zero

- **WHEN** a source declaration declares a GPU count of zero
- **THEN** no VM listing is derived from it and no report is made

#### Scenario: An unbacked listing's published quantity does not move

- **WHEN** any number of buyers settle against an unbacked listing
- **THEN** its published quantity is unchanged, because no reservation consumes it

#### Scenario: A shaped listing's quantities do not follow availability

- **WHEN** reservations consume part of a capacity-backed member from which a shaped listing
  is published, and the member can still admit the shape
- **THEN** the shaped listing stays open with its quantities unchanged
