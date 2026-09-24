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
- **The utility lives in `market_core`, not `kit/site`.** `structured-capacity-requirements`
  said "probably `kit/site`". `market_core` is dependency-light and importable by the site,
  the pool kit, storefronts, and domains. The VM listings and negotiation packages
  deliberately avoid depending on `kit/site`. The CLI query parser set this precedent.
- **The digest is taken over the family form.** A later rename then changes no listing key
  and churns nothing.

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

**When no member is feasible for a shape:**
- The shape yields no listing, and the storefront reports it in system status, naming the
  site, pool, shape digest, and what was not feasible.
- It never shrinks the shape and never falls back to another source's shapes.
- A listing whose shape becomes infeasible closes through ordinary source reconciliation,
  because its key is no longer derived.
- A default shape that is not currently feasible is not reported: that is ordinary
  unavailability. Only declared shapes are reported.

**Holds are unchanged.** A member with an unreadable GPU count holds the listings of its pool
(fungible) or its own (specific resource), as today.

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
- **Precedence, highest first.**
  - Commercial fields: the new store; the legacy home-site `compute_capacity_pools` row; the
    pool's hint; the storefront's configured default.
  - Shapes: the new store; the pool's `listing_shapes` hint; otherwise the domain's default
    shape generator.
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
  own semantic operation in the administrator identity contract. Its signed resource uses
  the same length-prefixed encoding as derivation keys. That encoding moves into a small
  neutral `market_core` module, byte-identical, so both the reconciler and the
  administrator identity contract depend on it rather than the middleware depending on
  the reconciler. The routes inherit durable
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
- **The response.** It returns the stored record and a feasibility report per shape, computed
  from the same live generation and labelled with its revision and digest. A shape no member is
  feasible for is reported, and the override is accepted anyway; the resulting delisting is
  the intended side effect. The live fetch does not write the cache. After a write the storefront
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

### Retained: omission beats inference

A pool with no declared shapes publishes the default shapes, which declare nothing beyond GPU
count and model. The original reasoning still applies to it:

- `on_missing: fail` treats an omission as honest ignorance and excludes the listing.
- A wrong value is treated as a truthful claim and includes it.
- Under-matching is a discovery inconvenience; over-matching sells capacity the seller has
  not declared.

Provisioning defaults are never published.

## Risks / Trade-offs

- **[Declared shapes change what is reserved and provisioned]** → Intended: the buyer gets
  every quantity the listing states. A declaration that overstates what the hypervisor can
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
- **[Shapes can be stated in two places]** → Whole-list replacement makes the effective list
  exactly one source's. System status names each pool's source.
- **[A deleted override reveals a legacy value]** → Reported in system status whenever a
  legacy value is in effect; ends when `pools-9` retires the tier.
- **[A site outage blocks override writes]** → Intended: the write is refused as retryable
  rather than accepted unverified.
- **[Scope]** → The work lands as two reviewable slices within this change (see
  `tasks.md`). Shared vocabulary, shape derivation, identity, and discovery come first; the
  override store and its control plane second.
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

Older storefronts ignore the unknown `listing_shapes` tag, as the hint contract requires, and
older pool kits store it without validation.

## Coordination with other changes

Recorded in each change's own design where it changes that change's plan.

- **`structured-capacity-requirements`.** Decision 3 implements its family-grouped shape
  form, the shared utility, and the VM family schema for listing shapes, places the utility
  in `market_core`, and records the flat-name exception its rename resolves.
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
- implementation lands as two reviewable slices (`tasks.md`);
- a provider-input test is added;
- the stale "globally unique `pool_id`" row in `docs/development/ARCHITECTURE.md`'s
  identifiers table is corrected at promotion.

## Open Questions

- **Should the override store become domain-neutral?** Deferred to Goal 4's kit extraction,
  where a second domain needs storefront pool overrides.
- **How is a shape generator assigned to a pool?** The generator seam exists (decision 2) but
  no pool hint selects an implementation; the default applies wherever no shape list is
  stated. Deferred to the change that introduces the first pluggable generator. It must also
  decide how a selected generator ranks against an explicit `listing_shapes` list.
