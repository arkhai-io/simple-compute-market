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
declare the GPU family only. Every VM shape MUST name a GPU count and a GPU model. A fungible
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

## ADDED Requirements

### Requirement: A VM listing's admissibility resolves per listing

The VM storefront SHALL resolve each listing's admissibility policy from two tiers, highest
first: the constraints its stated shape carries, from whichever source stated it, and the
storefront's configured default for the VM mode, `[admissibility.defaults.vm]` in the
listing shape's family nesting and field syntax, which states no offer. Absent and empty
both mean no default. It SHALL split each
stated shape and resolve the tiers through the admissibility kit with the VM domain's
schema, labelling each tier, and SHALL NOT read a constraint itself. Under the `min`/`max`
merge a listing MAY replace a configured default's value, including with a wider one, and
SHALL NOT remove it. A generated shape's policy SHALL be the configured default alone. A
field no tier constrains SHALL NOT be constrained by admissibility. An override's shapes
SHALL NOT merge with the hint's constraints. The resolved policy is the storefront's own;
site admission is not changed by it. A malformed configured default SHALL prevent the
storefront from starting. The storefront SHALL parse the configured default once and
supply the same declaration to publication, the default generator, and the override
write check.

#### Scenario: A listing narrows the configured default

- **WHEN** the configured default bounds `gpu.count` from 1 to 16 and a stated shape gives
  `gpu.count` `{offer: 1, max: 4}`
- **THEN** that listing's resolved range for `gpu.count` is 1 to 4

#### Scenario: A listing widens the configured default

- **WHEN** a stated shape states a larger maximum for a field than the configured default
- **THEN** the stated shape's maximum applies

#### Scenario: The configured default fills a field the listing leaves unconstrained

- **WHEN** a stated shape does not constrain `memory.gib` and the configured default does
- **THEN** the configured default's bound applies to `memory.gib` for that listing

#### Scenario: An override's shape does not inherit the hint's constraints

- **WHEN** the pool's hint constrains `gpu.count` on its shapes and the storefront's
  override states a shape that constrains nothing
- **THEN** the override's listing is constrained only by the configured default

#### Scenario: No tier constrains a field

- **WHEN** no tier states a constraint for a field
- **THEN** admissibility does not constrain that field

### Requirement: A VM listing whose admissibility cannot be computed closes

The storefront SHALL read a stated list's base shapes before its constraints. Where any
entry's base shape cannot be read with the VM domain's schema, including because a
constraint mapping without an offer removed a required field, the list is unreadable and
the pool SHALL keep the existing hold. Where every base shape can be read but a listing's
constraints cannot — a constraint on an attribute or an undefined field, or a key the
storefront's kit does not define — or its tiers resolve to an empty range, or its base
shape is stated twice with different constraints, the storefront cannot compute its own policy for that
listing and SHALL fail closed for it alone: it SHALL NOT publish the listing, SHALL close
an open listing for it, and SHALL continue to publish the pool's other listings. A pool
whose base shapes cannot be read SHALL keep the existing hold. The storefront SHALL report
the tier, the path, and the problem, each tier's conflicting value, or each conflicting
entry, per site in its derivation report served by system status. Entries identical in
base shape and constraints SHALL collapse to one listing and SHALL NOT be reported.

#### Scenario: A listing's range merges empty

- **WHEN** a stated shape gives `gpu.count` a maximum of 2 and the configured default a
  minimum of 4
- **THEN** that listing closes, the pool's other listings are published, and the report
  names both tiers and values

#### Scenario: A listing carries a constraint key the storefront does not know

- **WHEN** a stated shape's constraint mapping holds a key the storefront's kit does not
  define
- **THEN** that listing closes, the pool's other listings are published, and the report
  names the path and the key

#### Scenario: A listing constrains a required attribute

- **WHEN** a stated shape gives `gpu.model` a constraint mapping
- **THEN** the base shape lacks its required model, no new listing is derived from the
  pool, its existing listings are held, and the report names `gpu.model`

#### Scenario: A listing constrains a required quantity without offering it

- **WHEN** a stated shape gives `gpu.count` `{min: 2, max: 8}` with no `offer`
- **THEN** no new listing is derived from the pool, its existing listings are held, and
  the report names `gpu.count` as required

#### Scenario: A listing constrains a field the VM domain does not define

- **WHEN** a stated shape with a readable base shape gives `memory.foo` a constraint
  mapping with no `offer`
- **THEN** that listing closes, the pool's other listings are published, and the report
  names `memory.foo`

#### Scenario: A list states one base shape with different constraints

- **WHEN** a stored list holds `gpu.count` `{offer: 1, max: 4}` and `{offer: 1, max: 8}`
  for the same model
- **THEN** that listing closes, the pool's other listings are published, and the report
  names both entries

#### Scenario: A pool's base shapes cannot be read

- **WHEN** a pool's `listing_shapes` hint for the VM mode names a family outside the VM
  vocabulary
- **THEN** no new listing is derived from the pool and its existing listings are held

### Requirement: VM publication never advertises an inadmissible offer

A stated shape whose base shape is inadmissible under its resolved policy SHALL NOT be
published, an open listing for it SHALL close, and the storefront SHALL report it per site
with its source tier and problems. Generated shapes SHALL NOT be reported. A listing's
derivation identity SHALL be taken over its base shape, so a change to its constraints
alone SHALL NOT change its identity; reconciliation SHALL re-evaluate the listing against
its current policy. Asking rates SHALL be matched against the base shape. A storefront pool
override write for the VM mode SHALL be refused, before the site is called and without
changing the stored override, when one of its shapes' base shape or constraints cannot be
read with the VM domain's schema, its list states one base shape twice with different
constraints, or one of its shapes resolves to an empty range against the configured
default or leaves its offer inadmissible.

#### Scenario: A configured default excludes a stated offer

- **WHEN** a pool's hint states a shape offering 8 GPUs and the configured default bounds
  `gpu.count` to at most 4
- **THEN** that shape is not published, an open listing for it closes, and it is reported
  with its tier and problems

#### Scenario: Constraints change after publication

- **WHEN** a published listing's constraints change and its offer stays admissible
- **THEN** the listing keeps its identity and stays open

#### Scenario: Constraints tighten past a published offer

- **WHEN** a pool's constraints change so that a published listing's offer is inadmissible
- **THEN** the next reconciliation closes that listing

#### Scenario: An override's constraint merges empty

- **WHEN** a storefront administrator writes an override whose shape gives `gpu.count` a
  maximum below the configured default's minimum
- **THEN** the write is refused, the site is not called, and the stored override is
  unchanged

#### Scenario: An override states one base shape with different constraints

- **WHEN** a storefront administrator writes an override whose list states one base shape
  twice with different constraints
- **THEN** the write is refused naming both entries, and the stored override is
  unchanged

#### Scenario: An override states a shape with an unreadable constraint

- **WHEN** a storefront administrator writes an override whose shape constrains
  `gpu.model`
- **THEN** the write is refused naming the path, and the stored override is unchanged
