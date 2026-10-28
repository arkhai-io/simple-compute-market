## MODIFIED Requirements

### Requirement: A listing's published shape comes from its source declaration

A listing's published compute shape is derived from the shape its source declaration carries,
and a VM listing's is its listing shape; whether it is published is decided against its source
declaration, for capacity-backed and unbacked listings alike.
Nothing in publication verifies that shape against hardware, and this requirement makes no
claim that it does.

Derivation MUST NOT substitute a value for a quantity a declaration does not carry. A
declaration that omits the quantity a domain's default shapes are enumerated by (for VM, the
GPU count) MUST yield no default shape, and a declaration that declares that quantity as zero
likewise yields none; neither is reported on its own account. A VM member that declares no
GPUs remains a member: it is judged for every shape its pool states, like any other member.
A pool that states no listing shapes and none of whose enabled members declares a positive
GPU count MUST yield no listing and MUST be reported once in the storefront's system status,
naming the site and pool and saying that the VM default generates GPU shapes only and that the
pool must state its listing shapes. A declaration whose quantity is malformed, or a projected
member that does not state its resource kind, MUST be treated as unresolvable and reported:
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

- **WHEN** a pool states no listing shapes and one of its enabled members declares a GPU
  count and model while another carries no GPU count
- **THEN** the default shapes come from the GPU member, and nothing is reported about the
  member that carries no GPU count

#### Scenario: A pool whose members declare no GPUs states no shapes

- **WHEN** a pool states no listing shapes and none of its enabled members declares a GPU
  count
- **THEN** no VM listing is derived from it, listings previously derived from its default
  shapes close, and system status reports the pool once, saying it must state its listing
  shapes

#### Scenario: A declaration declares zero

- **WHEN** a source declaration declares a GPU count of zero
- **THEN** it yields no default shape and no report is made about it

#### Scenario: An unbacked listing's published quantity does not move

- **WHEN** any number of buyers settle against an unbacked listing
- **THEN** its published quantity is unchanged, because no reservation consumes it

#### Scenario: A listing's quantities do not follow availability

- **WHEN** reservations consume part of a capacity-backed member from which a listing is
  published, and the member is still feasible for its shape
- **THEN** the listing stays open with its quantities unchanged

### Requirement: Every VM listing is a listing shape

Every VM listing MUST be a listing shape: a family-grouped capability shape in the compute
family's vocabulary. A bare-metal listing's shape is derived from its Physical Resource's
declaration rather than chosen, and is governed by the bare-metal requirements below. API-credit
listings are not listing shapes. A pool's VM
shapes MUST come from exactly one source, in this precedence:

1. The storefront's override for that site and pool, when it states shapes.
2. Otherwise, the pool's own `listing_shapes` hint for the listing's offering mode.
3. Otherwise, the VM domain's default shape generator.

