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

- **Every listing is a listing shape.** A shape is a family-grouped statement of what one
  listing offers: GPU count and model, and optionally vCPU, memory, and storage. A pool's
  shapes come from exactly one source, in this order:
  1. the storefront's override for that site and pool;
  2. the site's new domain-neutral `listing_shapes` pool hint, a list per offering mode;
  3. otherwise the domain's default shape generator.
  
  The VM default is GPU-only, reproducing today's listings as shapes. It is generated per GPU
  model, so a pool mixing models no longer publishes one model's name over every member. The
  generator sits behind a domain interface, so pool-assigned generators such as proportional
  shapes can be added later.
- **Commitment.** A listing publishes and reserves exactly the quantities its shape declares.
  For a dimension its shape omits it makes no commitment. The site provisions it from its
  configured defaults, and keeping that capacity sufficient is the site administrator's
  responsibility. How many of a shape fit is derived from capacity declarations, never
  declared or published.
- **Feasibility.** A shape is published only where some source member satisfies the
  listing's claim under the site's resource-feasibility predicate, against declared capacity
  and, when backed, current availability.
  - The site's reservation remains the final admission boundary.
  - A stated shape no member is feasible for yields no listing and is reported; it is never
    shrunk or replaced by another source's shapes.
- **Identity.** Every listing's derivation identity includes a canonical digest of its
  shape, whatever produced it.
  - Every existing VM listing therefore closes and republishes once at upgrade, deployed
    fail-forward.
  - A seller's close or pause carries across to the successor listing.
  - Editing a shape closes the old listing and publishes a new one.
- **Site-scoped storefront overrides, as a kit capability.**
  - A durable store keyed by `(site_id, pool_id, offering_mode)` holds each market's
    commercial terms, settlement clauses, and listing shapes.
  - It lives in a new storefront-side kit, `kit/pool-overrides`, together with the write
    check, the override status, the signed-resource encoding, and a typed client extension.
    Each market supplies a contribution that validates its vocabulary and judges shape
    feasibility.
  - The core storefront client gains only universal transport.
  - It is administered through an authenticated API, typed clients, and a storefront CLI.
  - A write is checked against the site's live projection: a pool the site does not project
    is refused, and a shape no member is feasible for is reported but accepted.
  - The existing home-site override rows remain a lower tier until `pools-9` retires them;
    system status names each field a legacy row supplies.
  - System status reports each stored override as applied, orphaned, unknown (its site's
    projection is not held), site-unconfigured, or inactive (listings derive from local
    tables, where overrides do not apply).
- **A site whose projection is not held holds its listings.** A storefront deriving from
  projections no longer closes an unknown site's listings, or falls back to its local
  tables when no projection is held.
- **Family-grouped shape vocabulary**, pulled forward from `structured-capacity-requirements`:
  - shapes are declared in the family-grouped form (`gpu: {count, model}`, `cpu`, `memory`,
    `storage`);
  - they are flattened by one shared, domain-schema-driven utility in a new
    standard-library-only foundation kit, `kit/capability-shape`;
  - they are digested over that form, so the later wire rename churns nothing.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: every listing is a listing shape; shape feasibility; shape-bearing
  listing identity and the upgrade carry-over of seller state; site-scoped storefront pool
  overrides and their live-projection write check; and how a listing's published shape
  relates to its source declaration.
- `resource-pool-management`: the domain-neutral `listing_shapes` hint and its structural
  validation on every pool-write surface.
- `market-composition`: family-grouped capability shapes flattened through one shared
  utility driven by a domain-supplied schema.
- `site-capacity`: every projected resource-pool member states its resource kind, which a
  storefront needs to judge whether the member can serve a listing's claim.

## Non-Goals

- Do not negotiate on shape. A buyer naming a different shape is still refused at round
  zero. `capacity-shape-envelope`, `capacity-shape-pricing`, and
  `negotiation-driven-capacity-resize` own negotiable shapes.
- Do not add pool-assignable shape generators beyond the GPU-only default, or a hint that
  selects one.
- Do not account in the capacity ledger for dimensions a listing omits. Their provisioning is
  the site's, sized by its configured defaults.
- Do not guarantee admission at publication. Feasibility is resource feasibility; the
  reservation decides.
- Do not add per-dimension pricing or publish how many of a shape remain.
- Do not change the registry filter vocabulary or its `on_missing` semantics, and do not
  rename `ram_gb`, `disk_gb`, or `vcpu_count` on the wire. The rename is
  `structured-capacity-requirements`' to make.
- Do not let a storefront override physical facts: region, offering mode, backing, or a GPU
  model no member carries.
- Do not publish provisioning defaults, host totals, or any inferred value.
- Do not add shapes to bare-metal or API-credit publication.
- Do not support rollback. The change deploys fail-forward with the Goal 7 feature set.

## Impact

