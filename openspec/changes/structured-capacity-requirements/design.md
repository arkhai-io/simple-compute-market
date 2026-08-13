# Design

## Discuss phase (2026-08-01)

This section preserves the alternatives considered during POOLS-7 Section
11's code review, where these questions first came up. Nothing here is
implemented; this is discussion carried forward into its own change so it
isn't lost, re-derived, or silently dropped when Section 11 closes.

### Nested requirements shape vs. flat dimensions

**Rejected:** putting categorical fields inside `dimensions`:

```json
{"dimensions": {"gpu": {"model": "A100", "count": 4}}}
```

`dimensions` has one clean invariant today: every value is quantitative,
matched by sufficiency (`available >= requested`). Mixing in `model`
(matched by equality) means the matcher must know, per nested field,
which comparison applies — the name `dimensions` no longer describes
the contract it holds.

**Accepted direction:** a `requirements` object grouped by hardware
family, with each family's own schema defining which of its fields are
quantitative and which are categorical:

```json
{
    "requirements": {
        "gpu": {"count": 4, "model": "A100"},
        "cpu": {"count": 16},
        "memory": {"gib": 64},
        "storage": {"gib": 200}
    }
}
```

**Important scoping decision, reached after the initial proposal:** this
nested shape does not eliminate the type-awareness problem — it
relocates it one level down (something still has to know `gpu.count` is
quantitative and `gpu.model` isn't). The resolution is that this is
fine, *as long as it's resolved before reaching the generic matcher*: a
domain-layer parser (the natural evolution of
`compute_capacity_claim_from_order`) decomposes `requirements` into the
existing flat `dimensions`/`attributes` split before calling
`capacity.probe`/`reserve`. The generic matching contract
(`resource_satisfies_requirement`, `dict_resource_satisfies_claim`)
never needs to understand nested, per-family semantics — it keeps
working exactly as POOLS-7 Section 11.2 left it.

### Symmetric nesting: inventory description matches the requirement shape (2026-08-04)

**Question raised while starting `pools-8-capacity-projection-and-listing-hints`'s work on
projecting GPU model into `site_resource_pools`:** should a site's own resource/inventory
description (what a site *has*) be shaped the same way as a buyer's `requirements` (what a
buyer *wants*), given they're the two sides of the exact same match?

**Investigated before deciding, not assumed:** traced `kit/site/src/market_site/ledger.py`'s
actual matching contract (`resource_satisfies_requirement`, `dict_resource_satisfies_claim`,
`_split_claim_requirement`) directly. Confirmed two things:

1. Both `required_dimensions`/`required_attributes` (claim side) and `resource.available`/
   `resource.attributes` (resource side) are flat dicts today, compared by plain key lookup
   (`resource.attributes.get(key) == value`, `resource.available.get(dimension, 0) < amount`).
2. The claim side already has a flattening step (`_split_claim_requirement`) and this
   change's own accepted direction above gives it a second one (nested `requirements` →
   flat `dimensions`/`attributes`). **The resource side has no flattening step at all
   today** -- `dict_resource_satisfies_claim` reads `row.get("attributes")` straight off the
   wire snapshot, unmodified.

**Accepted direction:** yes, align them, but through a **shared flattening utility**, not by
nesting one side and leaving the other flat. A resource's capabilities get expressed in the
same family-grouped shape a requirement does:

```json
{
    "gpu": {"count": 4, "model": "A100"},
    "cpu": {"count": 16},
    "memory": {"gib": 64},
    "storage": {"gib": 200}
}
```

and **one** shared utility -- not two independently-maintained flatteners -- converts either
a `requirements` object or a resource's capability description into the existing flat
`dimensions`/`attributes` split, using the same per-family quantitative/categorical schema
either way. This directly answers this document's own "Unresolved questions" entry about
where the `requirements` parser should live: it answers it for the resource side too, at the
same time, rather than deciding the two independently and risking two different answers.

**Why not nest the resource side without adding a matching flatten step (the naive
version):** that would make the resource side *look* symmetric with the claim side while
staying mechanically different underneath -- the claim gets flattened before matching, the
resource wouldn't, so the two still wouldn't actually go through the same logic. That is the
"unnecessary transformer" outcome, just relocated rather than avoided. The whole point of
sharing one utility is that a reviewer can look at `requirements.gpu.model` and a resource's
`gpu.model` and see they are the literal same field path, flattened by the literal same
function, compared by the same unmodified generic matcher -- not two vocabularies that
happen to agree by convention.

