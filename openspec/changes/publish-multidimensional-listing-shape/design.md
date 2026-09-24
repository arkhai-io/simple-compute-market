# Design

## Context

Re-verified against the code on 2026-09-24. Several facts recorded when this change was
first written had moved; the corrected picture is below, and the decisions that follow
depend on it.

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
- The VM buyer sends no `compute_resource` in its provision terms, so the round-0
  shape-mismatch guard does not fire for a buyer accepting a listing's own shape.

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

## Goals / Non-Goals

**Goals:**

- A site administrator and a storefront administrator can each state which shapes a pool is
  listed in, and the storefront's choice wins.
- A listing in a declared shape publishes, reserves, and provisions exactly that shape.
- No listing publishes a shape its physical source cannot hold.
- Storefront overrides are durable, scoped to a site and pool, and administered through an
  authenticated API.
- Nothing this change stores or keys on needs rework when `structured-capacity-requirements`
  lands.
- A pool that declares no shape publishes exactly what it publishes today.

**Non-Goals:**

- Buyer-negotiated shapes. `capacity-shape-envelope`, `capacity-shape-pricing`, and
  `negotiation-driven-capacity-resize` own those.
- Per-dimension pricing; publishing how many of a shape remain.
- Changing the registry filter vocabulary, its `on_missing` semantics, or renaming the
  published `ram_gb`/`disk_gb`/`vcpu_count` fields.
- Storefront overrides of physical facts: `region`, `offering_mode`, capacity backing.
- Shapes for bare-metal or API-credit listings.

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

So dimensions beyond GPU count are published only on a listing whose shape someone chose
(decision 2).

### 2. Listing shapes are chosen, and how many fit is derived

A pool may carry a list of **listing shapes** for each offering mode. The pool's site
declares them in the domain-neutral `listing_shapes` pool hint; the storefront may replace
the list for that pool through its override store (decision 6). A pool with a list publishes
exactly its listed shapes and does not enumerate GPU counts. A pool with no list, from
either source, keeps GPU-count enumeration unchanged and publishes no dimension beyond GPU
count.

- **A list per offering mode.** One pool may be sold as several form factors; a VM shape and
  a future container shape are different declarations. The hint is keyed by offering mode:
  `listing_shapes: {vm: [<shape>, ...]}`.
- **A list, not a single shape.** Eight 1-GPU VMs and one 8-GPU VM can be offered from the
  same host at once; the site already arbitrates between them, because admission debits every
  dimension.
- **Count is derived, never declared or published.** A declared count would be a second
  authority on quantity beside the capacity declarations and would drift from them. Whether a
  shape is publishable follows from decision 4.
- **Cardinality is unchanged.** A fungible pool publishes one listing per shape; a
  specific-resource pool publishes one listing per member per shape that member can hold.
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

The roadmap's Goal 2 frames fixed shapes as the problem it removes. Chosen shapes are
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

2. **One shared flattening utility** in `market_core`, beside `market_core.query_dsl`. It
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

- **`gpu.model` sits inside the shape.** A shape fits only members of its own model, so a
  pool whose members have different models publishes one listing per shape, never a listing
  that mixes models. Pricing already resolves per GPU model, and it takes the model from the
  shape.
- **An optional family the shape omits is no commitment.** The listing does not publish it
  and the claim does not reserve it, as the commitment rule requires.
- **The flat names are an explicit exception.** The flat names are today's wire names rather
  than the family-prefixed names the convention would produce (`memory_gib`, `storage_gib`).
  The exception is recorded; when `structured-capacity-requirements` renames the wire, the
  change is two rows of this schema plus the wire rename it already owns. The units already
  agree: `ram_gb` and `disk_gb` are GiB (see Context).
- **The utility lives in `market_core`, not `kit/site`.** `structured-capacity-requirements`
  said "probably `kit/site`". `market_core` is dependency-light and importable by the site,
  the pool kit, storefronts, and domains. The VM listings and negotiation packages
  deliberately avoid depending on `kit/site`. The CLI query parser set this precedent.
- **The digest is taken over the family form.** A later rename then changes no listing key
  and churns nothing.

Stays in `structured-capacity-requirements`: the buyer-facing `requirements` object, the
claim restructure and the `probe` signature, the `offering_mode`/`resource_type` split, the
wire rename, and expressing the site's resource side in the family form.

### 4. A shape is publishable only where its source can hold it

A shape is consistent with its source when a member can admit the claim the listing would
produce:

