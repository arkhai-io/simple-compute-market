# Design

## Context

Re-verified against the code on 2026-09-24, and again after design review the same day.
Several facts recorded when this change was first written had moved; the corrected
picture is below, and the decisions that follow depend on it.

**Publication today.**

- The storefront publication loop (`publication_loop.py`) calls
  `publication_terms.listing_resource_for_candidate`, which calls
  `vm_listing_resource_for_listing` (`domains/vms/domain/src/arkhai_vms/storefront_adapter.py`).
  It publishes `pool_id`, `gpu_model`, `gpu_count`, `sla`, `region`, `offering_mode`, and
  `capacity_backing`, plus `resource_id` for a specific-resource candidate and the
  interruptible markers. `offering_mode` and `capacity_backing` are already published.
- Candidates are built by `_projected_pool_rows` and `_projected_resource_usage` in
  `domains/vms/listings/reconciler.py`. `_projected_resource_usage` reads only
  `capacity["gpu_count"]`. Every pool enumerates GPU-count slices from 1 up to its largest
  single member's available (backed) or declared (unbacked) count. `cli_publish.py` no
  longer builds listings, and `_publishable_slices` no longer exists.
- The reconciler's structural key is `(site, pool, gpu_count)` for a fungible pool and
  `(site, resource, gpu_count)` for a specific resource. The durable binding's source
  envelope is `compute.listing_source` schema version 1 with the same fields, and the
  binding's derivation key is a digest over that envelope
  (`core_storefront.domain_registry.build_storefront_derivation_key`).
- The resource-pool projection is built from capacity declarations alone
  (`provisioning/compute/service/src/compute_provisioning_service/services/capacity_inventory.py`).
  Each member carries a declared `capacity` map, an optional per-dimension `available`
  map computed by the site ledger, and its declared `attributes`, including `gpu_model`.
  The `_project_host` fallback the original proposal cited is gone.

**What a published dimension does downstream.**

- `compute_capacity_claim_from_order` copies every dimension in `arkhai_vms.DIMENSION_KEYS`
  found on `listing_resource` into the claim's `dimensions`. Site admission debits every
  requested dimension from the matched resource.
- Fulfillment derives the VM's shape from the reservation's committed dimensions.
  `VmManagementV1RequirementDelegate` translates `ram_gb` to MiB by multiplying by 1024
  and `disk_gb` to `<n>G`; a dimension absent from the reservation falls back to the pool's
  provisioning defaults. `ram_gb` and `disk_gb` are therefore GiB in practice.
- `AnsibleFulfillmentProvider` builds a VM from the translated committed dimensions and
  falls back to the pool's `default_vm_ram`, `default_vm_vcpus`, and `default_vm_disk_size`
  for any dimension the reservation omits. Nothing reports the defaults back, and the
  capacity ledger does not debit them.
- The VM buyer sends no `compute_resource` in its provision terms, so the round-0
  shape-mismatch guard does not fire for a buyer accepting a listing's own shape.

**Site admission is more than resource feasibility.**

- `dict_resource_satisfies_claim` reproduces the site's resource-requirement predicate:
  resource kind, dimensions, and exact attributes.
- `CapacityLedgerService._find_candidate` checks more before it admits:
  - that the site's configured required attributes are present;
  - that the pool declares the requested offering mode;
  - the pool provider's host requirement;
  - holds over the requested lease window;
  - physical-host conflicts.
- The resource-pool projection deliberately omits host connection data, so a storefront
  cannot reproduce all of that.
- `capacity_bucket_projection` groups resources by pool, resource type and subtype, their
  complete per-dimension `available` map, and their grouping attributes, which include
  `gpu_model`. Buckets therefore answer multidimensional availability per model.

**Discovery.**

- `core/registry/filter-spec.yaml` accepts `vcpu_count`, `ram_gb`, and `disk_gb` on
  `listing_resource`, with range filters that carry `on_missing: fail`.
- Buyers filter with the typed resource query (`--resource 'ram_gb>=64'`); the
  `--vcpu-min`/`--ram-gb-min`/`--disk-gb-min` flags this change first cited no longer exist.
  A listing that omits a dimension is excluded by any filter on it.

