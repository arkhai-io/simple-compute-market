## ADDED Requirements

### Requirement: Every listing is a listing shape

Every listing a domain publishes MUST be a listing shape: a family-grouped capability shape in
that domain's vocabulary. A pool's shapes MUST come from exactly one source, in this
precedence:

1. The storefront's override for that site and pool, when it states shapes.
2. Otherwise, the pool's own `listing_shapes` hint for the listing's offering mode.
3. Otherwise, the domain's default shape generator.

A stated list MUST replace the lower sources as a whole. How many of a shape a pool can serve
MUST be derived from its capacity declarations, and MUST NOT be declared or published.

**The VM default.** The VM domain's default generator MUST yield, for each GPU model among a
pool's enabled members, one shape per GPU count from one to the largest declared GPU count
among that model's members. Each such shape MUST declare the GPU family only. Every VM shape
MUST name a GPU count and a GPU model. A fungible pool MUST publish one listing per feasible
shape. A specific-resource pool MUST publish one listing per member per shape that member is
feasible for.

**Commitment.** A listing MUST publish every quantity and attribute its shape declares,
flattened through the domain's schema, and MUST NOT publish a quantity its shape does not
declare. The capacity claim built from a listing MUST request exactly its shape's quantities.
A listing commits only to what its shape declares. For a dimension its shape omits it makes
no commitment, and what is provisioned for that dimension is the site's to decide.

#### Scenario: A site declares shapes for a pool

- **WHEN** a pool's projected `listing_shapes` hint lists two VM shapes and the storefront
  has no override for that site and pool
- **THEN** the storefront publishes one listing per feasible shape, each carrying its shape's
  GPU count, GPU model, and every other declared quantity, and publishes no default shapes
  for the pool

#### Scenario: The storefront replaces a pool's shapes

- **WHEN** the storefront's override for a site and pool states one shape while the pool's
  hint states two
- **THEN** only the override's shape is published for that pool

#### Scenario: A pool states no shapes

- **WHEN** neither the storefront's override nor the pool's hint states shapes for a pool
  whose enabled members all declare one GPU model
- **THEN** the pool publishes one listing per GPU count its members make feasible, each
  carrying GPU count and model and no other dimension, as its listings did before shapes

#### Scenario: A pool's members declare different GPU models

- **WHEN** a fungible pool without stated shapes holds members declaring two different GPU
  models
- **THEN** the default generator yields each model's GPU counts as separate shapes, and each
  listing names the model of the members that are feasible for it

#### Scenario: A shape omits memory

- **WHEN** a VM shape declares GPU count, GPU model, and vCPU count but no memory family
- **THEN** its listing publishes no `ram_gb`, its capacity claim requests no memory, and any
  memory provisioned for the resulting VM is the site's to decide

#### Scenario: Eight single-GPU VMs from one host

- **WHEN** a fungible pool whose one member declares eight GPUs lists a one-GPU shape
- **THEN** the storefront publishes one listing for that shape, and successive reservations
  against it each reserve one GPU and the shape's other quantities until the member cannot
  admit another

### Requirement: A listing shape is published only where a source member is feasible for it

A shape MUST be publishable only where a member of its source satisfies the capacity claim
its listing would produce under the site authority's exported resource-feasibility
predicate:

- for a fungible pool, some single enabled member;
- for a specific-resource pool, that member.

**Declared and available capacity.**
- Feasibility MUST be judged against the member's declared capacity.
- For a capacity-backed listing the shape MUST additionally be feasible against current
  availability. For a fungible pool that availability is sourced from grouped capacity data
  when it has loaded for the site, and otherwise from the member's own projected
  availability.
- A member whose availability is not reported is unknown rather than empty and MUST be judged
  on its declared capacity.
- An unbacked listing MUST be judged on declared capacity alone.

