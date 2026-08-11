## Why

A capacity reservation deliberately does not commit to a physical resource, or to a
pool within its site. That is the point: availability shifts while a negotiation
runs, and placement should be decided only when it must be. Scheduling is
correspondingly free — `CapacityLedgerService.iter_scheduling_candidates_in_session`
returns every enabled bucket at the site, and
`PhysicalSettlementScheduler._eligible_candidates_in_transaction` loads every enabled
pool and filters candidates on `resource_kind`, dimensions, and
`requirement.attributes` alone.

Nothing populates `requirement.attributes` on the current VM path.
`fulfillment_service.fulfill_vm_obligation` calls `schedule_resource` with
`capacity_reservation_id` and `market` only, so `PhysicalSettlementScheduler._requirement`
finds no `requirements`, and `deal_ref` carries `listing_id`, `escrow_uid`,
`negotiation_id`, and `reserved_by` — never the admitted claim. The scheduler reads
`deal_ref["requirements"]` and `deal_ref["terms"]` if present; no storefront writes
either.

The consequence is that the categorical half of an agreed deal is unenforced after
admission. A deal admitted against a claim requiring `region="California, US"` and
`gpu_model="H200"` can be scheduled onto a bucket in another pool at the same site
carrying a different region or a different GPU model, and no layer objects. Those are
exactly the fields a buyer filters discovery on and negotiates against, so the deal
can be fulfilled outside the terms it was sold under.

The quantitative half is already protected. `site-capacity`'s "Committed dimensions
remain authoritative through scheduling" requirement makes reserved dimensions binding
and lets scheduling narrow but never widen them. This change is that requirement's
categorical analogue: what makes the *shape* binding should also make the *kind*
binding, without re-pinning placement.

## What Changes

- Record the binding categorical requirements of an admitted claim at reserve time, so
  the reservation carries what the deal was sold under rather than only the dimensions
  it reserved.
- Re-apply those requirements as scheduling eligibility, so a candidate outside them is
  not selectable however much capacity it has.
- Report a candidate shortfall caused by the agreed requirements distinctly from a
  generic absence of capacity, so an operator can tell "nothing free" from "nothing
  free that matches what was sold."
- Leave placement freedom intact: a reservation still commits to a site and a shape and
  to nothing narrower, and rebinding across pools within a site remains available.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: an admitted reservation carries the categorical requirements it was
  admitted against, alongside the dimensions it already carries.
- `fulfillment`: scheduling eligibility includes the reservation's recorded categorical
  requirements, and an eligibility shortfall attributable to them is a distinct
  outcome.

## Non-Goals

- Do not constrain a reservation to a pool. Cross-pool rebinding within a site is the
  behavior this change protects, not the behavior it restricts.
- Do not change fairness or selection policy among candidates that are already
  eligible.
- Do not decide the canonical claim/requirement vocabulary;
  `structured-capacity-requirements` owns that, and this change uses whatever names are
  current when it is implemented.
- Do not add negotiation-time feasibility verification;
  `negotiation-capacity-feasibility-probe` owns that, and it addresses a different
  moment (before terms are agreed, rather than after).
- Do not extend this to attributes that are not commercially binding. Which attributes
  bind is the change's central open question, recorded in `design.md`.

## Impact

- **Affected code (indicative, to be confirmed at planning):**
  `kit/site/src/market_site/ledger.py` (what an admitted reservation records),
  `kit/fulfillment/src/market_fulfillment/scheduler.py` (`_requirement` and
  `_eligible_candidates_in_transaction`),
  `domains/vms/storefront/src/market_storefront/services/fulfillment_service.py` and
  `utils/sync_negotiation.py` (what reaches `deal_ref` at reserve time).
- **Affected data:** reservations admitted before this change carry no recorded
  requirements; scheduling MUST treat that absence as unconstrained rather than as an
  empty requirement set, or every in-flight reservation becomes unschedulable at
  upgrade.
- **Affected tests:** `kit/site` ledger suites, `kit/fulfillment` scheduling suites, VM
  storefront fulfillment integration suites.
- **Wire compatibility:** additive if the requirements travel on the existing
  `deal_ref` mapping the ledger already treats as opaque.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/site-capacity/spec.md` and
      `openspec/specs/fulfillment/spec.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- An admitted reservation's categorical requirements remain binding through scheduling,
  as its committed dimensions already do — `openspec/specs/site-capacity/spec.md`,
  alongside "Committed dimensions remain authoritative through scheduling".
- Scheduling may move a reservation between pools at one site but not outside the
  requirements it was admitted against — `openspec/specs/fulfillment/spec.md`.

## Dependencies and Related Changes

- `structured-capacity-requirements` owns the requirement vocabulary this change
  applies. It does not block design discussion, but implementing before that vocabulary
  settles risks encoding a shape that is about to be renamed.
- `pool-declared-offering-modes` constrains which *modes* a pool may deliver, checked at
  reservation, scheduling, and provisioning. Adjacent and complementary: that change
  governs what a pool can do, this one governs what a deal was sold as. Neither
  subsumes the other.
- `capacity-shape-envelope` decides which shapes a seller will consider before a deal
  exists. This change enforces the one that was agreed after it does.
- `fix-vm-fulfillment-capacity-boundary` established the quantitative half
  ("Committed dimensions remain authoritative through scheduling"). This change is the
  categorical analogue and should reuse its precedence language rather than invent new
  wording.
- No current end-to-end scenario fails because of this gap, which is why it is recorded
  rather than implemented now: every scenario's pool holds resources with identical
  categorical attributes, so no cross-pool reassignment can currently violate a deal.
