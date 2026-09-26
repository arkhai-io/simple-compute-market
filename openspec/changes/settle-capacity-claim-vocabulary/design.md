# Design

## Context

- `kit/capability-shape` (`market_capability_shape`: `CapabilitySchema`,
  `ShapeField`, `flatten_shape`, `shape_digest`) defines the family-grouped
  capability shape and its schema-driven flattening; `VM_CAPABILITY_SCHEMA`
  (`arkhai_vms.compute_requirements`) instantiates it for the VM families `gpu`,
  `cpu`, `memory`, `storage`. Listing shapes and pool overrides use it; the flat
  names it produces are the claim dimension keys the site matches.
- Capacity declarations at the site are flat and domain-neutral: a declaration
  holds exactly the dimensions it names, and no domain's declaration carries
  another domain's dimension name. The site does not know any family schema.
- `offering_mode` is a required field on the claim wire, distinct from
  `resource_type`, the site's inventory-adapter discriminator.
- `kit/site`'s claim is split into `required_dimensions` (quantitative,
  sufficiency-matched) and `required_attributes` (categorical, equality-matched);
  `capacity.probe(claim=...)` and `reserve(claim=...)` take the whole claim.
- The VM storefront persists and publishes the whole claim under the key
  `required_attributes`: the admin settle API (`admin_controller.py`,
  `admin_settle_service.py`), the fulfillment plan (`vm_fulfillment_service.py`,
  `vm_fulfillment_planner.py`), the durable resume context
  (`fulfillment_resume_runtime.py`), `capacity_admin_models.py`,
  `vm_fulfillment_models.py`, `core_storefront`'s `settle_models.py`, and
  `storefront_client`.
- `VM_CAPABILITY_SCHEMA`'s flat names `vcpu_count`, `ram_gb`, and `disk_gb`
  appear in the published `listing_resource`, the compute registry's
  `filter-spec` (`ram_gb_min` and siblings), the buyer CLI's query language and
  examples, persisted VM capacity declarations at sites, and the claim
  dimension keys the scheduler reads — fourteen non-test files.

## Decisions

### `claim` is the name of what `probe` and `reserve` take

`CapacityClaim` is the flattened request — `dimensions`, `attributes`,
`resource_type`, `offering_mode`, and the pool or resource identity — and is
what `probe(claim=...)` and `reserve(claim=...)` already accept. A
`requirement=` parameter would be a second name for the same thing on the same
surface. The family-grouped form a buyer or a listing states is a *capability
shape*; a domain flattens it into a claim. No signature changes.

### The storefront key becomes `capacity_claim`

The persisted and published key holds a whole claim, so it takes the claim's
name. The rename is one step across the admin settle body, the fulfillment
plan, the resume context, and the client, with a client version bump; pre-1.0
APIs may break. The resume context is the one durable surface: it is read
under both names for one release and written under the new one, so a
storefront restarting mid-fulfillment across the upgrade resumes.

`kit/site`'s `required_attributes` (the categorical half of a claim, beside
`required_dimensions`) is correctly named and untouched.

### The site's resource side is not expressed in the family form

Rejected alternative: nesting capacity declarations in the same family form the
shapes use, flattened by the same utility, so that the two sides are symmetric
by construction. The site would have to import a domain schema to nest a
declaration, which inverts the dependency direction (the site is domain-neutral
by contract), and the symmetry that matters already holds: the VM schema's
flat names are the declaration keys, so a shape flattens to exactly what a
declaration states.

### The flat dimension spelling is a gate, not a task

The blast radius is larger than a vocabulary change: the published
`listing_resource`, the registry `filter-spec` (a version bump and registry
redeploy), the buyer CLI's query language and examples, persisted VM capacity
declarations, and the scheduler's claim keys. Against that: a reader of the
family form sees `memory.gib` flatten to `ram_gb` and has to be told it is
deliberate, and a second compute domain (`bare-metal-listing-shapes` is
choosing its flat names) inherits the exception or diverges from it.

Task 2.1 decides it with the bare-metal shape work in view and records the
answer permanently either way. If taken, it lands as one coordinated rename
across both domains rather than VM first.

## Migration

- `required_attributes` → `capacity_claim`: additive read of the old key in the
  resume context for one release; every writer switches at once; the old read
  is removed in the following release.
- Dimension rename, if taken: the VM schema's flat names change; a startup
  migration at VM sites renames the keys of persisted declarations; the
  registry `filter-spec` bumps and refuses the retired spellings at the publish
  boundary, as the retired `listing_mode` spellings are refused.

## Open questions

None. The dimension spelling is a decision gate in `tasks.md`, not an open
question.