**Feasibility is not admission.** Publication does not establish that a reservation will be
admitted; the site authority's reservation remains the final admission boundary. A published
listing MAY be refused at reservation for a reason the resource-feasibility predicate does not
evaluate, such as the pool provider's host requirement, holds over the requested lease
window, or a physical-host conflict.

**When no member is feasible.**
- A stated shape that no member is feasible for MUST yield no listing and MUST be reported in
  the storefront's system status, naming the site, the pool, the shape, and what was not
  feasible.
- A default shape that no member is feasible for against declared capacity MUST be reported
  once per pool, naming the claim attribute that no enabled member declares. A default shape
  that fails only against current availability MUST NOT be reported.
- Publication MUST NOT shrink a shape to make it feasible, and MUST NOT substitute another
  source's shapes for a stated list with an infeasible shape.
- A pool whose shape hint the domain cannot read MUST yield no new listing, MUST be reported,
  and its existing listings MUST be held rather than closed.

The seller's inventory guard MUST apply the same feasibility check to a listing's declared
match.

#### Scenario: An override names a model the pool does not have

- **WHEN** a storefront override lists a shape whose GPU model no enabled member of the pool
  declares
- **THEN** no listing is published for that shape and system status reports it, naming the
  model as what was not feasible

#### Scenario: A declaration shrinks beneath a published shape

- **WHEN** a member's declared memory falls below the memory of a shape published from it
  and no other member is feasible for the shape
- **THEN** the listing closes through source reconciliation and the infeasible shape is
  reported

#### Scenario: A backed shape's memory is taken

- **WHEN** a capacity-backed shape's GPUs are free on a member but the member's available
  memory is below the shape's
- **THEN** the shape is not publishable from that member

#### Scenario: A pool's region exists only as a pool hint

- **WHEN** a pool's `region` is stated only in its `region` hint and none of its enabled
  members declares a `region` attribute
- **THEN** the pool publishes no listing, and system status reports once for the pool that no
  member declares the claimed region

#### Scenario: A published listing is refused at reservation

- **WHEN** a listing is published because a member is feasible for its shape, and the site
  refuses the reservation for a reason feasibility does not evaluate
- **THEN** the refusal stands, and publication is not treated as having guaranteed admission

#### Scenario: A pool's shape hint cannot be read

- **WHEN** a pool's `listing_shapes` hint for the VM mode contains a family or field outside
  the VM vocabulary
- **THEN** no new listing is derived from the pool, its existing listings are held, the pool
  does not fall back to the default generator, and system status reports the problem

### Requirement: A listing's derivation identity includes its shape

**Identity.**
- Every listing's derivation identity MUST include a canonical digest of its shape, taken
  over the family-grouped form rather than the flattened field names, whichever source
  produced the shape.
- Its durable binding MUST record the shape in the current source envelope version.
- A stored listing's derivation identity MUST be read from its binding rather than
  recomputed from its published fields.
- A change to a pool's shapes MUST therefore close listings under a withdrawn shape and
  publish listings under a new one.

**Listings bound before shapes.** A listing bound under the earlier envelope, which carries
no shape, MUST NOT be reopened, and while open MUST close through source reconciliation.

**Seller state carries across.** Before any lifecycle loop runs, the storefront MUST carry a
seller's close and a seller's pause from each such listing to the listing bound for its
equivalent default shape:
- a listing its seller closed MUST have its successor bound closed by its seller and
  unpublished;
- a paused listing MUST have its successor bound paused.

The carry-over MUST be idempotent.

#### Scenario: A shape is edited

- **WHEN** a pool's only listed shape changes its memory from 64 to 96 GiB
- **THEN** the listing for the 64 GiB shape closes and a listing with a distinct derivation
  key is published for the 96 GiB shape, leaving the original binding row unmodified

#### Scenario: A site declares the shape its pool published by default

- **WHEN** a pool publishing a default one-GPU shape gains a `listing_shapes` hint stating
  exactly that shape
- **THEN** the listing keeps its derivation key and is neither closed nor republished

#### Scenario: A storefront upgrades

