## Why

Bare metal is Goal 7's primary target domain, and its listings differ from VM's in
ways that leave them outside machinery the rest of the compute family shares.

A bare-metal listing publishes its hardware under `listing_resource.capabilities`.
The compute registry schema — which the bare-metal registry serves — filters on
top-level `listing_resource` fields (`gpu_model`, `region`, `gpu_count`, `ram_gb`,
and the rest), every one of them `on_missing: fail`. So a buyer filtering by GPU
model, region, or any dimension excludes every bare-metal listing, and the schema's
dry run reports a bare-metal listing invalid for lacking the required `gpu_model`
and `region`.

A bare-metal listing also has no capability shape. Every VM listing is a listing
shape, derived and digested through `kit/capability-shape`; bare metal derives its
listings from each Physical Resource's publication view and never forms one. A
concept keyed by shape — the published asking rate that
`publish-indicative-listing-rates` adds is the first — therefore has no key on bare
metal.

Bare metal is also absent from the site-scoped pool-override store
(`kit/pool-overrides`), which VM joined so a storefront can state its own terms for
one pool at one site. Without it a bare-metal storefront has no per-site override
tier at all.

Each of these is a place the two compute-family domains solve one problem twice or
bare metal does not solve it. The direction is that both use the same kit
mechanisms.

## What Changes

- Give the compute-family capability schema one home in a new domain package,
  `domains/compute` (`arkhai_compute`). `arkhai_vms` re-exports it as
  `VM_CAPABILITY_SCHEMA`, and bare metal binds the same schema.
- Add a schema-driven `unflatten_shape` to `kit/capability-shape` as the inverse of
  `flatten_shape`.
- Derive, for each bare-metal listing, a family-grouped capability shape from its
  Physical Resource's capacity declaration: declared quantities other than `units`,
  and the schema's attributes (`gpu_model`) from declared attributes. Require the
  `gpu` family and exactly one `units`. Hold and report a declaration that cannot be
  read this way.
- Retire `bare_metal_publication.capabilities`, the nested `listing_resource.capabilities`
  mapping, and the unpopulated `site` labels.
- Publish the shape's quantities and attributes as top-level `listing_resource` fields
  under the compute family's wire names, so the compute schema's dimension filters
  match bare-metal listings. Publish `region` from the pool's hint, and hold a pool
  that has none.
- Include the shape digest in the bare-metal derivation identity. The Physical
  Resource anchors a listing and its shape completes the identity, so a corrected
  declaration closes its listing and publishes a successor. Existing listings are
  replaced once through ordinary source reconciliation.
- Carry the listing's shape attributes on the bare-metal capacity claim beside
  `units: 1`, so admission equality-matches the published model.
- Add a minimal seller inventory guard at bare-metal opening. It rechecks the
  listing's shape and region against its own declaration and pool.
- Join bare metal to the site-scoped pool-override store for the `bare_metal`
  offering mode. Its vocabulary is settlement clauses and the terms
  `min_duration_seconds` and `max_duration_seconds`; it states no shapes. Status is
  judged against each site's last accepted publication generation.
- Move the override HTTP handling into a framework-free `PoolOverrideRouteService`
  in `kit/pool-overrides`, bound by both the VM and bare-metal storefronts.
- Add `bare-metal-storefront pool-override` (`set`, `get`, `list`, `delete`). It is
  VM's command-line layer copied over the kit's typed client, and calls the
  administrator API.

## Capabilities

### Modified Capabilities

- `storefront-publication`: a bare-metal listing carries a derived capability shape
  and publishes its fields where the compute schema reads them; its derivation
  identity includes the shape; its claim carries the shape's attributes; its opening
  rechecks shape and region against its source; bare metal joins the site-scoped
  pool-override store; and the override write's refresh-and-wake effects apply only
  where a storefront has a cache and a loop.
- `market-composition`: the compute-family capability schema is owned by a
  compute-family domain package that both compute domains bind, and
  `kit/capability-shape` provides the schema-driven inverse of flattening.

### New Capabilities

None.

