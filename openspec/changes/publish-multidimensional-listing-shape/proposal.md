## Why

A VM listing's `listing_resource` carries GPU model and count, SLA, region, pool identity,
offering mode, and capacity backing, and never vCPU, RAM, or disk. The registry's
`vcpu_count`, `ram_gb`, and `disk_gb` range filters carry `on_missing: fail`, so **a buyer
filtering on RAM today matches no listing at all**, even though the registry schema and the
buyer's typed resource query both support it.

Publishing the dimensions a projection declares is not enough to fix this, because a
published dimension is not only descriptive. The capacity claim copies every published
dimension, site admission reserves each one, and fulfillment builds the VM from the reserved
dimensions. Publishing an 8-GPU, 512 GiB member's RAM on its 1-GPU slice would reserve the
whole host's memory for one GPU and build a 1-GPU VM with all of it.

What is missing is a way to say which shape a pool is sold in. Today the storefront derives
every listing by enumerating GPU counts, and nothing lets a site administrator or a
storefront administrator choose a shape. That is a byproduct of automating derivation, not a
recorded decision. Storefront overrides for a pool also exist only as local rows keyed by
pool alone. They apply only to the storefront's home site and have no administration API, so
a storefront cannot be the final authority over listings from any other site.

## What Changes

- **Listing shapes.** A pool may be listed in chosen shapes: a list per offering mode, each
  shape stating its GPU count and model and, optionally, vCPU, memory, and storage.
  - A site declares them in a new domain-neutral `listing_shapes` pool hint.
  - A storefront may replace the list per pool.
  - A pool with a list publishes exactly those shapes. A pool without one keeps today's
    GPU-count enumeration, byte-identical.
- **What a shaped listing publishes and reserves.** It publishes every quantity its shape
  declares, under the existing wire names. It reserves and provisions exactly that shape.
  How many of a shape fit is derived from capacity declarations, never declared or
  published.
- **Consistency.** A shape is publishable only where a member of its source can admit the
  listing's claim, judged by the site's own claim predicate. For a capacity-backed listing,
  every dimension of the shape must also be currently available. A shape that fits nothing
  yields no listing and is reported; it is never shrunk, and never replaced by another
  source's shapes.
- **Identity.** A shaped listing's derivation identity includes a canonical digest of its
  shape, so editing a shape closes the old listing and publishes a new one. Existing
  enumeration listings keep their identities.
- **Site-scoped storefront overrides.**
  - A durable store keyed by `(site_id, pool_id)` holds SLA, pricing, settlement clauses,
    and listing shapes.
  - It is administered through an authenticated API, typed clients, and a storefront CLI.
  - A write is checked against the site's live projection: a pool the site does not project
    is refused, and a shape that fits no member is reported but accepted.
  - The existing home-site override rows remain a lower tier until `pools-9` retires them.
- **Family-grouped shape vocabulary**, pulled forward from `structured-capacity-requirements`:
  - shapes are declared in the family-grouped form (`gpu: {count, model}`, `cpu`, `memory`,
    `storage`);
  - they are flattened by one shared, domain-schema-driven utility in `market_core`;
  - they are digested over that form, so the later wire rename churns nothing.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: listing shapes, shape consistency, shaped-listing identity,
  site-scoped storefront pool overrides and their live-projection write check, and how a
  shaped listing's published shape relates to its source declaration.
- `resource-pool-management`: the domain-neutral `listing_shapes` hint and its structural
  validation on every pool-write surface.
- `market-composition`: family-grouped capability shapes flattened through one shared
  utility driven by a domain-supplied schema.

## Non-Goals

- Do not negotiate on shape. A buyer naming a different shape is still refused at round
  zero. `capacity-shape-envelope`, `capacity-shape-pricing`, and
  `negotiation-driven-capacity-resize` own negotiable shapes.
- Do not add per-dimension pricing or publish how many of a shape remain.
- Do not change the registry filter vocabulary or its `on_missing` semantics, and do not
  rename `ram_gb`, `disk_gb`, or `vcpu_count` on the wire. The rename is
  `structured-capacity-requirements`' to make.