- **WHEN** a storefront whose listings were bound before shapes starts for the first time
  with shapes
- **THEN** each open earlier listing closes once and a listing for its equivalent shape
  publishes under a shape-bearing derivation key

#### Scenario: A seller-closed listing crosses the upgrade

- **WHEN** a listing its seller closed was bound before shapes
- **THEN** after upgrade the listing for its equivalent default shape is closed by its
  seller, is not published, and no reconciliation reopens it until the seller does

#### Scenario: A paused listing crosses the upgrade

- **WHEN** an open, paused listing was bound before shapes
- **THEN** after upgrade the listing for its equivalent default shape is paused and withheld
  from registries until the seller resumes it

### Requirement: Storefront pool overrides are site-scoped and durable

A storefront's per-pool overrides MUST be stored durably, keyed by site, pool, and offering
mode. Each override belongs to exactly one offering mode and MUST be validated by the market
that serves that mode; a write for a mode no market serves MUST be refused. An override MAY
state its market's commercial terms, settlement clauses, and listing shapes. An override
MUST NOT state region or capacity backing, and its offering mode MUST NOT be defaulted. A field an override leaves unset MUST fall
through to the next precedence tier. Listing shapes and settlement clauses MUST each replace
the lower tier's list as a whole, and an empty shape list or an empty settlement-clause list
MUST be refused.

Within the storefront-override tier, a value in the site-scoped store MUST take precedence
over the home-site legacy override record. While a legacy value is in effect for a pool, the
storefront's system status MUST report it, naming each field whose value came from the legacy
record.

Every listing-derivation path that computes a listing's derivation identity, including
source reconciliation and the inventory guard, MUST resolve the override tier, so that
publication and reconciliation derive the same listings.

An override MUST outlive the projection of its pool. The storefront's system status MUST
report every stored override in exactly one state, judged against the projection its
listings are derived from:

- `inactive` when listings derive from local tables, where no override applies;
- `site_unconfigured` when the storefront does not configure the override's site;
- `unknown` when the site is configured but no projection of it is held;
- `orphaned` when the projection derived from holds no such pool;
- `applied` otherwise.

A site with no projection held MUST NOT make an override `orphaned`, because the pool's
absence is not known. An orphaned override has no effect. When its pool returns, the
override MUST apply again.

#### Scenario: One pool is overridden for two offering modes

- **WHEN** overrides are stored for the same site and pool under two offering modes
- **THEN** each applies only to that mode's listings and is validated by that mode's market

#### Scenario: No market serves the override's mode

- **WHEN** an administrator writes an override for an offering mode no installed market
  serves
- **THEN** the write is refused without contacting the site and nothing is stored

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

#### Scenario: A site's projection has not loaded

- **WHEN** an override names a configured site whose projection the storefront has never
  loaded
- **THEN** system status reports the override as unknown rather than orphaned, and nothing
  is closed or published for it

#### Scenario: Listings derive from local tables

- **WHEN** a storefront deriving listings from its local tables accepts an override write
  whose pool its site's live projection contains
- **THEN** the override is stored, no listing changes, and system status reports it as
  inactive

#### Scenario: An override shapes a pool's listings

- **WHEN** an override states a shape for a pool and a publication cycle has published it
- **THEN** a later capacity reconciliation derives the same listing and does not close it

### Requirement: Storefront pool overrides are written against the site's live projection

A storefront MUST expose authenticated administrator operations to replace, read, list, and
delete a pool override. They MUST address the site, pool, and offering mode in the request
body or query rather than the path, and MUST bind them into the signed resource with an
unambiguous encoding. Replacement MUST replace the whole record. Deletion MUST be idempotent.

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

A shape no member of the live projection is feasible for MUST NOT cause refusal. The
response MUST report feasibility per shape against that live projection and identify the projection generation it
used. After accepting a write, the storefront MUST cause its cached projection of that site
to refresh and its publication loop to run, without writing the live result into the cache
itself. A failed refresh MUST NOT fail the accepted write.