A stated list MUST replace the lower sources as a whole, together with any constraints its
shapes carry. A stated shape MAY carry constraints inline on its quantity fields; the
listing's shape is the stated shape's base shape, which holds each field's offer, and its
constraints govern only admissibility (see "A VM listing's admissibility resolves per
listing"). How many of a shape a pool can serve MUST be derived from its capacity
declarations, and MUST NOT be declared or published.

**The VM default.** The VM domain's default generator MUST yield, for each GPU model among a
pool's enabled members, one shape per GPU count from one to the largest declared GPU count
among that model's members that the storefront's configured default admits for that model,
choosing those counts from the admissibility kit's admissible values rather than generating
and filtering. With no configured default every such count is admitted. Each such shape MUST
declare the GPU family only, and a member declaring no GPU count and model yields none. A VM
shape MAY state no GPUs; a shape stating no GPUs is published only from a stated list. A
fungible VM pool MUST publish one listing per feasible shape. A specific-resource VM pool MUST
publish one listing per member per shape that member is feasible for.

**Commitment.** A VM listing MUST publish every quantity and attribute its shape declares,
flattened through the domain's schema, and MUST NOT publish a quantity its shape does not
declare. The capacity claim built from a VM listing MUST request exactly its shape's
quantities. A VM listing commits only to what its shape declares. For a dimension its shape
omits it makes no commitment, and what is provisioned for that dimension is the site's to
decide. A constraint on a dimension its shape omits commits nothing on that dimension. A
bare-metal listing commits differently: it sells one whole unit held exclusively,
and its shape describes what that unit contains (see "A bare-metal listing sells one whole
unit").

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
  whose enabled members all declare one GPU model, and the storefront configures no
  default constraint
- **THEN** the pool publishes one listing per GPU count its members make feasible, each
  carrying GPU count and model and no other dimension, as its listings did before shapes

#### Scenario: The default generator meets a configured default

- **WHEN** a pool states no listing shapes, its members hold 8 GPUs, and the storefront's
  configured default bounds `gpu.count` to at most 4
- **THEN** the default generator yields shapes of 1 to 4 GPUs and nothing is reported

#### Scenario: A pool's members declare different GPU models

- **WHEN** a fungible pool without stated shapes holds members declaring two different GPU
  models
- **THEN** the default generator yields each model's GPU counts as separate shapes, and each
  listing names the model of the members that are feasible for it

#### Scenario: A shape omits memory

- **WHEN** a VM shape declares GPU count, GPU model, and vCPU count but no memory family
- **THEN** its listing publishes no `ram_gb`, its capacity claim requests no memory, and any
  memory provisioned for the resulting VM is the site's to decide

#### Scenario: A pool states a shape with no GPUs

- **WHEN** a pool's hint states `{cpu: {count: 16}, memory: {gib: 64}}` and a member without
  GPUs is feasible for it
- **THEN** its listing publishes `vcpu_count: 16` and `ram_gb: 64` and no GPU field, and its
  capacity claim requests vCPUs and memory and no GPU

#### Scenario: A GPU host's spare capacity sells as a VM without GPUs

- **WHEN** a pool states a shape with no GPUs and its only member is a GPU host whose
  declared vCPU and memory fit the shape
- **THEN** the shape is published from that member, and its reservations consume the host's
  vCPU and memory and none of its GPUs

#### Scenario: A stated shape carries constraints

- **WHEN** a pool's hint states a shape with `gpu.count` `{offer: 1, max: 4}` and
  `memory.gib` `{max: 512}`
- **THEN** its listing publishes a GPU count of 1 and no `ram_gb`, and its capacity claim
  requests one GPU and no memory

#### Scenario: Eight single-GPU VMs from one host

- **WHEN** a fungible pool whose one member declares eight GPUs lists a one-GPU shape
- **THEN** the storefront publishes one listing for that shape, and successive reservations
  against it each reserve one GPU and the shape's other quantities until the member cannot
  admit another

### Requirement: A bare-metal listing's shape is derived from its declaration

Every bare-metal listing MUST carry a family-grouped capability shape derived from the
capacity declaration of the Physical Resource it offers, through the compute-family schema
and the shared capability-shape utility:

- its quantities MUST be the declared capacity dimensions other than `units`;
- its attributes MUST be the declared attributes the schema names;
- no other declared attribute is shape input.

A machine without GPUs declares no GPU count and no GPU model, and its shape states no GPUs.

A declaration that cannot be read this way MUST be treated as unresolvable: it yields no new
listing, its existing listing is held, and the publication run reports it naming the
declaration. That covers:

- a capacity dimension outside the schema;
- a quantity that is not a positive integer, including a GPU count of zero;
- a GPU count without a GPU model, or a GPU model without a GPU count;
- a declaration stating no dimension other than `units`;
- a `units` dimension other than exactly one.

Publication-only data the site copies into the bare-metal view MUST NOT be a source of shape
fields.

A bare-metal listing MUST NOT read a pool's `listing_shapes` hint. A pool stating one for
bare metal MUST be reported as not applicable.

#### Scenario: A Physical Resource declares its hardware

- **WHEN** a Physical Resource declares capacity `{units: 1, gpu_count: 8, ram_gb: 2048}` and
  the attribute `gpu_model: H200`
- **THEN** its listing's shape is `{gpu: {count: 8, model: H200}, memory: {gib: 2048}}`

#### Scenario: A Physical Resource declares no GPUs

- **WHEN** a Physical Resource declares capacity `{units: 1, vcpu_count: 64, ram_gb: 512}` and
  no GPU model
- **THEN** its listing's shape is `{cpu: {count: 64}, memory: {gib: 512}}`, and the listing
  publishes no GPU field

#### Scenario: Two Physical Resources declare the same dimensions

- **WHEN** two Physical Resources in one pool declare identical dimensions
- **THEN** each publishes its own listing, and both listings carry the same shape

#### Scenario: A declaration names no GPU model

- **WHEN** a Physical Resource declares a GPU count but no `gpu_model` attribute
- **THEN** no listing is derived from it, any listing previously derived from it is held,
  and the run names the declaration and the missing field

#### Scenario: A declaration states only the machine

- **WHEN** a Physical Resource declares capacity `{units: 1}` and nothing else
- **THEN** no listing is derived from it, and the run names the declaration

#### Scenario: Hardware stated only for publication

- **WHEN** a declaration states its GPU model only inside its bare-metal publication
  configuration
- **THEN** that value is not published, the declaration is unresolvable for its missing
  model, and the run reports the ignored publication field

### Requirement: A bare-metal listing sells one whole unit

A capacity-backed bare-metal listing MUST be held by exclusive allocation of one unit
of its Physical Resource. Its capacity claim MUST request exactly one `units` and MUST
carry exactly the attributes its shape states, so that admission matches the published
attributes; a shape stating no attribute yields a claim carrying none, which still selects
its Physical Resource. Its shape's quantities describe what that unit contains, and MUST NOT
be requested dimension by dimension. An unbacked bare-metal listing constructs no capacity
claim.

The claimed attributes MUST come from the storefront's trusted record of the accepted
listing, never from buyer input. A trusted record that carries no claimed attributes at all,
rather than an empty set of them, MUST refuse the claim.

#### Scenario: A declaration changes model after acceptance

- **WHEN** a buyer accepts a capacity-backed bare-metal listing published with
  `gpu_model: H200`, and its Physical Resource's declaration is changed to another model
  before reservation
- **THEN** the site refuses the reservation

#### Scenario: A machine without GPUs is reserved

- **WHEN** a buyer accepts a capacity-backed bare-metal listing whose shape states no
  attribute
- **THEN** its claim requests one `units` of its Physical Resource with no attribute, and the
  site admits it

#### Scenario: An unbacked listing is accepted

- **WHEN** a buyer accepts an unbacked bare-metal listing
- **THEN** no capacity claim is constructed