**Flattening convention (derived from what's already in live use, not invented fresh):**
family-prefixed flat keys -- `gpu.count` -> `dimensions["gpu_count"]`,
`gpu.model` -> `attributes["gpu_model"]`, `memory.gib` -> `dimensions["memory_gib"]`, and so
on. This isn't a new vocabulary choice: `gpu_count` is already a real, live column/key name
today (`Host.gpu_count`, `compute_pool_members.gpu_count`). Choosing this convention means
existing flat data already sitting in that shape needs no migration once the shared utility
lands -- it's already in the post-flatten form the utility would produce.

**Practical consequence for work landing before this change is implemented:** any inventory
field added ahead of the shared utility (e.g. `pools-8-capacity-projection-and-listing-hints`
projecting GPU model) should be added in its **already-flattened** form (a flat
`attributes["gpu_model"]` key), not a premature one-off nested shape with no flattening logic
behind it. A flat key added this way requires no transformation later -- it's already exactly
what the eventual utility would produce. A nested key added ahead of the utility would be a
straight regression against today's matcher (which reads flat keys directly) until that
specific field's flattening was implemented, and would need to be reconciled with whatever
schema the shared utility eventually defines for that family.

**Where the shared utility likely lives, not yet finalized:** probably `kit/site`, alongside
the existing matching contract it feeds -- the same dependency-direction question already
flagged in "Unresolved questions" below for the claim-side parser applies identically here,
since it would now be one function serving both call sites rather than two.

**Second coordination point with `pools-8-capacity-projection-and-listing-hints`, this one on the config/pricing side rather than the wire/inventory side (added 2026-08-05, once `pools-8`'s own Section 6 landed):** that change's storefront-side pricing configuration
(`[pricing.defaults.gpu.<model>]`, resolved through a three-tier storefront-override →
pool-hint → config-default precedence for VM's own per-GPU-model pricing) adopted this
change's family-grouped vocabulary proactively for the `gpu` family alone, structurally
reserving `.cpu`/`.memory`/`.storage` for later without implementing them. This is a real,
one-directional dependency: extending that pricing config beyond the `gpu` family needs this
change's own vocabulary to have actually landed and stabilized first, since a
`cpu`/`memory`/`storage` shape decided independently there could disagree with whatever this
change ultimately settles on. Nothing in `pools-8` depends on this change landing before its
own `gpu`-only scope can proceed; this is a forward-compatibility bet on this change's
direction, not a blocking prerequisite. Whoever implements this change's own `requirements`
shape should check `pools-8`'s pricing config (`domains/vms/storefront/src/market_storefront/settings.toml`'s
`[pricing.defaults.gpu]` section, `domains/vms/listings/pricing_resolution.py`) as a second,
independent precedent for the family-grouped convention, alongside the `gpu_count`/`gpu_model`
flattening convention already described above -- both should end up consistent with whatever
this change finalizes, not treated as two separate shapes to reconcile after the fact.

### Third coordination point: rates nest inside the family shape (2026-08-06)

`capacity-shape-pricing` carries a per-dimension rate as a **field of each capability
family**, next to what it describes -- a `gpu` family holding its model, its count, and
its per-card-hour rate together -- rather than in a parallel rate-keyed map alongside
the shape. Its `design.md` records why: a parallel map is a second structure keyed by
the same families, so a family present in one and absent from the other is
representable and meaningless.

That makes rates the **third** consumer of the family-grouped shape this change
settles, after requirements (what a buyer wants) and inventory capabilities (what a site
has). The shared flattening utility accepted above therefore has a third call site, and
this change's vocabulary decision now constrains pricing configuration as well as the
wire and inventory shapes.

The one-directional dependency recorded above for `pools-8`'s
`[pricing.defaults.gpu.<model>]` applies with more force: `capacity-shape-pricing` is
the change that extends that configuration beyond the `gpu` family, and its task list
says to stop and coordinate rather than choose a `cpu`/`memory`/`storage` shape
independently if this change has not landed.

One known discrepancy to reconcile here rather than in either pricing change: the
registry filter vocabulary and buyer CLI already use `ram_gb` and `disk_gb`, while the
flattening convention above would suggest `memory_gib` and `storage_gib`.
`publish-multidimensional-listing-shape` publishes into the existing wire names
deliberately and defers the reconciliation to this change, on the grounds that
introducing a third spelling would make reconciliation harder.

### `resource_type` vs. a buyer-facing offering concept

Three distinct concepts were conflated under `resource_type` in the
original Section 11.2 implementation:

1. **Market/product type** — what the buyer is purchasing: VM, bare
   metal, Kubernetes pod, API credits.
2. **Requested resource shape** — CPUs, memory, GPUs, storage, network.
3. **Provider inventory representation** — the site's own internal
   adapter/record kind: `compute.gpu`, `token.erc20`,
   `information.note`, `api_credits`.

`resource_type` as it exists today (`kit/site`'s
`_split_claim_requirement`'s `required_resource_kind`, and Section
11.2's `_VM_RESOURCE_TYPE = "compute.gpu"` constant) is concept 3 — a
site-internal inventory-adapter discriminator. The buyer should not need
to know a VM site models capacity through a `compute.gpu` adapter; a
site might satisfy an `offering_type: "vm"` request from several
internal resource rows (host CPU capacity, host RAM capacity, GPU
capacity, VM quota capacity) without the buyer ever seeing
`resource_type` at all.

**Naming alternatives considered for the new, separate concept:**
`market_type`, `fulfillment_type`, `offering_type`. `offering_type` is
preferred: it describes what the buyer is purchasing without overloading
"domain" (an internal repository-layering term) or "resource type" (the
existing inventory-adapter term).

**Open question, not yet resolved:** whether `offering_type` needs to be
a real wire field at all. If a storefront can only ever reach
domain-matching site endpoints (true today — VM's storefront never talks
to a bare-metal site), the domain boundary itself already establishes
the type, and repeating it inside the claim may be unnecessary. It only
becomes load-bearing once a single aggregate capacity authority serves
multiple offering types through one endpoint. Confirm which architecture
is actually true before implementing this field.

### Vocabulary rename: cheap part vs. expensive part

Proposed staged rename, evaluated for cost before committing to it:

1. Rename local variables (`required_attributes` → `capacity_claim`)
   immediately, wherever touched — zero blast radius, since these never
   leave the function they're declared in.
2. Design `ResourceRequirement`/`requirements` (this change) before
   renaming anything wire- or storage-level, so the vocabulary doesn't
   get renamed twice.
3. Introduce the new stored/wire field with explicit compatibility
   handling once §1's shape is settled.
4. Remove the old `"required_attributes"` name only after every
   persisted/resume path has migrated.

Step 1 already happened during POOLS-7 Section 11.7.5 (confirmed: the
local variable in `vm_job_spec_service.py` is renamed; the wire key
`"required_attributes"` is untouched, correctly, since it's real
external/persisted surface — checked its full blast radius: admin API
request/response bodies, `fulfillment_resume_runtime.py`'s durable
resume context, and `core/storefront-client`'s external client library).
Steps 2–4 are this change's job.

## Unresolved questions

- Does `capacity.probe(requirement=...)` replace or sit alongside
  `capacity.probe(claim=...)`? A pure rename has no behavior change but
  touches every caller; an additive parameter avoids that but leaves two
  names for the same concept indefinitely.
- Should `ResourceFeasibilityView`-style matching ever become a
  `core`-layer concept, given `core/storefront`'s `CapacityClient`
  protocol is meant to be backend-agnostic? (Answered narrowly for
  Section 11.2's specific bug already — no, injection at the domain
  composition layer is correct, not a `core` promotion — but the
  question may recur as more domains need exact matching.)
- Where does the domain-layer `requirements` → `dimensions`/`attributes`
  parser live for a second domain (bare-metal, apicredits) once VM has
  one? A shared kit-layer parser is tempting but needs the same
  dependency-direction scrutiny Section 11.2 already applied to
  `ResourceFeasibilityView`. **Narrowed, not resolved, by the
  symmetric-nesting decision above (2026-08-04):** whatever the answer
  is, it now has to be one function serving both the claim/requirement
  side and the resource/inventory side identically -- the dependency-
  direction question is the same one, just with an added constraint
  that the answer can't special-case either caller.
- **New (2026-08-04):** the per-family quantitative/categorical schema
  (which leaf keys are which, per family) needs a concrete home and
  shape of its own -- referenced by the symmetric-nesting decision above
  but not yet designed. Likely small (a dict/registry keyed by family
  name), but not yet written down.

## Design promotion record

Not started. No decisions in this document are implemented yet.