- **Fungible pool:** some single enabled member.
- **Specific-resource pool:** that member.
- **Unbacked listing:** declared fit only; a member's declared `capacity` must admit the claim.
- **Capacity-backed listing:** declared fit, and additionally every dimension of the shape is
  currently available on that member according to the projection's per-member `available`
  map. A member that reports no `available` is unknown rather than empty and is treated as
  its declared capacity, as today's unknown-availability rule does, with admission deciding.
  Capacity buckets are not used for shaped pools, because their grouping may not carry every
  dimension.

**Fit uses the site's own predicate.** The storefront evaluates fit with the site's exported
claim predicate, `dict_resource_satisfies_claim`. It is injected through the storefront's
composition, as the placement matcher already is, so `domains/vms/listings` gains no
`kit/site` dependency. Declared fit evaluates the predicate against declared capacity;
availability evaluates it against `available`. So the storefront publishes a shape exactly
when the site would admit it, apart from projection staleness. The same predicate answers
the inventory guard's declared-match question. This settles the design's earlier question of
where the shared predicate should live.

**Consequence:** the claim requires the attributes it names, including `region`. A pool that
states its region only through the pool hint, with members that do not declare it, has
shapes that fit nothing. Admission would refuse their claims anyway; planning verifies the
parity.

**When a shape does not fit:**

- The shape yields no listing, and the storefront reports it in system status, naming the
  site, pool, shape digest, and the field that failed.
- It never shrinks the shape to fit, and never falls back to the pool hint's list or to
  GPU-count enumeration: each would publish something nobody chose.
- A listing whose shape stops fitting closes through ordinary source reconciliation, because
  its key is no longer derived.

**Holds are unchanged.** A member with an unreadable GPU count holds the listings of its pool
(fungible) or its own (specific resource), as today.

### 5. A shaped listing's identity includes its shape

- **Structural key.** A shaped candidate's reconciler key includes the site, the pool or
  resource, and the shape digest.
- **Binding envelope.** A shaped listing's binding envelope is `compute.listing_source`
  schema version 2, carrying the site, pool, resource, and the canonical shape. Its
  derivation key therefore never collides with a version 1 binding.
- **Reading the key back.** The key a stored shaped listing occupies is read from its binding
  envelope rather than recomputed from the published listing, because flattening is not
  required to be invertible.
- **Editing a shape.** The old key stops being derived, so the old listing closes and a
  listing under the new key publishes.
- **Enumeration listings.** They keep version 1 envelopes and their current keys, so adopting
  this change churns no existing listing. Churn would have been acceptable; it is not needed.

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
- **Precedence, highest first.**
  - Commercial fields: the new store; the legacy home-site `compute_capacity_pools` row; the
    pool's hint; the storefront's configured default.
  - Shapes: the new store; the pool's `listing_shapes` hint; otherwise GPU-count enumeration.
- **The legacy tier stays until `pools-9`.** It remains live for as long as its writer, the
  resource import, exists; `pools-9` retires both together. A migration could not attribute
  legacy rows to a site without reading live configuration, which `pools-8` found unsafe.
  System status reports every pool where a legacy value is in effect, so deleting a new
  override and seeing a legacy value reappear is visible.
- **Durable intention.** An override outlives its pool. If the pool disappears from the
  projection the override has no effect and is reported as orphaned; if the pool returns, it
  applies again.
- **Not a common store yet.** A domain-neutral store in the common storefront database was
  considered and deferred to Goal 4's kit extraction. The fields here are VM commercial
  vocabulary.

### 7. The override API checks the site's live projection before accepting

- **Routes.** Under `/api/v1/admin/`:
  - `PUT /pool-overrides` replaces one record.
  - `GET /pool-overrides` with `site_id` and `pool_id` reads one; without them it lists all,
    optionally filtered by `site_id`.
  - `DELETE /pool-overrides` with `site_id` and `pool_id` removes one. It is idempotent.
- **Addressing.** Site and pool IDs are operator-chosen strings with no character
  restriction, so they travel in the body or query rather than the path. Each route has its
  own semantic operation in the administrator identity contract, and its signed resource
  uses the same length-prefixed encoding as derivation keys. The routes inherit durable
  replay reservation from the administrator middleware.
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
- **The response.** It returns the stored record and a fit report per shape, computed from
  the same live generation and labelled with its revision and digest. A shape that fits no
  member is reported, and the override is accepted anyway; the resulting delisting is the
  intended side effect. The live fetch does not write the cache. After a write the storefront
  triggers a projection refresh and wakes the publication loop, so the override takes effect
  promptly. For a full preview of the next cycle, the operator uses the existing publication
  dry run.
