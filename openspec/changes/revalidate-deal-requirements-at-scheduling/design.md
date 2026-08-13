# Design

## Context

Traced directly against the tree at `af3e0aa4` during an e2e debugging session
(2026-08-11). Re-verify before implementing; each of these is a specific line that may
move.

**A reservation records dimensions and no categorical requirements.**
`CapacityReservation` carries `dimensions`, `units`, `deal_ref`, `escrow_uid`,
`executor_kind`, `executor_ref`, lease window fields, and state. There is no column, and
no `deal_ref` convention in use, for the attributes the claim matched on.

**Admission does match on them.** `_find_candidate` splits the claim through
`_split_claim_requirement` into a resource-kind constraint plus exact-match attribute
requirements, and `resource_satisfies_requirement` compares
`resource.attributes.get(key) == value` for each. So at admission time the categorical
requirements are known and enforced — they are simply not retained.

**Scheduling has no pool constraint and no attribute input.**
`iter_scheduling_candidates_in_session` returns every enabled bucket of the requested
`resource_kind` at the site. `_eligible_candidates_in_transaction` loads every enabled
pool, keeps a candidate whose pool exists, and filters on
`resource_satisfies_requirement` with `requirement.attributes`. `_requirement` builds
those attributes from `request.requirements.get("attributes")`, falling back to nothing.

**The VM path supplies nothing.** `fulfill_vm_obligation` constructs
`FulfillmentScheduleRequest(capacity_reservation_id=..., market=...)` with no
`requirements`. `deal_ref` is written at reserve time by
`admin_controller.reserve_capacity` (`listing_id`, `escrow_uid`, `reserved_by`) and by
`sync_negotiation`'s hold placement (`listing_id`, `negotiation_id`). Neither carries
requirements or terms, both of which `_requirement` would read if present.

**The dimensions analogue is already normative.** `site-capacity`'s "Committed
dimensions remain authoritative through scheduling" requirement, added by
`fix-vm-fulfillment-capacity-boundary`, establishes that scheduling may narrow within a
reservation's bound and must report what it actually scheduled. The precedent for making
an admitted value binding through scheduling exists; only the categorical half is
missing.

## Goals / Non-Goals

**Goals:**

- Make the categorical requirements a deal was admitted against binding through
  scheduling.
- Preserve cross-pool rebinding within a site, which is the deferred-placement property
  the reservation model exists to provide.
- Distinguish "no capacity" from "no capacity matching what was sold".

**Non-Goals:**

- Choosing the requirement vocabulary (`structured-capacity-requirements`).
- Constraining which offering modes a pool may serve (`pool-declared-offering-modes`).
- Pre-agreement feasibility (`negotiation-capacity-feasibility-probe`).

## Open Questions

These are why the change is in discuss phase rather than planned.

- **Which attributes are commercially binding?** `region` and `gpu_model` are the two a
  buyer filters discovery on and the two `has_matching_inventory_guard` compares, so
  they are the obvious floor. `sla` is published and negotiated but is a seller
  assertion about a pool rather than a matchable resource fact, and today
  `PoolHintResolutionSettings.accept_pool_declared_sla` defaults `False` — so whether it
  binds depends on a trust decision already made elsewhere. A blanket "every attribute
  in the admitted claim binds" is the simplest rule and may be the right one; it also
  makes any attribute an operator adds to a claim silently load-bearing at scheduling
  time, which is how a coarse hint becomes an eligibility gate by accident.
- **Who owns the binding set — kit or the domain?** Kit cannot know that `region` is
  commercial and `vm_host` is telemetry. Either the domain declares which claim keys
  bind, or the rule is structural (every claim key except the ones the claim builder
  already treats as identity/pinning). The structural rule needs no domain hook and is
  therefore cheaper, but it inherits whatever the claim builder happens to include.
- **Where do the requirements live — the reservation row or the schedule request?**
  Recording them on the reservation makes them authoritative and survives a storefront
  that forgets to send them, which is the failure mode this change exists to close.
  Passing them per schedule request is additive and needs no ledger change, but a caller
  that omits them silently restores today's behavior. The `deal_ref` mapping is a third
  option — already opaque to the ledger, already read by `_requirement` under the
  `requirements` key — which requires no schema change while still being reservation-carried.
  It is the most likely answer and should be confirmed against
  `capacity-reservation-lifecycle-hardening`'s own `deal_ref` handling before being
  committed to.
- **What happens to reservations admitted before this change?** Absence of recorded
  requirements must read as unconstrained, not as an empty requirement set. Worth an
  explicit test rather than a comment, because the two are one `or {}` apart and the
  wrong one makes every in-flight reservation unschedulable at upgrade.
- **Does a `resize_reservation` supersede carry the requirements forward?** The resize
  path releases and re-admits under a new `capacity_reservation_id`. Whatever carries
  the requirements has to survive that, or a resized deal loses its categorical binding
  precisely when its shape changed.

## Why this is not implemented now

No end-to-end scenario fails on it. Every scenario's pool contains resources with
identical categorical attributes, so no cross-pool reassignment available today can
place a deal outside its sold terms. The gap is real and reachable in production — a
seller with two pools of differing hardware in one site — but it is not what is
currently breaking, and implementing it against a requirement vocabulary that
`structured-capacity-requirements` is about to rewrite would mean encoding the shape
twice.
