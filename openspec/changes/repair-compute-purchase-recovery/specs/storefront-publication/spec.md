## MODIFIED Requirements

### Requirement: A listing's published shape comes from its source declaration

A listing's published compute shape is derived from the shape its source declaration carries,
and a VM listing's is its listing shape; whether it is published is decided against its source
declaration, for capacity-backed and unbacked listings alike.
Nothing in publication verifies that shape against hardware, and this requirement makes no
claim that it does.

Derivation MUST NOT substitute a value for a quantity a declaration does not carry. A
declaration that omits the quantity a domain enumerates listings by (for VM, the quantity its
default shapes are enumerated by) MUST yield no listing from that enumeration, and the
omission MUST be reported to the operator naming the declaration. A VM declaration that omits
it remains a member of its pool for the shapes the pool states, and is judged for each stated
shape on the quantities that shape declares. A
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

- **WHEN** a source declaration carries no GPU count and its pool states no shapes
- **THEN** no VM listing is derived from it, listings previously derived from it close, and the operator is told which declaration omits it

#### Scenario: A declaration without GPUs serves a stated shape

- **WHEN** a source declaration carries no GPU count and its pool states a shape without GPUs that its declared vCPU, memory, and storage are feasible for
- **THEN** a listing is derived for that shape from it

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
declare the GPU family only, so the default generator yields nothing for a pool whose
members declare no GPU. A stated VM shape MAY omit the GPU family, describing a VM
without GPUs; a VM shape that states the GPU family MUST name both its count and its
model. A shape without the GPU family commits to no GPU: its listing publishes no GPU
count or model, its capacity claim requests no GPU, and its fulfillment provisions no
GPU. A listing whose shape names no GPU model MUST resolve its terms and family rates
from the storefront's override, the pool's flat hint fields, and the flat configured
default alone; no per-GPU-model term or rate applies to it. A fungible
VM pool MUST publish one listing per feasible shape. A specific-resource VM pool MUST publish
one listing per member per shape that member is feasible for.

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

#### Scenario: A pool states a shape without GPUs

- **WHEN** a pool's `listing_shapes` hint states a VM shape with `cpu`, `memory`, and
  `storage` and no `gpu` family, and a member's declared capacity is feasible for it
- **THEN** the storefront publishes one listing for it, carrying its vCPU count,
  `ram_gb`, and `disk_gb` and no GPU count or model, and its capacity claim requests
  exactly those quantities

#### Scenario: A shape without GPUs is priced

- **WHEN** a storefront configures per-GPU-model terms and rates, and a pool states a
  VM shape with no `gpu` family
- **THEN** that shape's listing takes its terms and family rates from the flat tiers
  alone, and no per-GPU-model term or rate is applied to it

#### Scenario: A stated shape names a GPU count without a model

- **WHEN** a stated VM shape gives the `gpu` family a count and no model
- **THEN** the shape is unreadable, the pool's listings are held, and system status
  reports it