## Non-Goals

- Fungible bare-metal pools. A pool whose Physical Resources all declare the same
  shape could later publish one fungible listing, but this change keeps one listing
  per Physical Resource.
- Unbacked bare-metal listings — `unbacked-bare-metal-listings`.
- Asking rates — `publish-indicative-listing-rates`, which keys them on the shape
  this change introduces.
- Changing site admission or scheduling semantics, the resource-pool projection, or
  the `bare_metal.v2` view the site produces. The claim gains an attribute that
  admission already knows how to match.
- Making bare-metal publication autonomous.
- Renaming the compute family's flat dimension spellings —
  `settle-capacity-claim-vocabulary`'s gate, which now edits one package.
- Moving bare-metal opening validation onto the kit negotiation runtime —
  `bare-metal-and-credits-domain-stacks` 4a, which takes this change's guard with it.

## Impact

- New `domains/compute/` package; `domains/vms/domain` re-exports its schema.
- `kit/capability-shape`: `unflatten_shape`.
- `kit/pool-overrides`: `PoolOverrideRouteService`; VM's admin controller reduced to
  a binding over it.
- `domains/bare_metal/src/arkhai_bare_metal/`: listing schema, shape derivation,
  classification, listing comparison, source identity, and the publication-view
  fixture. The domain package gains dependencies on `arkhai-compute` and
  `arkhai-kit-capability-shape`.
- `domains/bare_metal/storefront/`:
  - publication cycle, derivation key, and region hold;
  - claim construction on both reservation paths;
  - opening guard;
  - override routes, migration, contribution, service composition, and status;
  - the `pool-override` command group;
  - import-boundary test.
- `e2e-tests` bare-metal publication scenario: declarations move hardware into
  `capacity` and `attributes`, and discovery is asserted by a dimension filter.
- `docs/bare-metal-seller-quickstart.md`: the registration body.
- Build and packaging: the new distribution enters `.dist`, reinit targets, locks,
  and the storefront images of both domains.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the package layers gain the compute-family
      domain package. "One name per concept" and "Storefront capacity boundary" no
      longer say bare-metal listings are not listing shapes; they state that bare
      metal's shape is derived from its declaration, and that its unit is one whole
      machine held exclusively.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`
      and its `architecture.md`; `openspec/specs/market-composition/spec.md` and its
      `architecture.md`.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Storefront listing shapes and pool
      overrides" covers bare metal; "Capacity definitions" states how a bare-metal
      declaration carries its hardware.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The compute-family schema's home, and why neither the foundation kit nor the core
  holds it — `ARCHITECTURE.md` package layers and `market-composition/architecture.md`.
- `unflatten_shape` as the exact inverse of `flatten_shape` — `market-composition/spec.md`.
- A bare-metal listing's shape is derived from its declaration, and its whole unit is
  held exclusively — `storefront-publication/spec.md`, with rationale in its
  `architecture.md`.
- Bare-metal derivation identity includes the shape — `storefront-publication/spec.md`.
- Bare metal's override vocabulary, status source, and the kit route service —
  `storefront-publication/spec.md` and `architecture.md` (storefront pool overrides).

## Dependencies

- **Depends on `bare-metal-publication-reads-pool-declarations`** (complete), which makes
  bare-metal publication read projected pool declarations and policy tags — the
  region hint and the override store's pool resolution both need them.
- **Blocks `publish-indicative-listing-rates`** for bare metal, and
  `unbacked-bare-metal-listings`, whose listings need the same discoverable shape.
- Shares one capability schema and one flat dimension spelling with VM, now in one
  package. `settle-capacity-claim-vocabulary` decides that spelling for both domains
  by editing `arkhai_compute`. This change uses today's spellings, so it neither waits
  on that gate nor pre-empts it.
- **Moves with `bare-metal-and-credits-domain-stacks` 4a**: this change's opening
  guard is re-homed onto the kit's `validate_opening` hook there.
- **Informs `kit-owned-storefront-shell`**: the override route service is one of the
  framework-free services that change binds once for every storefront.
