## Why

Once a buyer can request a capacity shape, a seller has to say which shapes it will
sell. Nothing expresses that today. `has_matching_inventory_guard` checks a listing
against its own source; a pool's `listing_shapes` hint lists what it advertises, not
what a buyer may ask for; site admission bounds only physical capacity, offering mode,
and the host requirement. No structure states that a seller will rent between 1 and 8
GPUs, or at most 512 GiB of memory, per deal — and publication cannot keep a stated
shape out on those grounds.

The concept is not domain-specific: a per-dimension admissible range is the same for VM
vCPUs, bare-metal disk, pod memory, and inference tokens, so it belongs in a foundation
kit beside the shape and pricing kits rather than being rebuilt per domain.

The interface matters more than the first implementation. A static minimum and maximum
per dimension is a box, but a seller's real policy can couple dimensions — at most
64 GiB of memory per GPU requested — and buyer and seller are expected to negotiate
dimensions with counter-proposals. An interface that returns readable bounds would make
either a rewrite of every caller; one that takes the whole shape and answers questions
about it makes them new implementations.

## What Changes

- A new foundation kit, `kit/capability-admissibility`, with a whole-shape check that
  returns structured problems and a query for the values one dimension may take given a
  partial shape, such that a counter-proposal can be built one dimension at a time
  without search. A static per-field minimum/maximum is the only implementation. No
  operation exposes readable bounds.
- A `shape_bounds` pool policy tag, keyed by offering mode, holding named constraint
  sections; this change defines `bounds`. Unknown sections and keys make a declaration
  unreadable, so later constraint forms fail closed on older readers.
- Storefront resolution of bounds per field across the site-scoped pool override, the
  pool hint, and a configured default, where a higher tier may replace a value but not
  remove it.
- VM and bare-metal publication never advertise an inadmissible shape; an unusable or
  empty declaration closes the pool's listings and is reported. The VM default generator
  generates only admissible shapes. Override writes are checked.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

Provisional; planning and review confirm the destinations (`design.md`, D11).

- `market-composition`: the admissibility kit's contract.
- `resource-pool-management`: the `shape_bounds` hint and its write-time validation.
- `storefront-publication`: tier resolution, publication and generator behavior, the
  override write check, and the reports.

## Non-Goals

- Occupancy-dependent bounds. A limit that depends on what is already rented is
  availability, owned by `negotiation-capacity-feasibility-probe` and site admission.
- Coupled constraint sections (`ratios`, `required`) and bounds keyed by attribute value.
  The declaration and interface admit them; this change ships `bounds` only.
- Site-enforced limits. Admissibility is the storefront's policy; site admission is
  unchanged.
- Pricing shapes (`capacity-shape-pricing`, archived) and categorical constraints.
- Negotiation wiring. `negotiation-driven-capacity-resize` composes admissibility first
  in the seller's round; this change records inputs to it.
- Disclosing bounds to buyers (`publish-shape-bounds`).

## Impact

- New distribution `kit/capability-admissibility` (`arkhai-kit-capability-admissibility`).
- `kit/resource-pools`: the tag key, a raw reader, and the structural check on every
  pool-write surface.
- VM: `arkhai_vms` binds the implementation and validates declarations against
  `VM_CAPABILITY_SCHEMA`; the VM storefront's publication, default generator, pool
  override terms and contribution, configuration, and derivation report.
- Bare metal: the storefront's publication, pool override terms, configuration, and
  derivation report.
- Not affected: site admission and the ledger, scheduling, fulfillment, pricing, the
  registry, negotiation.
- Tests: kit unit tests against a synthetic schema and an import-boundary test; hint
  validation; tier resolution; VM and bare-metal publication; the override write check;
  one end-to-end run publishing from a pool that declares bounds.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the foundation kit list, and an
      authority-boundary row for which shapes a storefront sells.
- [x] Existing subsystem specification — provisional: `market-composition`,
      `resource-pool-management`, `storefront-publication`.
- [ ] New subsystem specification — none.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — the configured default.

### Knowledge to promote

Destinations are provisional (D11).

- The admissibility contract: whole shape in, structured problems out, never readable
  bounds; `admissible_values` and its one-dimension-at-a-time guarantee; the opaque
  value set; omitted dimensions are free; sections intersect; unknown sections and keys
  are unreadable — `openspec/specs/market-composition/spec.md`.
- Why the interface is shaped for coupled declared constraints and counter-proposals,
  why occupancy is excluded, and why the declaration has sections —
  `openspec/specs/market-composition/architecture.md`.
- The `shape_bounds` hint and its write-time structural check —
  `openspec/specs/resource-pool-management/spec.md`.
- Per-field tier resolution without removal; unusable and empty declarations close
  listings; inadmissible shapes are not published; the generator; the override check;
  the reports — `openspec/specs/storefront-publication/spec.md`.
- Admissibility is the storefront's policy and a pool bound an advisory site default;
  absence commits nothing; why bounds close where pricing holds —
  `openspec/specs/storefront-publication/architecture.md`.
- The foundation kit and the authority boundary — `docs/development/ARCHITECTURE.md`.
- The configured default — `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- The negotiation invariant and the omitted-dimension refusal —
  `negotiation-driven-capacity-resize`'s own deltas; not promoted by this change.

## Dependencies and Related Changes

- No prerequisites; closes out on its publication callers alone.
- Consumed by `negotiation-driven-capacity-resize`, whose seller round evaluates
  admissibility first; `design.md` records the inputs it takes.
- Complements `negotiation-capacity-feasibility-probe`: admissibility asks whether the
  seller would sell a shape, the probe whether the site can serve it now.
- `publish-shape-bounds` discloses the resolved bounds to buyers and depends on this
  change.