- Do not let a storefront override physical facts: region, offering mode, backing, or a GPU
  model no member carries.
- Do not publish provisioning defaults, host totals, or any inferred value for a pool that
  declares no shape.
- Do not add shapes to bare-metal or API-credit publication.

## Impact

- **Affected code:**
  - `market_core` (new shared capability-shape utility);
  - `kit/resource-pools` (hint key and structural validation; new dependency on
    `arkhai-core`);
  - the VM domain package (family schema);
  - `domains/vms/listings` (shaped candidates, fit through the injected site predicate, shape
    keys, identity fields derived from `DIMENSION_KEYS`; new dependency on `arkhai-vms`);
  - the VM storefront (binding envelope version 2, override store and migration, admin
    routes and identity contract, publication loop and inventory guard wiring, system
    status, CLI);
  - `core/storefront-client` (override methods on both variants).
- **Behaviour:**
  - Shaped listings reserve and provision their full shape instead of GPU count plus pool
    defaults.
  - Pools without shapes are unchanged.
  - Override writes now require the site to be reachable.
- **Wire:** additive. The published fields already exist in the listing model and the
  registry schema. The new pool hint is opaque to consumers that do not read it.
- **Tests:**
  - unit tests for the utility, the schema, hint validation, fit, and keys;
  - integration tests for the override API through the typed client against the live-fetch
    fake site, and for shaped publication and reconciliation;
  - registry filter coverage;
  - one end-to-end path in which a declared shape is discovered with a `ram_gb` query,
    negotiated, and provisioned at that shape.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`:
  - shape ownership across site and storefront, and site-scoped storefront overrides in the
    storefront capacity boundary and authority table;
  - the shared capability-shape utility in `market_core` in the package layers;
  - `listing_shapes` in the vocabulary.
- [x] Existing subsystem specifications:
  - `openspec/specs/storefront-publication/spec.md` and its `architecture.md`;
  - `openspec/specs/resource-pool-management/spec.md`;
  - `openspec/specs/market-composition/spec.md`.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md`: a pool definition entry may declare
  `listing_shapes`, and storefront pool overrides are administered through the API rather
  than configuration.
- [x] `docs/development/ROADMAP.md`: Goal 2's statements that listings advertise a GPU-only
  shape and that dimension filters match nothing.
- [ ] New subsystem specification: none.

### Knowledge to promote

- A pool's listing shapes are chosen by its site and replaced per pool by its storefront. A
  shaped listing publishes, reserves, and provisions its shape, and how many fit is derived
  — `openspec/specs/storefront-publication/spec.md`.
- A shape is publishable only where the site's own predicate admits it, against declared
  capacity and, when backed, current availability. An unfit shape is reported and never
  substituted — `openspec/specs/storefront-publication/spec.md`.
- A shaped listing's identity includes its shape digest —
  `openspec/specs/storefront-publication/spec.md`.
- Storefront pool overrides are site-scoped, durable, outlive their pool, and are written
  against the site's live projection — `openspec/specs/storefront-publication/spec.md`.
- Why a published dimension is a commitment, why shapes are chosen rather than inferred, and
  why the storefront is the final authority within physical bounds —
  `openspec/specs/storefront-publication/architecture.md`.
- `listing_shapes` hint and structural validation —
  `openspec/specs/resource-pool-management/spec.md`.
- One shared, schema-driven flattening utility for family-grouped capability shapes —
  `openspec/specs/market-composition/spec.md`; its place in the package layers —
  `docs/development/ARCHITECTURE.md`.

## Dependencies and Related Changes

- Independent of every other active change; can be implemented now.
- Implements part of `structured-capacity-requirements`' accepted direction: the shape form,
  the shared utility, and the VM family schema. That change keeps the buyer-facing
  `requirements` object, the claim restructure, and the wire rename.
- Supersedes the storefront override endpoint `pools-9-retire-local-physical-authority`
  planned. `pools-9` still retires the legacy override tier together with its writer.
- Prerequisite for `capacity-shape-pricing`, which prices the shapes this change publishes.
- `capacity-shape-envelope`'s bounds should use the same vocabulary. Once they exist,
  publication's fit check also asks whether the pool admits the shape.
