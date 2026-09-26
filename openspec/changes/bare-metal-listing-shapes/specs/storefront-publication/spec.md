## ADDED Requirements

### Requirement: A bare-metal listing's shape is derived from its declaration

Every bare-metal listing MUST carry a family-grouped capability shape derived from the
capacity declaration of the Physical Resource it offers, through the compute-family schema
and the shared capability-shape utility:

- its quantities MUST be the declared capacity dimensions other than `units`;
- its attributes MUST be the declared attributes the schema names;
- no other declared attribute is shape input.

A declaration that cannot be read this way MUST be treated as unresolvable: it yields no new
listing, its existing listing is held, and the publication run reports it naming the
declaration. That covers:

- a capacity dimension outside the schema;
- a quantity that is not a positive integer;
- a missing GPU count or GPU model;
- a `units` dimension other than exactly one.

Publication-only data the site copies into the bare-metal view MUST NOT be a source of shape
fields.

A bare-metal listing MUST NOT read a pool's `listing_shapes` hint. A pool stating one for
bare metal MUST be reported as not applicable.

#### Scenario: A Physical Resource declares its hardware

- **WHEN** a Physical Resource declares capacity `{units: 1, gpu_count: 8, ram_gb: 2048}` and
  the attribute `gpu_model: H200`
- **THEN** its listing's shape is `{gpu: {count: 8, model: H200}, memory: {gib: 2048}}`

#### Scenario: Two Physical Resources declare the same dimensions

- **WHEN** two Physical Resources in one pool declare identical dimensions
- **THEN** each publishes its own listing, and both listings carry the same shape

#### Scenario: A declaration names no GPU model

- **WHEN** a Physical Resource declares a GPU count but no `gpu_model` attribute
- **THEN** no listing is derived from it, any listing previously derived from it is held,
  and the run names the declaration and the missing field

#### Scenario: Hardware stated only for publication

- **WHEN** a declaration states its GPU model only inside its bare-metal publication
  configuration
- **THEN** that value is not published, the declaration is unresolvable for its missing
  model, and the run reports the ignored publication field

### Requirement: A bare-metal listing publishes its shape where the compute schema reads it

A bare-metal listing MUST publish its shape's quantities and attributes as top-level fields
of the listing resource under the compute family's flat names, so that the compute
registry schema's dimension filters evaluate bare-metal listings as they evaluate VM
listings.

It MUST publish `region` from its pool's `region` hint. A pool with no non-empty string
region hint MUST be held: its resources yield no new listing, its existing listings are
neither closed nor refreshed, and the run reports the pool.

A bare-metal listing MUST NOT publish its hardware in a nested mapping beside the top-level
fields.

#### Scenario: A buyer filters compute supply by GPU model

- **WHEN** a buyer queries a compute registry for a GPU model that a published bare-metal
  listing's Physical Resource declares
- **THEN** the bare-metal listing is returned

#### Scenario: A buyer filters by GPU count

- **WHEN** a buyer queries a compute registry for listings with at least eight GPUs
- **THEN** a bare-metal listing whose Physical Resource declares eight GPUs is returned

#### Scenario: A pool states no region

- **WHEN** a pool advertising bare metal carries no region hint
- **THEN** no bare-metal listing is published from it and the run reports the pool

### Requirement: A bare-metal listing's derivation identity includes its shape

A bare-metal listing's derivation identity MUST be its site, pool, Physical Resource, and a
canonical digest of its shape taken over the family-grouped form, and its durable binding
MUST record the shape digest. A Physical Resource anchors at most one open listing at a time.
A change to its declared shape MUST close its listing and publish a listing under a new
derivation key, leaving the original binding unmodified.

A listing bound under a derivation identity that carries no shape digest matches no
candidate, and MUST close through source reconciliation. It MUST NOT be reopened.

#### Scenario: A declared dimension is corrected

- **WHEN** a Physical Resource behind an open listing changes its declared memory from
  1024 to 2048
- **THEN** that listing closes and a listing with a distinct derivation key publishes for
  the new shape

#### Scenario: A storefront upgrades

- **WHEN** a bare-metal storefront whose listings were bound without a shape digest runs
  publication
- **THEN** each such open listing closes as a withdrawn source and a listing for the same
  Physical Resource publishes under a shape-bearing derivation key in the same run

### Requirement: A bare-metal listing sells one whole unit

