# Design

## Where the original direction went (2026-08-01 to 2026-09-25)

This change opened as `structured-capacity-requirements`, carrying three design
questions out of POOLS-7 Section 11's review. Their fate:

| Item | Outcome |
|---|---|
| A family-grouped `requirements` shape, with each family's schema saying which fields are quantities and which attributes, flattened before the generic matcher | **Landed** as `kit/capability-shape` (`market_capability_shape`: `CapabilitySchema`, `ShapeField`, `flatten_shape`, `shape_digest`) and `arkhai_vms.compute_requirements.VM_CAPABILITY_SCHEMA`, through `publish-multidimensional-listing-shape` (archived 2026-09-25). The generic matcher is unchanged, as this design required. It is used today for listing shapes and pool overrides; a buyer's proposed shape uses the same form under `negotiation-driven-capacity-resize`. |
| The site's resource side expressed in the same family form, through the same flattening utility ("symmetric nesting", 2026-08-04) | **Invalidated.** `capacity-resource-administration` (archived 2026-09-21) made capacity declarations flat and domain-neutral on purpose: a declaration holds exactly the dimensions it names, and no domain's declaration carries another's dimension name. The family form is domain vocabulary — the site would have to import a domain schema to nest it, which is the dependency direction the original design already flagged as suspect. The two sides still meet on the same flat names; that is the symmetry that matters, and it holds by construction because the VM schema's flat names are the declaration keys. |
| `offering_mode` as a buyer-facing concept separate from the site's `resource_type` discriminator | **Landed** through `settle-listing-vocabulary` (archived 2026-09-15): `offering_mode` is on the claim wire, required, and `resource_type` keeps its inventory-adapter meaning beside it. The open question "does it need to exist on the wire" was answered yes by `site-capacity`'s "Requested offering mode is explicit and bounded by the pool". |
| Canonical claim vocabulary and the `required_attributes` wire-key rename | **Remains here.** |
| `probe(requirement=)` versus `probe(claim=)` | **Decided here**: `claim`. |
| The family-prefixed flat spelling (`memory_gib`, `storage_gib`) versus today's `ram_gb`/`disk_gb` | **Remains here, as a gate.** Deferred to this change by `publish-multidimensional-listing-shape` so that a third spelling was not introduced. |

The alternatives considered in 2026-08 — nesting categorical fields inside
`dimensions` (rejected: breaks the one clean invariant `dimensions` has), and the
naming candidates `market_type`/`fulfillment_type`/`offering_mode` — are recorded in
the archived `publish-multidimensional-listing-shape` and `settle-listing-vocabulary`
designs respectively, which took the decisions.

## Decisions

### `claim` is the name of what `probe` and `reserve` take

`CapacityClaim` is the flattened request — `dimensions`, `attributes`,
`resource_type`, `offering_mode`, and the pool or resource identity — and it is what
`capacity.probe(claim=...)` and `reserve(claim=...)` already accept. A
`requirement=` parameter would be a second name for the same thing on the same
surface. The family-grouped form a buyer or a listing states is a *capability
shape*; a domain flattens it into a claim. No signature changes.

### The storefront key becomes `capacity_claim`

The persisted and published key holds a whole claim, so it takes the claim's name.
The rename is one step across the admin settle body, the fulfillment plan, the
resume context, and the client, with a client version bump; pre-1.0 APIs may break.
The resume context is the one durable surface: it is read under both names for one
release and written under the new one, so a storefront restarting mid-fulfillment
across the upgrade resumes.

`kit/site`'s `required_attributes` (the categorical half of a claim, beside
`required_dimensions`) is correctly named and untouched.

### The flat dimension spelling is a gate, not a task

The blast radius is larger than a vocabulary change: the published
`listing_resource`, the compute registry's `filter-spec` (`ram_gb_min` and its
siblings, so a version bump and registry redeploy), the buyer CLI's query language
and examples, VM capacity declarations already persisted at sites, and the claim
dimension keys the scheduler reads. Against that: a reader of the family form sees
`memory.gib` flatten to `ram_gb` and has to be told it is deliberate, and a second
compute domain (`bare-metal-listing-shapes` is choosing its names now) inherits the
exception or diverges from it.

Task 2.1 decides it with the bare-metal shape work in view, and records the answer
permanently either way. If taken, it lands as one coordinated rename across both
domains rather than VM first.

## Migration

- `required_attributes` → `capacity_claim`: additive read of the old key in the
  resume context for one release; every writer switches at once; the old read is
  removed in the following release.
- Dimension rename, if taken: the VM schema's flat names change; a startup
  migration at VM sites renames the keys of persisted declarations; the registry
  `filter-spec` bumps and refuses the retired spellings at the publish boundary, as
  `settle-listing-vocabulary` did for `listing_mode`.

## Open questions

None. The dimension spelling is a decision gate in `tasks.md`, not an open question.