#### Scenario: The pool is unknown to the site

- **WHEN** an administrator writes an override for a pool the site's live projection does
  not contain, while the storefront's cached projection still lists it
- **THEN** the write is refused and nothing is stored

#### Scenario: The site is unreachable

- **WHEN** an administrator writes an override while the named site cannot be reached
- **THEN** the write is refused as retryable, naming the site as unavailable rather than the
  pool as unknown

#### Scenario: An override's shape is feasible nowhere

- **WHEN** an administrator writes an override whose only shape no member of the live
  projection is feasible for
- **THEN** the override is stored, the response reports the shape as infeasible, and
  the next publication cycle publishes no listing for it

#### Scenario: A shape outside the vocabulary

- **WHEN** an administrator writes an override whose shape names a family or field the
  domain does not define
- **THEN** the write is refused without contacting the site

### Requirement: A site whose projection is not held holds its listings

A storefront that derives listings from site projections MUST treat a configured site whose
resource-pool projection holds no value as unknown, not empty: every listing derived from
that site MUST be held, neither closed nor refreshed, until the site's projection holds a
value. Such a storefront MUST NOT derive listings from its local tables because no site's
projection is held.

#### Scenario: The storefront starts while a site is unreachable

- **WHEN** a storefront with open listings from a site restarts while that site cannot be
  reached, and a publication cycle runs
- **THEN** those listings stay open, and none is closed as having lost its source

#### Scenario: No site's projection is held

- **WHEN** no configured site's projection holds a value and a publication cycle runs
- **THEN** no listing is derived from the storefront's local tables and no listing is
  closed

#### Scenario: The site returns

- **WHEN** the unknown site's projection loads
- **THEN** its listings are reconciled against it as usual

## MODIFIED Requirements

### Requirement: A listing's published shape comes from its source declaration

A listing's published compute shape is its listing shape, and whether that shape is published
is decided against its source declaration, for capacity-backed and unbacked listings alike.
Nothing in publication verifies that shape against hardware, and this requirement makes no
claim that it does.

Derivation MUST NOT substitute a value for a quantity a declaration does not carry. A
declaration that omits the quantity a domain's default shapes are enumerated by MUST yield no
listing, and the omission MUST be reported to the operator naming the declaration. A
declaration that declares that quantity as zero MUST yield no listing without a
report. A declaration whose quantity is malformed, or a projected member that does not state its
resource kind, MUST be treated as unresolvable and reported:
it yields no new listing and its existing listings are held. In a fungible pool one
unresolvable member holds every listing derived from the pool, because which shapes its
members are feasible for cannot be decided without it; in a specific-resource pool it holds
only its own.

Where a listing is capacity-backed, whether its shape is published additionally follows the
availability its site projects, so a pool's published set moves as capacity is reserved and
released. An unbacked fungible pool's default shapes range up to the largest single
member's declared quantity, never a sum across members, because a reservation would land on
one member. A listing's own quantities never move: availability decides only whether it is
published. An unbacked listing has no availability to bound it and no reservation consumes
it; that difference is carried by the listing's published backing and MUST NOT be encoded a
second time in a separate published field.

#### Scenario: A declaration omits the enumerated quantity

- **WHEN** a source declaration carries no GPU count
- **THEN** no VM listing is derived from it, listings previously derived from it close, and the operator is told which declaration omits it

#### Scenario: A declaration declares zero

- **WHEN** a source declaration declares a GPU count of zero
- **THEN** no VM listing is derived from it and no report is made

#### Scenario: An unbacked listing's published quantity does not move

- **WHEN** any number of buyers settle against an unbacked listing
- **THEN** its published quantity is unchanged, because no reservation consumes it

#### Scenario: A listing's quantities do not follow availability

- **WHEN** reservations consume part of a capacity-backed member from which a listing is
  published, and the member is still feasible for its shape
- **THEN** the listing stays open with its quantities unchanged