- **Clients and CLI.** Methods on both storefront client variants, covered by the
  sync/async parity test, and a `market-storefront` command group that reads a record from
  a document and calls the client.

### 8. Pool hints are validated for structure at the site, and for vocabulary by the domain

- **At the site.** Every pool-write surface validates `listing_shapes` through one shared
  structural check: create, replace, patch, and bulk import. The value must be a mapping of
  offering mode to a non-empty list of well-formed family-grouped shapes. This is the same
  treatment the SLA and hold hints get. The pool kit calls the structural validator in
  `market_core`, gaining a downward dependency on `arkhai-core`, and learns no dimension
  names.
- **At the storefront.** The VM domain validates its vocabulary during derivation. A pool
  whose `vm` list it cannot read yields no shaped listing and is reported. Its existing
  shaped listings are held rather than closed, because an unreadable declaration is not a
  withdrawn one. The pool does not fall back to enumeration.
- **At an override write.** A shape outside the vocabulary is refused (decision 7).

### 9. What a shaped listing publishes

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

### Retained: omission beats inference

A pool with no shape list publishes no dimension beyond GPU count. The original reasoning
still applies to it:

- `on_missing: fail` treats an omission as honest ignorance and excludes the listing.
- A wrong value is treated as a truthful claim and includes it.
- Under-matching is a discovery inconvenience; over-matching sells capacity the seller has
  not declared.

Provisioning defaults are never published.

## Risks / Trade-offs

- **[Shaped listings change what is reserved and provisioned]** → Intended: the buyer gets
  the shape the listing states. The fit rule checks shapes only against declarations. A
  declaration that overstates what the hypervisor can allocate now fails at fulfillment
  rather than being hidden by pool defaults. Declaration accuracy stays the site operator's
  responsibility.
- **[Shapes can be stated in two places]** → Whole-list replacement makes the effective list
  exactly one source's. System status names the source of each pool's list.
- **[A deleted override reveals a legacy value]** → Reported in system status whenever a
  legacy value is in effect; ends when `pools-9` retires the tier.
- **[A site outage blocks override writes]** → Intended: the write is refused as retryable
  rather than accepted unverified.
- **[Scope]** → The store, API, and shared utility make this change larger than first
  proposed. That was accepted deliberately to avoid a follow-up that `pools-9` would also
  depend on.
- **[Naming exception]** → Recorded in decision 3 and in
  `structured-capacity-requirements`' design, where the rename is owned.

## Migration Plan

Additive:

- one new storefront table, and no data migration;
- the pool hint is optional, and a pool without it publishes exactly as before;
- version 2 envelopes are written only for new shaped listings;
- older storefronts ignore the unknown `listing_shapes` tag, as the hint contract requires,
  and older pool kits store it without validation.

Rollback is a code revert. A reverted storefront derives no shaped candidate, so source
reconciliation closes every shaped listing, and the override table is left unread.

## Coordination with other changes

Recorded in each change's own design where it changes that change's plan.

- **`structured-capacity-requirements`.** Decision 3 implements its family-grouped shape
  form, the shared utility, and the VM family schema for listing shapes, places the utility
  in `market_core`, and records the flat-name exception its rename resolves.
- **`pools-9-retire-local-physical-authority`.** The override endpoint its design planned
  over `compute_capacity_pools` is superseded by decision 7. It still retires the legacy
  override tier with its writer.
- **`capacity-shape-envelope`.** Its bounds should use the same family-grouped vocabulary
  through the shared utility. Once bounds exist, the fit check in decision 4 also asks
  whether the pool admits the shape.
- **`capacity-shape-pricing`.** It prices shaped listings; per-model pricing already resolves
  from the shape's `gpu.model`.
- **`pools-8-capacity-projection-and-listing-hints`.** Its `vm.ansible_pool_defaults.v1` view
  remains a provisioning default and is not a listing shape (decision 2).

## Open Questions

- **Does GPU-count enumeration still need a kind partition for fungible pools whose members
  have different GPU models?** Enumerated pools keep today's behaviour: the first member's
  model is published, and a warning names the pool and the differing models. Shapes remove
  the problem for any pool that declares them, since each shape names its model. Deferrable
  because enumeration publishes no dimension beyond GPU count, so first-member-wins cannot
  publish a wrong RAM, vCPU, or disk quantity. Revisit if enumeration is kept for pools that
  mix models in practice, or when a change proposes retiring enumeration.
- **Should the override store become domain-neutral?** Deferred to Goal 4's kit extraction,
  where a second domain needs storefront pool overrides.
