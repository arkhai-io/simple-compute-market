## Why

Once a buyer can request a capacity shape, a seller has to decide which shapes it will
even consider. Nothing expresses that today: `has_matching_inventory_guard` compares
`region` and `gpu_model` by equality, and no structure anywhere states that a pool will
serve between 1 and 8 GPUs, or at most 512 GiB of RAM per reservation.

The constraint is not domain-specific. A per-dimension admissible range is the same
concept for VM vCPU shares, bare-metal disk, Kubernetes pod memory, and inference
tokens, so it belongs in the kit layer beside the matching contract it feeds rather than
being reinvented per domain as domains are added.

The shape of the abstraction matters more than the first implementation. A static
minimum and maximum per dimension is a **box**. The real constraint is coupled and
occupancy-dependent — the RAM available to one more VM depends on how many cards are
already rented and how much memory those reservations took — so the feasible region is
not a box and its bounds move as capacity is consumed. Building a box behind a
box-shaped interface would make the coupled version a rewrite. Building a box behind a
predicate-and-range interface makes it a second implementation.

## What Changes

- Add a kit-level admissibility capability answering two questions: whether a proposed
  shape is admissible for a pool, and what range remains admissible for one dimension
  given the rest of a proposed shape.
- Ship a static per-dimension minimum/maximum implementation as the first and only
  answer to both.
- Express a pool's bounds as pool policy, resolved through the existing hint mechanism
  rather than a new configuration channel.
- Keep the interface free of any assumption that bounds are static, independent, or
  expressible as a pair of numbers, so an occupancy-derived implementation replaces the
  static one without touching callers.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: a site authority exposes, alongside its existing matching contract, a
  domain-neutral admissibility check for a proposed capacity shape and the admissible
  range for a single dimension given the remainder of that shape.

## Non-Goals

- Do not implement occupancy-derived or coupled bounds. The interface admits them; this
  change ships the static implementation only.
- Do not price shapes. `capacity-shape-pricing` owns what a shape costs; this change
  owns which shapes are considered at all.
- Do not check current availability. Admissibility is a policy question answerable from
  a pool's declared bounds; whether the site can serve a shape *right now* is
  `negotiation-capacity-feasibility-probe`'s authoritative check. A shape can be
  admissible and momentarily unservable, and the two answers must stay separable.
- Do not change reservation admission. `_find_candidate` already matches
  multidimensionally and is unaffected.
- Do not extend bounds to categorical attributes. Ranges are quantitative; categorical
  matching by equality already works.

## Impact

- Affected code: `kit/site` (the admissibility capability beside the existing matching
  contract), `kit/resource-pools`' hint vocabulary for the bounds, and the VM domain's
  composition root to supply its dimension vocabulary.
- Affected tests: `kit/site` unit suites, hint resolution, and a VM-level test proving
  the domain supplies bounds without kit knowing the dimension names.
- Not affected: reservation admission, scheduling, pricing, publication.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — re-confirm at implementation time; the
      authority boundaries are unchanged.
- [x] Existing subsystem specification — `openspec/specs/site-capacity/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Admissibility is answered as a predicate plus a per-dimension range, never as a
  static bounds pair the caller reads directly —
  `openspec/specs/site-capacity/spec.md`.
- Why the interface is shaped for a coupled, occupancy-dependent feasible region even
  though the first implementation is a box —
  `openspec/specs/site-capacity/architecture.md`.

## Dependencies and Related Changes

- Consumed by `capacity-shape-pricing`'s seller feasibility guard and by
  `negotiation-driven-capacity-resize`'s rejection of an out-of-range counter-offer.
  Independent of both; can land in any order.
- Complements `negotiation-capacity-feasibility-probe`: this change answers "would the
  seller consider this shape," that one answers "can the site serve it now."
- Uses `kit/resource-pools`' existing hint mechanism; adds no new configuration channel.
- The occupancy-derived implementation this interface is shaped for is not scheduled and
  is not owned by any change.