**Listing identity and commitment.** The rules `unbacked-listing-publication` adopted are
permanent (`openspec/specs/storefront-publication/spec.md`, "A listing's identity is the
physical resource it offers"). `compare_listing` ignores identity fields the stored listing
does not publish, and `refreshed_listing_resource` keeps the stored identity, so a refresh
never adds a field. `listing_comparison.IDENTITY_FIELDS` already names `vcpu_count`,
`ram_gb`, and `disk_gb` as a literal. `slice_identity`, which the inventory guard and the
availability reopen use, omits them.

**Storefront overrides today.** The storefront's per-pool override values are the
commercial columns of the local `compute_capacity_pools` table. It is keyed by `pool_id`
alone, and derivation consults it only for pools at the storefront's home site, the first
configured site, so that one site's pool IDs cannot collide with another's. Its only writer
is the resource import that `pools-9-retire-local-physical-authority` retires. There is no
administrator API for it. The same row also carries physical bookkeeping: its `status`
becomes `deleted` when the pool's local GPU count reaches zero.

**The administrator surface and the projection cache** (verified before Slice B,
2026-09-24).

- Every administrator route that signs operator-chosen strings percent-encodes each one
  with no safe characters: `identity_subject_resource` and `identity_status_resource`
  (`core_storefront.identity_lifecycle`), the query-routed status and event resources in
  `middleware/admin_identity.py`, and the client's `_query_resource` and
  `_rotation_resource`. `arkhai-core-storefront-client` depends only on `httpx` and
  `arkhai-kit-identity`.
- The client has authenticated `POST`, `GET`, and `PATCH` helpers, and no `PUT` or `DELETE`.
- `site_projection_cache.load_site_projections` replaces every site's caches with new ones,
  built through its own `build_capacity_client` rather than the composed capacity runtime.
  Each `ProjectionCache` can instead refresh itself in place (`refresh(force=True)`).
- Publication, capacity reconciliation, and the inventory guard select their source through
  `capacity_client.listing_source_projection()`. It returns `None` when derivation reads
  local tables. Otherwise it maps each site whose resource-pool cache holds a value, loaded
  or stale, to that value. A site that has never loaded, or whose load failed without an
  earlier value, is absent: unknown, not empty.
- On the projection path, the per-row `gpu_model` and commercial fields `_projected_pool_rows`
  resolves, including the legacy row's `gpu_model` fallback, are read only by that
  function's own unit tests. Every candidate takes its terms from `pricing_by_model`, keyed
  by its shape's model.

**Adjacent work.**

- `pools-8-capacity-projection-and-listing-hints` task 3.5 made per-pool VM size defaults
  settable and projects them as `pool_views["vm.ansible_pool_defaults.v1"]`, "so a storefront
  can resolve a full four-dimension shape at negotiation time". No storefront code reads the
  view.
- `capacity-shape-envelope` (not implemented) puts per-dimension admissibility bounds in
  pool policy tags, with kit code free of dimension names.
- `structured-capacity-requirements` (design phase) accepts a family-grouped capability shape
  (`gpu: {count, model}`, `cpu: {count}`, `memory: {gib}`, `storage: {gib}`) flattened by one
  shared utility into flat dimensions and attributes, and asks that fields added before the
  utility exists use the already-flattened form.
- The end-to-end VM scenarios declare `{"gpu_count": N}` only
  (`e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`).

**Seller-owned listing state.** A listing its seller closed stays closed against every
reconciliation, and no replacement binds under its derivation identity. A paused open
listing refuses new negotiations and is withheld from registries until resumed. Both states
belong to a listing ID.

## Goals / Non-Goals

**Goals:**

- Every VM listing is a listing shape.
- A site administrator and a storefront administrator can each state which shapes a pool
  is listed in, and the storefront's choice wins. Otherwise the domain's default shape
  generator reproduces today's listings.
- A listing commits to, publishes, and reserves exactly the quantities its shape declares,
  and nothing else.
- No listing publishes a shape that none of its source's members is feasible for.
- Storefront overrides are durable, scoped to a site and pool, and administered through an
  authenticated API.
- Nothing this change stores or keys on needs rework when `structured-capacity-requirements`
  lands, or when pool-assigned shape generators arrive.
- A seller's close or pause survives the one-time identity change at upgrade.

**Non-Goals:**

- Buyer-negotiated shapes. `capacity-shape-envelope`, `capacity-shape-pricing`, and
  `negotiation-driven-capacity-resize` own those.
- Pool-assignable shape generators beyond the default, such as proportional shapes. This
  change shapes the seam only (decision 2).
- Ledger accounting for dimensions a listing omits (decision 3).
- Per-dimension pricing; publishing how many of a shape remain.
- Changing the registry filter vocabulary, its `on_missing` semantics, or renaming the
  published `ram_gb`/`disk_gb`/`vcpu_count` fields.
- Storefront overrides of physical facts: `region`, `offering_mode`, capacity backing.
- Shapes for bare-metal or API-credit listings.
- Rollback. Deployment is fail-forward (see Migration Plan).

## Decisions

### 1. A published dimension is a commitment, not a description

This change first proposed publishing every dimension the projection declares onto every
listing, as descriptive data for discovery. That premise does not hold. Because the claim
copies every published dimension and fulfillment builds from the committed dimensions, a
published `ram_gb` is both what the site reserves and what the VM receives. Publishing an
8-GPU, 512 GiB member's RAM on its 1-GPU slice would reserve all 512 GiB for one GPU, leave
the member's other GPUs unadmittable, and build a 1-GPU VM with the whole host's memory. The
listing model already distinguishes a slice's `ram_gb` ("RAM allocated to this slice") from
the host-level `host_ram_gb`.

Rejected alternatives for what a GPU-count slice should publish for its other dimensions:

- **The member's declared total on every slice.** Over-reserves and over-provisions as above.
- **Only on a slice that takes the whole member.** Honest, but cannot express the ordinary
  case of eight concurrent 1-GPU VMs on one 8-GPU host.
- **A proportional per-GPU share.** A partitioning policy nobody declared: inference, which
  the reasoning below rejects.
- **Member totals as `host_ram_gb` and similar.** Never reaches the claim, but the names do
  not line up (`vcpu_count` has no `host_cpu_cores` counterpart) and it leaves the `ram_gb`
  filter matching nothing.

So a listing publishes a dimension only when its shape declares it. Every listing has a
shape (decision 2). By default that shape declares GPU count and model only, as today's
listings do, and every other dimension is left to the site (decision 3).

### 2. Every listing is a shape; shapes are chosen or generated, and how many fit is derived

Every VM listing is a **listing shape**. A pool's shapes come from exactly one source, in
this order:

1. The storefront's override for that site and pool (decision 6).
2. The pool's `listing_shapes` hint, which its site declares, keyed by offering mode:
   `listing_shapes: {vm: [<shape>, ...]}`.
3. Otherwise, the domain's **default shape generator**.

A list from either the storefront or the site replaces the default entirely.

**The VM default is GPU-only.**
- It reproduces today's listings as shapes: `{gpu: {count: n, model: M}}` for each GPU model
  M among the pool's enabled members, and n from 1 to the largest declared GPU count among
  that model's members.
- Every other dimension is left to the site's configured defaults and provisioning playbook.
- Which of those shapes publish is decided by feasibility (decision 4), which reproduces
  today's range: a backed pool's is bounded by current availability, an unbacked pool's by
  declaration.

**Generating per model splits mixed pools.** A pool whose members have different models
publishes each model's counts separately. That replaces the first-member-wins behaviour and
its warning, which published one model's name over every member's GPUs.

**The generator is a seam.** It sits behind a small domain-owned interface: a pool's
projected members go in, shapes come out. GPU-count enumeration is its only implementation
in this change. The longer-term design assigns pluggable kit generators to pools, such as
proportional shapes. Those become further implementations selected by a future pool hint,
without changing derivation. This change adds no selection hint.

Further rules:

- **A list per offering mode.** One pool may be sold as several form factors; a VM shape and
  a future container shape are different declarations.
- **A list, not a single shape.** Eight 1-GPU VMs and one 8-GPU VM can be offered from the
  same host at once; the site already arbitrates between them, because admission debits every
  dimension a claim requests.
- **Count is derived, never declared or published.** A declared count would be a second
  authority on quantity beside the capacity declarations and would drift from them.
- **Cardinality is unchanged.** A fungible pool publishes one listing per feasible shape; a
  specific-resource pool publishes one listing per member per shape that member is feasible
  for.
- **A pool hint rather than storefront-only configuration.** A seller whose site is served by
  a storefront they hold no credential for can only express intent at the site
  (`openspec/specs/storefront-publication/architecture.md`, "Autonomous publication"). This
  is the same pool-policy channel `capacity-shape-envelope` chose for bounds.
- **Not `listing_cardinality_mode`.** That hint's scope is cardinality only, and the spec
  forbids adding what is offered to it.
- **Not `offered_shapes`.** `offer` names a negotiation message
  (`docs/development/ARCHITECTURE.md`, "One name per concept").
- **Not the projected VM size defaults.** `vm.ansible_pool_defaults.v1` is a provisioning
  fallback describing what a VM gets when nothing else says, and it carries no GPU count.
  Publishing it would advertise a default as a capability. It stays a provisioning default.

The roadmap's Goal 2 frames fixed shapes as the problem it removes. Listing shapes are
consistent with that goal as the listing's advertised starting point, which envelope,
pricing, and resize later make negotiable. They are not its end state.

### 3. Shapes are declared in the family-grouped form, through one shared utility

To avoid rework when `structured-capacity-requirements` lands, this change implements four
contained pieces of that change's accepted direction:

1. **The family-grouped shape form** is the only way to declare a listing shape:

   ```json
   {"gpu": {"count": 1, "model": "H100"}, "cpu": {"count": 8},
    "memory": {"gib": 64}, "storage": {"gib": 500}}
   ```

2. **One shared flattening utility** in the standard-library-only foundation kit
   `kit/capability-shape` (`market_capability_shape`). It
   validates the shape's structure (families holding fields holding scalar values), flattens
   it into quantities and attributes using a schema the domain supplies, and computes a
   canonical digest. It knows no family or field name.
3. **The VM family schema**, owned by the VM domain package next to `DIMENSION_KEYS`:

   | Family field | Kind | Flat name |
   |---|---|---|
   | `gpu.count` | quantity, required, positive integer | `gpu_count` |
   | `gpu.model` | attribute, required, non-empty string | `gpu_model` |
   | `cpu.count` | quantity, optional, positive integer | `vcpu_count` |
   | `memory.gib` | quantity, optional, positive integer | `ram_gb` |
   | `storage.gib` | quantity, optional, positive integer | `disk_gb` |

   Its quantity names must equal `DIMENSION_KEYS`, and a test asserts it.
4. **The shape digest** is computed over the canonical family-grouped form, not the flat names.

Why each piece:

- **`gpu.model` sits inside the shape.** A shape is feasible only on members of its own model, so a
  pool whose members have different models publishes one listing per shape, never a listing
  that mixes models. Pricing already resolves per GPU model, and it takes the model from the
  shape.
- **A family the shape omits is no commitment.** The listing does not publish it and the
  claim does not reserve it, as the commitment rule requires. What is provisioned for an
  omitted dimension is the site's choice: today the pool's configured defaults and the
  playbook. Nothing reports those defaults back, so the ledger cannot debit them. Keeping
  such capacity sufficient is the site administrator's responsibility, through the
  configurable pool defaults. This is an accepted division of responsibility, not a defect
  this change or another owns. Families stay optional so a dimension added later can be
  absent from some listings.
- **The flat names are an explicit exception.** The flat names are today's wire names rather
  than the family-prefixed names the convention would produce (`memory_gib`, `storage_gib`).
  The exception is recorded; when `structured-capacity-requirements` renames the wire, the
  change is two rows of this schema plus the wire rename it already owns. The units already
  agree: `ram_gb` and `disk_gb` are GiB (see Context).
- **The utility lives in its own foundation kit, not `kit/site` or the market core.**
  `structured-capacity-requirements` said "probably `kit/site`", which is heavy and which the
  VM listings and negotiation packages deliberately avoid. The kit imports only the standard
  library, so buyers (which install `arkhai_vms` without the pool kit), the pool kit, sites,
  and domains can all depend on it.
  - *Code review (2026-09-24):* the first implementation put it in `market_core`. The core
    holds only what is invariant across listing schemas, and a capability shape is not: its
    flattening exists to yield the quantities a capacity claim requests and the attributes
    admission matches, which means nothing to a market with no capacity admission, such as a
    market in unique items, or to API credits, whose purchase is a quota grant. Every
    consumer is capacity machinery. It moved to `kit/capability-shape`.
  - No existing kit fits: the listing-publication kit, `kit/capacity-publication`, depends on
    the storefront role package, so neither the pool kit nor a buyer could depend on it.
  - The identifier encoding stays in `market_core`: any market joining operator-chosen
    identifiers into a key needs it, and it knows nothing about capacity.
- **The digest is taken over the family form.** A later rename then changes no listing key
  and churns nothing.
- **Correction found in implementation (2026-09-24).** `market_core`, which holds the
  identifier encoding, is not importable by every domain package. The VM concept packages (`domains/vms/listings`, `negotiation`,
  `settlement`) are held by an enforced guardrail
  (`domains/vms/storefront/tests/unit/test_architecture_imports.py`) to import no core
  package, `market_core` included; none does today. The permanent contract is looser: it
  forbids only "core composition packages" (`openspec/specs/market-composition/spec.md`,
  "From-below kit dependencies").
  - *Decided (design review, 2026-09-24):* the concept packages reach the utility and the
    encoding only through `arkhai_vms`. The VM vocabulary package already depends on
    `arkhai-core` and exposes the VM-bound operations: validating, flattening, and digesting
    a VM shape, and building VM listing keys. The guardrail stands unchanged. It still holds
    now the utility is a kit: `arkhai_vms` binds the VM schema in one place.
  - *Refined after implementation review:* `arkhai_vms` exposes the listing key builders,
    which use the encoding, rather than re-exporting the encoding itself; a VM concept
    package gains a VM operation, not a core primitive under another name.
  - Rejected for now: narrowing the guardrail to admit `market_core`, which loosens a
    deliberate rule; and moving shape resolution and keys out of the listings package, which
    separates keys from the reconciler that owns them.

Stays in `structured-capacity-requirements`: the buyer-facing `requirements` object, the
claim restructure and the `probe` signature, the `offering_mode`/`resource_type` split, the
wire rename, and expressing the site's resource side in the family form.

### 4. A shape is published only where a source member is feasible for it

**What is checked.** A shape is publishable when some source member satisfies the claim the
listing would produce under the site's canonical **resource-feasibility** predicate,
`dict_resource_satisfies_claim`:

- **Fungible pool:** some single enabled member.
- **Specific-resource pool:** that member.
- **Unbacked listing:** feasibility against declared capacity only.
- **Capacity-backed listing:** additionally feasible against current availability.
  - For a fungible pool, availability comes from the capacity-bucket projection when it has
    loaded for the site, as the permanent spec already requires for fungible pools. Buckets
    carry every dimension's availability and the GPU model.
  - For a specific-resource pool, or when buckets have not loaded, it comes from the
    member's projected `available` map.
  - A member reporting no availability is unknown rather than empty and is judged on
    declared capacity, as today's unknown-availability rule does.

**How the predicate reaches the storefront.** It is injected through the storefront's
composition, as the placement matcher already is, so `domains/vms/listings` gains no
`kit/site` dependency. The same predicate answers the inventory guard's declared-match
question.

**What it is not.** This is resource feasibility, not site admission; the site's reservation
remains the final admission boundary.
- *Checked by publication outside the predicate:* the pool's advertisement authorization and
  backing, as today.
- *Not checked:*
  - the site's configured required-attribute presence;
  - the delivery-mode check;
  - the pool provider's host requirement, since the projection deliberately carries no host
    connection data;
  - holds over the requested lease window;
  - physical-host conflicts.
- A listing may therefore publish and still be refused at reservation, as today's listings
  can be. Reproducing full admission would need a different site capability and state the
  projection intentionally withholds.

**Parity gate result (task 0.1, 2026-09-24).** Run against the real code on both sides:

- **Method.**
  - Claims came from `compute_capacity_claim_from_order` applied to shaped
    `listing_resource` values.
  - The site side was a real `CapacityLedgerService` composed as the VM provisioner composes
    it: unit claim keys `("units", "gpu_count")` and mirror dimension `gpu_count`.
  - Holds were placed so that declared and available capacity differ.
  - The ledger's answer is the two `resource_satisfies_requirement` calls inside
    `_find_candidate`, against declared capacity and then capacity less holds.
  - The projections were the ones the provisioning app serves:
    `load_capacity_resource_inventory(ledger.list_resources())` through
    `SiteProjectionService`, plus `capacity_bucket_projection`.
  - The storefront's answer was `dict_resource_satisfies_claim`, with the storefront's
    `VM_UNIT_CLAIM_KEYS` and `VM_MIRROR_DIMENSION`, over adapted rows.
- **The adapter is required.** A projected member names itself `physical_resource_id` and
  takes its pool from the enclosing row's `resource_pool_id`. A capacity bucket names its pool
  `resource_pool_id`, its attributes `grouping_attributes`, and no resource. The adapter maps
  these onto the snapshot-row fields `resource_id`, `pool_id`, `resource_type`,
  `resource_subtype`, `attributes`, and `available`. A bucket maps to an empty resource ID,
  which is why buckets stand in only for fungible claims.
- **Agreement.** The predicate agreed with the ledger's step on every member, for declared
  and available capacity, across eight claims:
  - a member declaring `region` and `gpu_model`, with one, two, and four dimensions;
  - a shape exceeding current GPU availability, and one exceeding current memory
    availability;
  - a model the pool lacks;
  - a specific-resource claim, which drops `pool_id`, and the same claim with a model the
    member lacks.
  
  For fungible claims, "some bucket is feasible" agreed with "some member is available". Full
  admission (`ledger.probe`) chose a member in exactly the cases both judged feasible.
- **Region only as a pool hint.** Both refuse. `_split_claim_requirement` makes every
  non-quantity claim key a required exact attribute, `region` and `pool_id` included, and
  admission reads attributes from the declaration itself, never from pool policy. Today such
  a pool publishes listings no reservation can admit. The same holds for a `region` or
  `gpu_model` taken from the legacy home-site row. Resolved below: such pools publish nothing
  and are reported per pool.
  - The two places are not interchangeable. A listing advertises its pool's `region` hint
    (or the legacy home-site row), never a member attribute, and a listing with no region
    cannot be built; a reservation matches the claimed region against the declaration's own
    attribute. A pool therefore states its region on the pool and on its declarations. The
    end-to-end scenario first failed on exactly this (task 5.4).
- **Disagreement: a projected member without `resource_type`.** The predicate reads an
  absent type as `""` and refuses every claim; the ledger cannot store one (the column is
  non-null with default `compute.gpu`), and the provisioning projection fills in the same
  default. The disagreement therefore arises only from producers that omit the field: the
  `kit/site-client` contract builder `build_projected_resource`, which sets it to `None`, and
  the storefront's `fake_site.py` projection and hand-built test members, which omit it.
  `validate_resource_pool_projection` does not check it, because no consumer read it until
  now. Resolved below: the projection contract requires it, and a member without it is
  unresolvable.
- **Design review of the gate (2026-09-24).** Both questions were answered, and the gate is
  cleared:
  - *Missing `resource_type`.* The projection contract requires a non-empty `resource_type`
    on every member, and its builder, the fake site, and hand-built test members send one.
    The storefront assumes no default. A member without one is malformed, not incapable, so
    it is unresolvable and reported, like a malformed GPU count, rather than judged
    infeasible (see "Holds" below). Rejected: assuming the site's default kind, which puts a
    site default in the storefront, and skipping the kind check, which would let a member of
    another kind match.
  - *Pools no reservation can admit.* A default shape that fails against declared capacity is
    reported per pool (see below). Rejected: silent delisting, and no longer claiming a
    hint-sourced region, which would change what admission matches.

**When no member is feasible for a shape:**
- The shape yields no listing, and the storefront reports it in system status, naming the
  site, pool, shape digest, and what was not feasible.
- It never shrinks the shape and never falls back to another source's shapes.
- A listing whose shape becomes infeasible closes through ordinary source reconciliation,
  because its key is no longer derived.
- A stated shape no member is feasible for is reported per shape.
- A default shape that fails against **declared** capacity is reported **per pool**, naming
  the claim attribute no enabled member declares, for example that the claim requires
  `region` `us-east` and no enabled member declares it.
  - Default shapes are generated from members' declared counts, so declared infeasibility
    arises only from a categorical mismatch (region, model, kind), never from load. It is a
    configuration problem the operator can fix by declaring the attribute on the capacity
    declarations.
  - Reporting per pool keeps one mismatch from producing an entry for every GPU count.
- A default shape that fails only against current availability is not reported: that is
  ordinary unavailability.

**Holds.** A member is unresolvable, and holds the listings of its pool (fungible) or its own
(specific resource), when:
- its GPU count is unreadable, as today; or
- it projects no `resource_type`, which the projection contract requires.

Both are reported in the derivation report. Holding rather than closing matters only if a
producer breaks the contract, and then holding is the safer failure.

**Local-table derivation.** A storefront that derives capacity-backed listings from its local
tables rather than site projections has no projected members to judge. Its pools publish the
default GPU-only shapes for their one model, ranged over local availability, without the
feasibility predicate, and keyed by shape digest like every other listing. Accepted in design
review (2026-09-24) as sufficient for a path `pools-9-retire-local-physical-authority`
removes.

### 5. Every listing's identity includes its shape

- **Structural key.** Every candidate's reconciler key is built from the site, the pool or
  resource, and the shape digest, whichever source produced the shape.
- **Binding envelope.** Every new binding's envelope is `compute.listing_source` schema
  version 2, carrying the site, pool, resource, and the canonical shape.
- **Why one scheme.** Identity then depends only on what is offered:
  - a site that later declares the same shape its pool was publishing by default keeps that
    listing;
  - a future generator yielding some of the same shapes keeps those listings.
  
  The alternative, keeping today's keys for default shapes, avoided churn at upgrade but
  tied identity to where a shape came from.
- **Reading the key back.** A stored listing's key is read from its binding envelope rather
  than recomputed from its published fields, because flattening is not required to be
  invertible.
- **Version 1 bindings after upgrade.** Their keys are never derived again. Each open
  version 1 listing therefore closes through source reconciliation, and its version 2
  successor publishes, once, at upgrade. A closed version 1 listing is never reopened.
- **Editing a shape.** The old key stops being derived, so the old listing closes and a
  listing under the new key publishes.

**Seller state carries across the identity change.** A seller's close and a seller's pause
belong to a listing ID, and the identity change would otherwise defeat them: the version 2
successor is a different derivation identity, so neither state would reach it. A one-time,
idempotent carry-over step runs at storefront startup, before the lifecycle loops start:

- For each version 1 VM listing, it computes the equivalent default shape from the stored
  listing and its binding: site, pool or resource, `gpu_count`, and `gpu_model`.
- For a seller-closed listing, it binds the version 2 successor as a listing closed by its
  seller, never published. Publication's existing rules then leave it closed and bind no
  replacement under its identity, and the seller may reopen it as usual.
- For a paused open listing, it binds the successor paused.
- It records nothing for a listing reconciliation closed, or an open unpaused one.
- It is runtime initialization rather than a schema migration, because the derivation key
  depends on the configured domain registration.
- It is idempotent: a successor already bound is left alone.
- The number carried over is reported in system status, with each earlier listing mapped to
  its successor.
- A seller who reopens an earlier listing rather than its successor reopens it only until
  the next cycle closes it again, because its key is never derived. The successor is the
  listing to reopen, and the status mapping names it.

### 6. Storefront overrides live in a site-scoped durable store

- **Table.** A new `storefront_pool_overrides` table in the VM storefront database, with
  primary key `(site_id, pool_id)`. It holds `sla`, `min_price`, `token`,
  `max_duration_seconds`, settlement clauses, and `listing_shapes`, plus timestamps.
- **Why a new table.** `compute_capacity_pools` is not reused: it mixes commercial values with
  physical bookkeeping, it is keyed by pool alone, and its writer is being retired.
- **What an override may carry.**
  - Physical facts (`region`, `gpu_model`, backing, offering mode) are not overridable.
  - A shape's `gpu.model` is a choice among the models the pool actually has, and decision 4
    refuses to publish a model no member carries.
  - Raw `accepted_escrows` is omitted, because settlement options come only from typed
    clauses.
- **Semantics.**
  - A field left empty means "no opinion" and falls through to the next tier, as today.
  - A write replaces the whole record.
  - Shapes and settlement clauses each replace the lower tier's list as a whole.
  - An empty shape list is refused: to stop selling a pool the seller closes its listings,
    which is already durable.
  - An empty settlement-clause list is refused for the same reason (decided in planning,
    2026-09-24). It would leave every listing of the pool with no settlement option, a
    second, less visible way to stop selling it.
- **Precedence, highest first.**
  - Commercial fields: the new store; the legacy home-site `compute_capacity_pools` row; the
    pool's hint; the storefront's configured default.
  - Shapes: the new store; the pool's `listing_shapes` hint; otherwise the domain's default
    shape generator.
- **Where the tier is read.** Derivation reads the store itself, inside the one function
  every projection-path caller goes through (`available_compute_slices`). Publication,
  capacity reconciliation (`stale_open_listing_ids`, `current_available_resource_keys`),
  and the inventory guard all derive structural keys there. An override's shapes change
  those keys, so a tier applied on the publication path alone would have reconciliation
  close every listing an override shaped.
- **The legacy tier stays until `pools-9`.** It remains live for as long as its writer, the
  resource import, exists; `pools-9` retires both together. A migration could not attribute
  legacy rows to a site without reading live configuration, which `pools-8` found unsafe.
- **Reporting the legacy tier.** System status names, per pool, every field whose resolved
  value came from the legacy row, so deleting a new override and seeing a legacy value
  reappear is visible.
  - This includes `region` and `accepted_escrows`, which the new store cannot state.
  - It excludes the row's `gpu_model`, which no longer decides anything on the projection
    path (see "Dead legacy model fallback" below).
- **Durable intention.** An override outlives its pool. If the pool disappears from the
  projection the override has no effect and is reported as orphaned; if the pool returns, it
  applies again.
- **Override status: unknown is not absent.** System status reports every stored override
  in exactly one state:
  - `inactive`: listings derive from local tables, so no override applies;
  - `site_unconfigured`: the storefront no longer configures the override's site;
  - `unknown`: the site is configured, but no projection value is held for it, so whether
    the pool exists is not known;
  - `orphaned`: the projection generation publication derives from holds no such pool;
  - `applied`: that generation holds the pool.
  
  It is judged against `listing_source_projection()`, the selector publication uses. Status
  therefore cannot call an override orphaned while publication has no answer for its site,
  and cannot disagree with publication about which generation counts.
  - It is computed in system status from the store, the configured sites, and that
    selector, rather than inside derivation. Derivation runs only for sites that hold a
    value, so it can never observe the `unknown`, `site_unconfigured`, or `inactive` states.
  - Rejected: judging only loaded sites and omitting the rest, which makes an unknown
    override indistinguishable from an applied one.
- **Local-table derivation ignores overrides.** When listings derive from local tables, no
  override applies. Writes are still accepted and checked against the live projection,
  because the check needs only the site's client. Each stored override reports `inactive`.
  - Rejected: refusing writes with `409`, which would stop an operator preparing overrides
    before switching derivation to projections.
  - Rejected: applying the commercial fields on the local-table path, which would add a
    partial precedence chain to a path `pools-9` removes.
- **Dead legacy model fallback.** On the projection path, shapes carry the GPU model and
  every candidate's terms resolve per shape model (Context). The legacy row's `gpu_model`
  fallback, and the per-row model and commercial fields it feeds, decide nothing. Slice B
  removes them from `_projected_pool_rows` when it adds the override tier there.
  - Commercial terms then resolve only per shape model.
  - The local-table path, whose shapes are generated from the row's model, is unchanged.
- **A kit capability, not a VM store** (superseded 2026-09-24; see decision 10). The store
  was first VM-local, with a domain-neutral store deferred to Goal 4. A second market with
  similar shape requirements, kube pods, is imminent, so the store, write check, and status
  move to a kit now, with each market supplying its own vocabulary.

### 7. The override API checks the site's live projection before accepting

- **Routes.** Under `/api/v1/admin/`:
  - `PUT /pool-overrides` replaces one record.
  - `GET /pool-overrides` with `site_id` and `pool_id` reads one; without them it lists all,
    optionally filtered by `site_id`.
  - `DELETE /pool-overrides` with `site_id` and `pool_id` removes one. It is idempotent.
- **Addressing.** Site and pool IDs are operator-chosen strings with no character
  restriction, so they travel in the body or query rather than the path.
  - Each route has its own semantic operation in the administrator identity contract.
  - The routes inherit durable replay reservation from the administrator middleware.
- **The signed resource is percent-encoded** (decided 2026-09-24). This follows the
  administrator contract's existing convention for operator-chosen strings (Context).
  Decision 10 adds the offering mode as a third address component and moves the encoding
  into the kit; the rules below otherwise stand.
  - The `PUT` and `DELETE` resources are the site and pool, each percent-encoded with no
    safe characters and joined by `/`, as `identity_subject_resource` builds one.
  - The `GET` resources are the sorted, percent-encoded query, as
    `identity_status_resource` builds one. They are `pool-overrides?pool_id=…&site_id=…` for
    one record, and `pool-overrides` or `pool-overrides?site_id=…` for a list.
  - The query admits only `site_id` and `pool_id`, each at most once, as the existing query
    resources do. `pool_id` without `site_id` is refused.
  - Percent-encoding with no safe characters is injective, which is all a signed resource
    needs. The client reproduces it with the standard library, so it gains no dependency.
  - Rejected: the length-prefixed encoding in `market_core.identifier_encoding`. The client
    would need `arkhai-core` only to rebuild a string, and the administrator contract would
    use two encodings. That module keeps its one consumer, VM listing keys through
    `arkhai_vms`. Its docstring's claim that signed administrator resources depend on its
    byte form is corrected in implementation.
- **Before accepting a `PUT`:**
  - Refuse a site the storefront has not configured, and a structurally invalid record: an
    unknown field, a malformed shape, or a malformed settlement clause. The refusal is `422`.
  - Fetch the site's resource-pool projection live through that site's signed client. The
    storefront's cache is not read, so staleness in either direction cannot admit or refuse
    a write wrongly.
  - Refuse a pool absent from that live generation (`404`). Refuse with a retryable `503` if
    the site is unreachable or its response does not verify; the reason names which.
  - Accept a pool present in the live generation even if its declarations are currently
    unresolvable.
- **The response.** It returns the stored record and a feasibility report per shape, computed
  from the same live generation and labelled with its revision and digest. The report is
  judged by the derivation publication runs, on declared capacity, with the new record in
  place of the stored one and without recording a derivation report, so the report and the
  next cycle cannot disagree. A shape no member is
  feasible for is reported, and the override is accepted anyway; the resulting delisting is
  the intended side effect. The live fetch does not write the cache. For a full preview of
  the next cycle, the operator uses the existing publication dry run.
- **After a write** (decided 2026-09-24), the storefront refreshes that one site's
  resource-pool cache in place and wakes the publication loop, so the override takes
  effect promptly.
  - The override itself is read from the store on the next cycle. The refresh only ensures
    that cycle derives from a generation no older than the one the write was checked
    against. The wake is what makes the effect prompt rather than one interval late.
  - A site with no cache yet is left to the poller's first load. Its override reports
    `unknown` until then (decision 6).
  - A refresh failure does not fail the write, which is already stored. The cache records
    the failure as it does for a poll, and the next poll retries.
  - A lifecycle pause does not suppress the refresh, as it does not suppress the admin
    refresh route. A held publication loop does not observe the wake; a caller holding the
    loops advances publication explicitly.
  - Rejected: `load_site_projections`. It rebuilds every site's caches, including capacity
    buckets, through a capacity client it builds itself rather than the composed runtime.
- **After a delete**, the storefront wakes the publication loop and refreshes nothing. A
  delete contacts no site and verifies no pool, so it has no newer generation to bring the
  cache up to.
- **Clients and CLI.** Methods on both storefront client variants, covered by the
  sync/async parity test, and a `market-storefront` command group that reads a record from
  a document and calls the client. Both variants gain authenticated `PUT` and `DELETE`
  helpers beside their existing `POST`, `GET`, and `PATCH` ones.

### 8. Pool hints are validated for structure at the site, and for vocabulary by the domain

- **At the site.** Every pool-write surface validates `listing_shapes` through one shared
  structural check: create, replace, patch, and bulk import. The value must be a mapping of
  offering mode to a non-empty list of well-formed family-grouped shapes. This is the same
  treatment the SLA and hold hints get. The pool kit calls the structural validator in
  `kit/capability-shape`, gaining a dependency on that foundation kit, and learns no
  dimension names.
- **At the storefront.** The VM domain validates its vocabulary during derivation. A pool
  whose `vm` list it cannot read yields no shaped listing and is reported. Its existing
  shaped listings are held rather than closed, because an unreadable declaration is not a
  withdrawn one. The pool does not fall back to the default shape generator.
- **At an override write.** A shape outside the vocabulary is refused (decision 7).

### 9. What a listing publishes

`listing_resource` carries:

- `pool_id`, plus `resource_id` for a specific resource;
- the shape's `gpu_model` and `gpu_count`, and each quantity the shape declares under its
  flat name;
- `sla`, `region`, `offering_mode`, and `capacity_backing`, as today.

The existing filter vocabulary matches these fields without change. The inventory guard and
the availability reopen compare them because `slice_identity` carries every published
identity field. The dimension part of `IDENTITY_FIELDS` is derived from `DIMENSION_KEYS`
rather than written as a literal, which adds a dependency from `arkhai-vms-listings` on
`arkhai-vms`.

### 10. Storefront pool overrides are a kit capability; each market supplies its vocabulary

Decided 2026-09-24, after the Slice B code review. Everything that remains in a core package
must be universal to all markets, and a second market with shape requirements is imminent.

- **A new kit, `kit/pool-overrides`** (`arkhai-kit-pool-overrides`, `market_pool_overrides`).
  - `kit/capacity-publication` was the first choice of home. Both the VM and API-credits
    storefronts pin it exactly, so extending it would release the API-credits storefront
    only to move a pin, for a capability that market does not use.
  - A new kit reaches only its consumers.
  - It is a storefront-side kit, beside `kit/capacity-publication`. It depends on the core
    storefront client (universal transport), the site client (its error types), and pydantic.
- **The kit owns:**
  - the store and its migrations, which a storefront composes as it composes
    `settlement_migrations()`;
  - the framework-free write service with its check order, retryable refusals, and
    refresh-and-wake effects;
  - the five status states;
  - one signed-resource encoding, shared by the storefront's identity contract and the
    client;
  - the typed client extension.
- **The storefront composition root owns:** the thin FastAPI routes, as it does for hosted
  settlement's route service, and the mapping from offering mode to contribution.
- **Each market supplies a contribution per offering mode:**
  - validation of its commercial terms and its shapes;
  - a feasibility judge over a site's live projection;
  - integration with its own listing derivation.
  
  Settlement clauses are already market-neutral; the composition root injects their
  compiler.
- **An override is addressed by site, pool, and offering mode.** This realizes the
  discussion's "shapes per offering mode". A pool serving two modes carries two
  independent overrides, each validated and read by its own market.
  - Keying by mode rather than nesting a per-mode map inside one record keeps each record
    wholly one market's. The kit stays opaque: it never splits a record between markets.
  - A write for a mode no contribution serves is refused, as a vocabulary error.
  - The mode is never defaulted (`ARCHITECTURE.md`, "One name per concept").
- **Record shape:** `site_id`, `pool_id`, `offering_mode`; then `listing_shapes` and
  `settlements`, each a non-empty list when set; then `terms`, an object the kit stores
  without interpreting. For VM, `terms` holds `sla`, `min_price`, `token`, and
  `max_duration_seconds`.
- **Storage: a new kit-owned table, `pool_overrides`,** keyed by all three address
  components.
  - The VM migration that created `storefront_pool_overrides` in Slice B is retired. The
    store was never released.
  - A development database that ran it keeps an orphan table that nothing reads.
  - Reusing the table name would leave `CREATE TABLE IF NOT EXISTS` silently keeping the
    older schema there.
- **Derivation still reads the store directly** (decision 6, "Where the tier is read";
  retained in review). VM derivation reads the kit's documented table for its own mode.
  The listings package cannot import the kit, because its buyers install it without
  storefront dependencies.
- **Core keeps only universal transport.** The core client exposes one generic
  `authenticated_request` on both variants; every override method, model, and status field
  leaves core.
  - The override status field is declared on the VM storefront's own status response.
  - The kit client reads it from the generic response's `extra`.
- **One encoding for signed resources, owned by the kit.** Write and delete sign the three
  address components, each percent-encoded with no safe characters and joined by `/`.
  Reads sign the sorted, percent-encoded query under `pool-overrides`. An empty query signs
  `pool-overrides` with no trailing `?`, as decision 7 states.
- Rejected:
  - keeping the typed client in core, which put VM vocabulary in a core package;
  - a per-mode map inside one record, which splits a record between markets;
  - extending `kit/capacity-publication`, for the exact-pin release it forces.

### 11. A site whose projection is not held holds its listings

Decided 2026-09-24. Found while writing a test the review asked for.

- **Before:** a publication cycle closed every open listing of a configured site whose
  resource-pool projection held no value, as `source_gone`. That happens when the
  storefront starts while the site is unreachable, or after the admin refresh route rebuilds
  caches during an outage. With one site, or with no site known, an empty projection map
  also made derivation fall back to the storefront's local tables.
- **Both contradict the permanent contract.** A failed refresh retains the last generation
  "rather than representing an empty projection", and a local-table path is an explicit
  rollback opt-in, not a default (`openspec/specs/storefront-publication/spec.md`,
  "Storefronts cache independent site projections").
- **Decision:**
  - A configured site with no projection value holds its listings: they are neither closed
    nor refreshed, as an unreadable pool's are.
  - A storefront configured to derive from projections never falls back to local tables
    for lack of one. It derives nothing for the unknown sites and holds them. Local-table
    derivation remains only where it is configured, which `pools-9` removes.
- **The trade-off weighed:**
  - *Delisting and relisting.* The listing is absent for the outage plus up to one
    projection poll interval (5 s by default). A returning projection wakes publication,
    and the same listing IDs reopen. It costs registries a close and a reopen write per
    listing per registry, costs sellers visibility and false `source_gone` records, and
    loses buyers the listing for the window.
  - *Holding.* A buyer who opens a negotiation during the window is refused at round zero
    with `source_unavailable` by the inventory guard, before acceptance, so no escrow is
    funded.
  - Holding is the smaller change, and it is the one consistent with the guard and the
    projection cache.
  - A site that loaded once and later becomes unreachable was never affected: its cache
    keeps the last generation as stale.
- **Found in implementation (task 13.3's gate).** The admin reservation route, the
  fulfillment-event callbacks, and the failure-action reopen derived from local tables even
  where listings derive from projections. After an admin reservation of one GPU in a
  two-GPU projected pool, both listings closed, including the one still feasible. They now
  use the same projection selector as publication. The five older tests that seeded
  local-table listings now configure local-table derivation explicitly.
- **Not in this change:**
  - A time bound on holding. A decommissioned site whose listings are never closed would
    otherwise stay advertised indefinitely, refusing every buyer. See Open Questions.
  - The admin refresh route discarding last-known generations.

### Retained: omission beats inference

A pool with no declared shapes publishes the default shapes, which declare nothing beyond GPU
count and model. The original reasoning still applies to it:

- `on_missing: fail` treats an omission as honest ignorance and excludes the listing.
- A wrong value is treated as a truthful claim and includes it.
- Under-matching is a discovery inconvenience; over-matching sells capacity the seller has
  not declared.

Provisioning defaults are never published.

## Risks / Trade-offs

- **[Declared quantities change what is reserved and provisioned]** → Intended: the buyer
  gets every quantity the listing states; a dimension it omits is sized by the site. A declaration that overstates what the hypervisor can
  allocate now fails at fulfillment. Declaration accuracy stays the site operator's
  responsibility.
- **[Omitted dimensions are provisioned but not reserved]** → Accepted division of
  responsibility (decision 3). The site administrator sizes the configurable defaults. It is
  documented at promotion so operators know it is theirs.
- **[Feasibility is weaker than admission]** → A listing may publish and be refused at
  reservation (decision 4), as today. Stated normatively so no caller treats publication as
  an admission guarantee.
- **[Every VM listing changes identity once at upgrade]** → Accepted, and deployed
  fail-forward. Outstanding buyer references to open listings go stale once. Accepted deals
  and leases keep their own bindings. Seller closes and pauses carry across (decision 5).
- **[Mixed-model pools publish differently]** → A correction: each model's listings name
  that model.
- **[Pools no reservation can admit stop publishing]** → A pool whose `region` exists only as a
  pool hint or legacy row, or whose members lack the published `gpu_model`, publishes today
  but is refused at every reservation. After upgrade it publishes nothing, and system status
  names the undeclared attribute. Intended: those listings advertised what could not be
  bought. The fix is declaring the attribute on the capacity declarations.
- **[Shapes can be stated in two places]** → Whole-list replacement makes the effective list
  exactly one source's. System status names each pool's source.
- **[A deleted override reveals a legacy value]** → Reported in system status whenever a
  legacy value is in effect; ends when `pools-9` retires the tier.
- **[Overrides do nothing under local-table derivation]** → Accepted until `pools-9`
  removes that path. Every stored override reports `inactive` there, so the absence of an
  effect is visible rather than silent.
- **[Unknown sites hold their listings without a time bound]** → Accepted for now
  (decision 11). A site decommissioned without closing its listings leaves them advertised
  and refusing every buyer at round zero until an operator closes them; system status names
  the site. A time bound is an open question.
- **[A site outage blocks override writes]** → Intended: the write is refused as retryable
  rather than accepted unverified.
- **[Scope]** → The work lands as three reviewable slices within this change (see
  `tasks.md`). Shared vocabulary, shape derivation, identity, and discovery come first; the
  override store and its control plane second; its extraction into `kit/pool-overrides`, the
  review's corrections, and the unknown-site hold third.
- **[Naming exception]** → Recorded in decision 3 and in
  `structured-capacity-requirements`' design, where the rename is owned.

## Migration Plan

**Fail-forward.** This change deploys with the Goal 7 feature set, which is fail-forward as a
whole; there is no rollback procedure. A reverted storefront would not be safe:

- It rebuilds a shaped listing's key from its published GPU count and pool, so an open shaped
  listing would not look stale.
- It would publish a second, version 1 listing beside it.
- It could reopen a closed shaped listing through capacity events.

VM leases, reservations, and accepted deals are unaffected by this change: they keep their
own bindings and records. The listing layer is derived state. If it were lost, the
storefront rebuilds it from site projections.

**Upgrade sequence:**

1. The new storefront table is created by its migration. No data migration.
2. At startup, before the loops run, the seller-state carry-over binds successors for
   seller-closed and paused version 1 listings (decision 5).
3. The first publication cycle closes every open version 1 VM listing, since its key is no
   longer derived, and publishes the version 2 successors.
4. A pool whose listings no reservation could admit publishes no successors, and system
   status reports the attribute its members do not declare. A seller-closed or paused
   successor is bound by the carry-over whether or not its shape is feasible; reopening one
   that is infeasible yields the same report.

Older storefronts ignore the unknown `listing_shapes` tag, as the hint contract requires, and
older pool kits store it without validation.

The pool override store is created by the `kit/pool-overrides` migration (decision 10). A
development database that ran Slice B's retired VM migration keeps an orphan
`storefront_pool_overrides` table and its migration record. Nothing reads either, and no
release carried them.

## Coordination with other changes

Recorded in each change's own design where it changes that change's plan.

- **`structured-capacity-requirements`.** Decision 3 implements its family-grouped shape
  form, the shared utility, and the VM family schema for listing shapes, places the utility
  in the foundation kit `kit/capability-shape`, and records the flat-name exception its
  rename resolves.
- **`pools-9-retire-local-physical-authority`.** The override endpoint its design planned
  over `compute_capacity_pools` is superseded by decision 7. It still retires the legacy
  override tier with its writer.
- **`capacity-shape-envelope`.** Its bounds should use the same family-grouped vocabulary
  through the shared utility. Once bounds exist, the feasibility check in decision 4 also asks
  whether the pool admits the shape.
- **`capacity-shape-pricing`.** It prices shaped listings; per-model pricing already resolves
  from the shape's `gpu.model`.
- **`pools-8-capacity-projection-and-listing-hints`.** Its `vm.ansible_pool_defaults.v1` view
  remains a provisioning default and is not a listing shape (decision 2).

## Design review (2026-09-24)

A review of the design and plan raised three blockers. Each was confirmed against the code
and resolved in the decisions above.

- **Optional shape families against provisioning defaults.** "A listing provisions exactly
  its shape" was false, because the provider provisions pool defaults for any dimension the
  reservation omits.
  - Considered: requiring every quantity family on a shape.
  - Considered after implementation review: requiring completeness only of stated shapes
    (a pool hint or a storefront override), leaving generated shapes GPU-only. It would
    make a stated shape's advertised, reserved, and provisioned quantities coincide.
    Rejected, because:
    - one commitment rule serves every source, so a stated shape identical to a default
      one is the same listing and keeps its key; under the narrower rule an operator
      adopting a hint for a pool's existing GPU-only listings could not state them;
    - the pool kit cannot validate the VM vocabulary, so an incomplete hint would be
      refused only when a storefront reads it, far from the operator who wrote it;
    - later families could not be left out of existing stated shapes without making
      them invalid.
  - Resolved instead by stating the commitment precisely (decisions 2 and 3): a listing
    commits to and reserves only what its shape declares; for anything omitted the site
    decides and the site administrator sizes the defaults. Every listing is a shape, and
    the default shape is GPU-only, as today's listings are.
  - Families remain optional, so later dimensions can be left out of some listings.
- **Feasibility is not admission.** The claim that publication matches site admission was
  false: `_find_candidate` checks mode, host requirement, lease-window holds, and physical
  conflicts that the exported predicate does not. Decision 4 now states resource
  feasibility, names what it does not check, and leaves admission to the reservation. The
  same review corrected an earlier statement: capacity buckets carry every dimension's
  availability and the GPU model, so they remain the fungible availability source.
- **Rollback.** "Rollback is a code revert" was false: reverted code rebuilds shaped
  listings' keys from their GPU counts, duplicates open ones, and can reopen closed ones.
  Deployment is fail-forward instead (Migration Plan). Moving every listing to shape
  identity (decision 5) made the one-time identity change at upgrade explicit. The
  seller-state carry-over was added so that change does not undo a seller's close or pause.

The review's other recommendations were adopted:
- the length-prefixed encoding moves to a neutral `market_core` module (decision 7);
  the administrator contract later kept its own percent-encoding instead ("Slice B
  discussion"), so the module's consumer is VM listing keys;
- implementation lands as two reviewable slices (`tasks.md`);
- a provider-input test is added;
- the stale "globally unique `pool_id`" row in `docs/development/ARCHITECTURE.md`'s
  identifiers table is corrected at promotion.

## Slice B discussion (2026-09-24)

Slice B's plan was checked against the code before implementation. Five points needed a
decision; the maintainer decided each, and decisions 6 and 7 record the results.

- **Signed-resource encoding.** Percent-encoding, following the administrator contract's
  existing convention, instead of the length-prefixed encoding task 7.3 named (decision 7).
- **Post-write refresh.** An in-place refresh of the written site's resource-pool cache,
  plus a publication wake, instead of `load_site_projections` (decision 7).
- **Local-table derivation.** Writes accepted, no effect, each override reported
  `inactive`. It is kept lightweight because `pools-9` removes the path (decision 6).
- **Legacy reporting scope.** Every field resolved from the legacy row, `region` and
  `accepted_escrows` included. The row's dead `gpu_model` fallback is removed rather than
  reported (decision 6).
- **Unloaded sites.** An override at a site with no projection value is `unknown`, never
  `orphaned`, and is judged through the selector publication uses (decision 6).

Two plan amendments needed no decision:

- Client `PUT` and `DELETE` helpers (decision 7).
- A fake-site live projection settable apart from the test harness's cache, which task
  7.8's cached-but-absent case needs.

The invariant that derivation reads the tier where structural keys are derived (decision 6)
was implicit in the plan and is now stated.

Planning then decided that an empty settlement-clause list is refused and that a delete
refreshes nothing (decisions 6 and 7).

Implementation found two defects, neither a design question:

- **Status dropped undeclared keys.** The status route returns the common
  `HealthResponse`, which drops any key it does not declare, so Slice A's carry-over report
  never reached a caller. The VM storefront declares its own keys on a
  `VmSystemStatusResponse`, keeping the fix out of the core package.
- **A leaking test cursor.** The capacity-event cursor is process-wide, while each test
  app's fake site restarts its events at version one. The publication test harness resets
  it on entry and exit.

## Slice B code review (2026-09-24)

A review of Slice B found the architecture sound and raised one blocking layering issue. Its
points and their dispositions, as decided with the maintainer:

- **VM override vocabulary in the core storefront client (blocking).** Accepted: decision 10.
  Core keeps only universal transport, and everything else moves to `kit/pool-overrides`.
- **Orchestration asserted in mocked unit tests.** Accepted. Sequencing, refusal before the
  site call through the real compiler, and refresh failure at the real seam move to
  application integration tests. Local behaviour stays unit-tested: the status state and
  translating site errors into refusals.
- **The e2e log helper in this change.** Kept, at the maintainer's choice. It is not part of
  this change's own files.
- **A live projection row that is not a mapping.** Accepted: it is refused as an unusable
  projection (retryable).
- **Coverage gaps.** Accepted:
  - a two-site application test for a non-home site;
  - a pool whose declarations are unresolvable is accepted;
  - a refresh failure does not fail the write;
  - malformed clauses are refused through the real compiler;
  - an unknown site's listings are held (decision 11);
  - commercial terms reach the published listing.
- **Task record overclaims.** Corrected in `tasks.md` (7.8, 8.1).
- **Signed list resource `pool-overrides?`.** The code now follows the design: no trailing
  `?` (decision 10).
- **Docstrings citing delta-only requirements.** Resolved by promotion at closeout.
- **Derivation reading the store directly.** Retained (decision 10).
- **Moving the whole service to a kit.** Superseded by the maintainer's decision to do so
  now (decision 10).

## Open Questions

- **How long may an unknown site's listings be held?** Decision 11 holds them without
  bound, so a site decommissioned without closing its listings leaves them advertised.
  A time bound is owed, not in this change. Whichever change takes it must also decide
  whether expiry closes as reconciliation (reopenable) or needs an operator.
- **Should the admin projection refresh keep last-known generations?** It rebuilds every
  site's caches, so pressing it during an outage turns a stale site into an unknown one,
  which decision 11 now holds. It is not in this change.
- **How is a shape generator assigned to a pool?** The generator seam exists (decision 2) but
  no pool hint selects an implementation; the default applies wherever no shape list is
  stated. Deferred to the change that introduces the first pluggable generator. It must also
  decide how a selected generator ranks against an explicit `listing_shapes` list.