A bare-metal listing MUST be held by exclusive allocation of one unit of its Physical
Resource. Its capacity claim MUST request exactly one `units` and MUST carry its shape's
attributes, so that admission matches the published attributes. Its shape's quantities
describe what that unit contains, and MUST NOT be requested dimension by dimension.

The claimed attributes MUST come from the storefront's trusted record of the accepted
listing, never from buyer input.

#### Scenario: A declaration changes model after acceptance

- **WHEN** a buyer accepts a bare-metal listing published with `gpu_model: H200`, and its
  Physical Resource's declaration is changed to another model before reservation
- **THEN** the site refuses the reservation

### Requirement: Bare-metal opening rechecks its listing against its source

Before a bare-metal seller agrees terms, the storefront MUST re-derive the listing's shape
and region from its own site's live resource-pool projection, at its bound pool and
Physical Resource. It MUST refuse with a declared-match reason when any of these hold:

- the shape digest differs from the binding's;
- the region differs from the published region;
- the Physical Resource is absent or disabled.

It MUST refuse as retryable when the site cannot be reached or does not verify.

#### Scenario: A declaration shrinks beneath its listing

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose Physical Resource now
  declares fewer GPUs than it published
- **THEN** the opening is refused with a declared-match reason

### Requirement: Bare metal joins the site-scoped pool-override store

A bare-metal storefront MUST contribute a market vocabulary for the `bare_metal` offering
mode to the site-scoped pool-override store, and MUST serve the same authenticated
administrator operations, through the same signed-resource contract, as every storefront
that serves overrides.

The bare-metal vocabulary is:

- settlement clauses;
- the terms `min_duration_seconds` and `max_duration_seconds`.

A bare-metal override MUST NOT state listing shapes. An override's settlement clauses
replace the storefront's configured publication clauses for that site's pool, and its
duration bounds replace the configured bounds.

A bare-metal storefront's command line MUST offer the same replace, read, list, and delete
operations through its administrator API, with the offering mode never defaulted, and MUST
NOT read or write its database to do so.

A bare-metal storefront MUST record durably, for each site, the last resource-pool projection
generation a publication run accepted, whichever process ran it, and its override status MUST
be judged against that generation. A site with no recorded generation is `unknown`.

#### Scenario: A bare-metal override is written

- **WHEN** an operator writes an override for a pool at a configured site in the
  `bare_metal` offering mode
- **THEN** bare metal validates it, and it applies only to that site's pool's bare-metal
  listings

#### Scenario: A bare-metal override states a shape

- **WHEN** an operator writes a `bare_metal` override that states listing shapes
- **THEN** the write is refused without contacting the site

#### Scenario: An operator writes a bare-metal override from the command line

- **WHEN** an operator runs the bare-metal storefront's override command with a record for
  the `bare_metal` mode
- **THEN** the command sends it through the administrator API, which checks it against
  the site's live projection, and prints the stored override

#### Scenario: Publication runs from the command

- **WHEN** an operator runs `bare-metal-storefront publish` in its own process and the run
  accepts a site's generation holding the override's pool
- **THEN** the running storefront reports the override as applied

#### Scenario: Status before the first run

- **WHEN** a bare-metal storefront reports override status before any publication run has
  accepted a generation for the override's site, including after a restart that follows
  no run
- **THEN** the override is reported as unknown

## MODIFIED Requirements

### Requirement: Every VM listing is a listing shape

Every VM listing MUST be a listing shape: a family-grouped capability shape in the compute
family's vocabulary. A bare-metal listing's shape is derived from its Physical Resource's
declaration rather than chosen, and is governed by the bare-metal requirements below. API-credit
listings are not listing shapes. A pool's VM
shapes MUST come from exactly one source, in this precedence:

1. The storefront's override for that site and pool, when it states shapes.
2. Otherwise, the pool's own `listing_shapes` hint for the listing's offering mode.
3. Otherwise, the VM domain's default shape generator.

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
used. After accepting a write, a storefront that caches site projections MUST cause its
cached projection of that site to refresh, without writing the live result into the cache
itself, and a storefront that runs a publication loop MUST cause it to run. A failed refresh
MUST NOT fail the accepted write. A storefront whose publication is operator-invoked applies
an accepted write at its next publication run.

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

#### Scenario: A bare-metal override is accepted between runs

- **WHEN** an administrator writes an override for a bare-metal pool while no publication
  run is in progress
- **THEN** the write is stored and reported without starting a run, and the next
  operator-invoked run publishes under it
