<!-- This change was `structured-capacity-requirements` until 2026-09-25. Its two
larger items — a family-grouped, buyer-facing requirement shape with a shared
flattening utility, and a buyer-facing offering concept separate from the site's
inventory discriminator — landed through other changes (`kit/capability-shape` and
`VM_CAPABILITY_SCHEMA` from `publish-multidimensional-listing-shape`; `offering_mode`
from `settle-listing-vocabulary`). Its symmetric-nesting decision for the site's
resource side was invalidated by `capacity-resource-administration`. What remains is
vocabulary: two wire renames and a canonical term table. `design.md` records the
history and the invalidation. -->

## Why

Three names on the capacity-claim path say something other than what they hold, and
each was deferred to this change by the work that noticed it.

1. **`required_attributes` holds an entire claim.** The storefront persists and
   publishes the VM capacity claim — `offering_mode`, `resource_type`, `pool_id` or
   `resource_id`, `gpu_model`, `region`, and a `dimensions` map — under a key named
   for its categorical half: the admin settle API's request and response bodies
   (`admin_controller.py`, `admin_settle_service.py`), the fulfillment plan
   (`vm_fulfillment_service.py`, `vm_fulfillment_planner.py`), the **durable resume
   context** (`fulfillment_resume_runtime.py`, persisted across restarts), and
   `core/storefront-client`. `kit/site`'s own `required_attributes` is the
   categorical half and is correctly named; the storefront key is the only wrong one.
   A reader who knows the site vocabulary reads the storefront key as "attributes"
   and misses the dimensions inside it.
2. **The flat dimension names are a recorded exception.** `VM_CAPABILITY_SCHEMA`
   flattens `memory.gib` to `ram_gb` and `storage.gib` to `disk_gb` because those
   were the wire names when it landed, and `publish-multidimensional-listing-shape`
   deferred the reconciliation here rather than introduce a third spelling. The
   family-prefixed convention (`memory_gib`, `storage_gib`, `cpu_count`) is what a
   reader of the family form expects and what a second compute domain would produce.
   Whether the rename is worth its blast radius is a decision this change owes, not
   a task it prescribes.
3. **`probe(claim=)` and the term table.** The claim/requirement vocabulary was
   proposed in 2026-08 and never written down permanently. It is settled below in
   favor of `claim` as the name of what `probe`/`reserve` take, so the open question
   whether `probe(requirement=)` should exist is closed: it should not.

## What Changes

- Rename the storefront's persisted and published `required_attributes` claim key to
  `capacity_claim`, on every surface listed above, with the durable resume context
  read under both names for one release and written under the new one. Pre-1.0
  APIs may break; the admin settle body and the client change in one step with a
  client version bump.
- Decide, as a gate, whether the VM flat dimension names become family-prefixed
  (`vcpu_count` → `cpu_count`, `ram_gb` → `memory_gib`, `disk_gb` → `storage_gib`).
  If taken: the schema rows, the published `listing_resource`, the compute registry
  filter specification (a `filter-spec` bump, as `settle-listing-vocabulary` did),
  the buyer CLI and query examples, capacity declarations at VM sites, and the claim
  dimension keys, with the site's declaration keys migrated in place. If not taken:
  the schema's flat names are recorded as permanent VM vocabulary rather than an
  exception.
- Promote the term table: `ResourceRequirement`/capability shape (the
  family-grouped form a buyer or a listing states), `CapacityClaim` (what
  `probe`/`reserve` take: the flattened `dimensions`/`attributes`/`resource_type`
  plus identity), `CapacityReservation` (unchanged), `dimensions` (quantitative,
  sufficiency-matched), `attributes` (categorical, equality-matched).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None by requirement text unless the dimension rename is taken; then
`site-capacity` (its multidimensional example), `registry-discovery` and
`cli-query-language` (the filter names), `storefront-publication` (the listing
shape scenario), and `market-composition` (its flattening example) each gain a
delta naming the new spellings.

## Non-Goals

- Do not change `kit/site`'s admission semantics, `resource_satisfies_requirement`,
  or the `dimensions`/`attributes` split.
- Do not express the site's resource side in the family-grouped form. Capacity
  declarations are flat and domain-neutral by design (`capacity-resource-administration`);
  the family form is domain vocabulary, and the site must not learn it.
- Do not change how a buyer states a shape on the wire; whether round 0's
  `compute_resource` adopts the family form is `negotiation-driven-capacity-resize`'s
  question.
- Do not touch `offering_mode`, which is settled and required on the claim wire.

## Impact

- `required_attributes` rename: ten storefront and client files, the durable resume
  context's read path, and every test constructing a plan or a settle body.
- Dimension rename, if taken: fourteen non-test files across `kit/site`
  (examples only), `core/registry`, `core/buyer`, the VM buyer CLIs, listings,
  storefront, and domain; the registry `filter-spec`; and persisted VM capacity
  declarations.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the vocabulary table gains the claim
      terms.
- [x] Existing subsystem specification — `openspec/specs/site-capacity/architecture.md`
      for the `dimensions`/`attributes` invariant and why the family form does not
      weaken it; the specs above only if the dimension rename is taken.
- [ ] New subsystem specification — none.
- [ ] No permanent documentation change — not applicable.

### Knowledge to promote

- The claim term table — `docs/development/ARCHITECTURE.md`'s vocabulary.
- The `dimensions`/`attributes` invariant and its relation to the family-grouped
  form — `openspec/specs/site-capacity/architecture.md`.
- The decision on the flat dimension spelling, either way —
  `openspec/specs/market-composition/architecture.md` beside the capability-shape
  rationale.

## Dependencies and Related Changes

- Continues `structured-capacity-requirements` (2026-08-01 to 2026-09-25); see
  `design.md` for what that change's direction became and where it landed.
- `capacity-shape-pricing` no longer depends on this change; the family vocabulary
  it needed is `VM_CAPABILITY_SCHEMA`.
- `negotiation-driven-capacity-resize` owns whether round 0's buyer shape adopts
  the family form.
- The dimension rename, if taken, must land before `bare-metal-listing-shapes`
  chooses bare metal's flat names, or after it with both domains renamed together.
