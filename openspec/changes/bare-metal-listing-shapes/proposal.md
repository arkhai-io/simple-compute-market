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

- Derive, for each bare-metal listing, a family-grouped capability shape matching
  its Physical Resource's declared dimensions exactly, through `kit/capability-shape`.
- Publish that shape's quantities and attributes as top-level `listing_resource`
  fields under the compute family's wire names, so the compute schema's dimension
  filters match bare-metal listings; publish `region` from the pool's hint as VM does.
- Join bare metal to the site-scoped pool-override store for the `bare_metal`
  offering mode, with bare metal's own vocabulary for the terms and settlement
  clauses an override may state.
- Keep a bare-metal listing's identity the Physical Resource it offers.

## Capabilities

### Modified Capabilities

- `storefront-publication`: a bare-metal listing carries a capability shape matching
  its Physical Resource and publishes that shape's fields where the compute schema
  reads them; bare metal joins the site-scoped pool-override store.

### New Capabilities

None.

## Non-Goals

- Fungible bare-metal pools. A pool whose Physical Resources all declare the same
  shape could later publish one fungible listing, but this change keeps one listing
  per Physical Resource.
- Unbacked bare-metal listings — `unbacked-bare-metal-listings`.
- Asking rates — `publish-indicative-listing-rates`, which keys them on the shape
  this change introduces.
- Changing site admission, scheduling, or fulfillment for bare metal.
- Making bare-metal publication autonomous.

## Impact

- `domains/bare_metal/src/arkhai_bare_metal/` publication derivation and listing
  schema.
- The bare-metal storefront's publication path and a `bare_metal` market
  contribution to `kit/pool-overrides`.
- `openspec/specs/storefront-publication/spec.md`: "Every VM listing is a listing
  shape" currently states that bare-metal listings are not listing shapes.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — the "One name per concept" section says a
      listing shape is what VM publication uses; re-confirm at implementation time.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

## Dependencies

- **Depends on `bare-metal-publication-reads-pool-declarations`** (complete), which makes
  bare-metal publication read projected pool declarations and policy tags — the
  region hint and the override store's pool resolution both need them.
- **Blocks `publish-indicative-listing-rates`** for bare metal, and
  `unbacked-bare-metal-listings`, whose listings need the same discoverable shape.
- Shares one capability schema and one flat dimension spelling with VM;
  `settle-capacity-claim-vocabulary` decides that spelling for both domains, and
  this change follows whichever it takes.