- **Affected code:**
  - `kit/capability-shape` (new foundation kit: the shared capability-shape utility);
  - `market_core` (the length-prefixed identifier encoding, moved out of the VM
    reconciler);
  - `kit/resource-pools` (hint key and structural validation; new dependency on
    `kit/capability-shape`);
  - the VM domain package (family schema, the default shape generator, VM-bound shape
    operations, and listing key builders; new dependency on `kit/capability-shape`);
  - `domains/vms/listings` (shape resolution, feasibility through the injected site
    predicate, identity fields derived from `DIMENSION_KEYS`; new dependency on
    `arkhai-vms`);
  - `kit/site-client` (the projection contract requires each member's `resource_type`);
  - the VM storefront:
    - binding envelope version 2 for every listing, and the startup carry-over of seller
      state;
    - the override store and its migration;
    - admin routes and the identity contract;
    - publication loop and inventory guard wiring;
    - system status and the CLI;
  - `kit/pool-overrides` (new): the override store, write service, status, signed-resource
    encoding, and typed client extension;
  - `core/storefront-client`: a generic `authenticated_request` on both variants, and no
    market vocabulary;
  - `provisioning/compute/service`, whose exact client pin moves with the client version;
  - `e2e-tests`, which uses the kit's typed client.
- **Behaviour:**
  - A listing with a stated shape reserves every quantity it declares. Its omitted
    dimensions stay the site's.
  - Pools without stated shapes publish the same fields as today, except that mixed-model
    pools publish per model.
  - A pool whose listings claim a region or model no member declares, so no reservation
    could be admitted, publishes nothing and is reported per pool. A member projecting no
    `resource_type` is held and reported.
  - Every VM listing closes and republishes once at upgrade, keeping seller closes and
    pauses.
  - Override writes now require the site to be reachable.
  - Under local-table derivation, overrides are stored but have no effect until `pools-9`
    removes that path.
  - An unknown site's listings stay open, where they were closed until the site returned; a
    buyer is refused at round zero meanwhile.
- **Wire:** additive for consumers. The published fields already exist in the listing model
  and the registry schema, and the new pool hint is opaque to consumers that do not read it.
  For producers, the resource-pool projection now requires each member's `resource_type`,
  which the site already projects.
- **Tests:**
  - unit tests for the utility, the schema, hint validation, fit, and keys;
  - integration tests for the override API through the typed client against the live-fetch
    fake site, and for shaped publication and reconciliation;
  - registry filter coverage;
  - a provider-input test proving that declared quantities, not defaults, size the VM;
  - upgrade tests for the identity change and the seller-state carry-over;
  - one end-to-end path in which a shape declaring every family is discovered with a
    `ram_gb` query, negotiated, reserved at its declared quantities, and provisioned with
    them.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`:
  - shape ownership across site and storefront, and site-scoped storefront overrides in the
    storefront capacity boundary and authority table;
  - the identifiers table's stale "globally unique" `pool_id` row, corrected to the
    site-local slug the resource-pool contract defines;
  - the capability-shape foundation kit in the kit layers, and the identifier encoding in
    `market_core`;
  - `listing_shapes` in the vocabulary.
- [x] Existing subsystem specifications:
  - `openspec/specs/storefront-publication/spec.md` and its `architecture.md`;
  - `openspec/specs/resource-pool-management/spec.md`;
  - `openspec/specs/market-composition/spec.md`.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md`:
  - a pool definition entry may declare `listing_shapes`;
  - storefront pool overrides are administered through the API rather than configuration,
    and have no effect while listings derive from local tables;
  - the site administrator sizes the pool VM defaults for dimensions listings omit;
  - upgrade is fail-forward: every VM listing republishes once and seller state carries
    across.
- [x] `docs/development/ROADMAP.md`: Goal 2's statements that listings advertise a GPU-only
  shape and that dimension filters match nothing.
- [ ] New subsystem specification: none.

### Knowledge to promote

- Every listing is a listing shape, from the storefront's override, the site's hint, or the
  domain's default generator. A listing commits to and reserves exactly its declared
  quantities, and how many fit is derived — `openspec/specs/storefront-publication/spec.md`.
- A shape is published only where a source member is resource-feasible for it; reservation
  remains the admission boundary — `openspec/specs/storefront-publication/spec.md`.
- Every listing's identity includes its shape digest, and seller state carries across the
  upgrade — `openspec/specs/storefront-publication/spec.md`.
- Storefront pool overrides are addressed by site, pool, and offering mode, validated by the
  owning market, durable, outlive their pool, report one status each (an unloaded site is
  unknown, not absent), and are written against the site's live projection —
  `openspec/specs/storefront-publication/spec.md`.
- An unknown site's listings are held, and projection derivation never falls back to local
  tables — `openspec/specs/storefront-publication/spec.md`.
- The pool-override kit, its per-market contribution seam, and core holding only universal
  transport — `docs/development/ARCHITECTURE.md` (kit layers) and
  `openspec/specs/storefront-publication/architecture.md`.
- Why a published dimension is a commitment, why shapes are stated or generated rather than
  inferred, the generator seam, and why the storefront is the final authority within
  declared capacity — `openspec/specs/storefront-publication/architecture.md`.
- Omitted dimensions are the site administrator's to size through configured defaults —
  `openspec/specs/storefront-publication/architecture.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
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
