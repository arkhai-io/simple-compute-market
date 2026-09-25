<!-- Re-grounded 2026-09-25. The negotiation lifecycle now lives in
`kit/negotiation-runtime`; the round-0 guard is `_validate_vm_opening`;
`sync_negotiation.py` and `_reject_unsupported_resource_shape_request` are gone;
the shipped default places no pre-settlement hold, so `resize_reservation`'s first
caller is `negotiation-time-capacity-hold` rather than this change. Section 2 is
now planned and owns the multiplier reinterpretation moved from
`capacity-shape-pricing`. Older text below is history; "Re-grounding" in
`design.md` states what is current. -->

## Why

`docs/development/ARCHITECTURE.md`'s "Capacity reservation" section (added
2026-07-29) states the intended negotiation model: buyer and seller
negotiate pooled capacity, not a pinned physical resource, and a durable
shape change is expressed by resizing the reservation for that
negotiation (`CapacityLedgerService.resize_reservation`), never by
mutating an existing reservation or committed settlement assignment in
place. `resize_reservation` is implemented (`kit/site`) but has no caller
anywhere in the repository. This change wires it into the VM negotiation
path.

External review of `fix-vm-fulfillment-capacity-boundary` (see that
change's `design.md`, "Discuss phase: scheduled dimensions can diverge
from committed reservation dimensions") surfaced this gap while
investigating a different, narrower question (whether a scheduling
narrower than a reservation is correctly authoritative). Resolving that
question required the repository owner to supply the negotiation-model
context now captured in `ARCHITECTURE.md`; this change is the follow-on
work that context implies.

## Current state (verified by inspection, 2026-07-29)

- Round 0 of a negotiation (`NegotiateNewRequest`) already carries a real,
  validated `provision_terms.compute_resource` shape from the buyer.
- Every round after that (`NegotiateContinueRequest`, `AdvanceRequest`,
  shared cross-domain in `core_storefront/models/negotiation_models.py`)
  carries only `action` and `proposal` (price/escrow terms). There is no
  field for a shape change on any round after the first.
- The capacity hold placed at negotiation acceptance
  (`sync_negotiation.py`'s `_place_capacity_hold`) always builds its claim
  from `our_order_dict` -- the seller's own listing-derived order, fixed
  at negotiation setup -- never from anything a buyer counter-offered.
- Pool-level VM size defaults (`default_vm_ram`, `default_vm_vcpus`,
  `default_vm_disk_size` -- `AnsiblePoolConfig`) are real and persisted
  provisioning-service-side but have no HTTP/projection exposure to the
  storefront at all.

## What This Change Covers (accepted so far)

- **Section 0 (implemented, 2026-07-29):** `start_sync_negotiation` now
  loudly rejects a round-0 request naming a VM shape that disagrees with
  the listing's own shape (`OfferUnfulfillableError`,
  `resource_shape_not_negotiable`), rather than silently ignoring it in
  favor of the listing's fixed shape. Round-0 shape negotiation itself
  remains out of scope (see Non-Goals) -- this only prevents a buyer from
  believing it negotiated a different deal than what actually gets built.
- **Section 1 (implemented 2026-07-29, corrected same day, then fully
  reverted same day, repository-owner direction):** a
  `model_config = {"extra": "forbid"}` guard on `NegotiateContinueRequest`/
  `AdvanceRequest` was tried, found to be placed wrong (see `design.md`'s
  "Correction"), and then reverted outright rather than re-implemented in
  corrected form -- no `model_config` change belongs in `core` for this.
  `core_storefront` is unchanged from before this change opened. The
  correction's *reasoning* (a revised-terms field is a child of
  `proposal`, typed as the existing `ProvisionTerms` envelope, not new
  core vocabulary) is retained in `design.md` for Section 2 planning, and
  is exactly the shape Section 0 above actually implements -- correctly
  scoped to the VM domain, not core.
- **Section 2 (planned 2026-09-25):** a round after the first can carry a
  revised capacity shape, as a child of `proposal` typed as the existing
  `ProvisionTerms` envelope; the negotiated quantity becomes a rate
  multiplier over the listing's advertised minimum rate structure (moved
  here from `capacity-shape-pricing`, which delivers the structure and
  its evaluation); the seller's `evaluate_round` composition runs the
  admissibility check, the authoritative feasibility probe, the seller's
  commercial feasibility guard, and pricing against the requested shape;
  and the *agreed* shape, not the listing's, reaches the accepted
  artifacts, the settlement order, and therefore the capacity claim. The
  round-0 guard is then retired, since a differing shape is a proposal
  rather than a defect.
- **`resize_reservation` is not wired here.** Both storefronts ship
  `capacity.hold_ttl_seconds = 0`, so no reservation exists before the
  buyer's escrow settles, and the reservation created at settlement is
  built from the agreed shape directly. A resize is only meaningful when a
  hold was placed before the shape was final, which is exactly what
  `negotiation-time-capacity-hold` introduces; that change owns the first
  caller. (Until 2026-09-25 this change's title premise was that it would
  be the first caller.)

## Non-Goals (for now)

- Building the *pricing* of a shape. `capacity-shape-pricing` delivers the
  per-dimension rate structure, its evaluation, and the seller's
  commercial feasibility guard; this change consumes them. (Until
  2026-09-25 this non-goal excluded all shape-evaluating policy; the
  policy design has since been done there.) Any nested revised-terms
  content is limited to what that policy can price -- an unexamined field
  that passes content through unchecked risks a buyer claiming resources
  the seller never agreed to give away.
- Calling `resize_reservation`. Owned by `negotiation-time-capacity-hold`,
  the change that first places a hold before the shape is final.
- Deciding which shapes a seller will consider (`capacity-shape-envelope`)
  or whether the site can currently serve one
  (`negotiation-capacity-feasibility-probe`). This change calls both
  where they exist and degrades to "not checked" where a domain composes
  neither.
- Storefront-side consumption of pool VM size defaults at negotiation
  round 0. Depends on `pools-8-capacity-projection-and-listing-hints` task
  3.5 (projecting those defaults to the storefront) landing first; that
  task is this change's explicit dependency, not duplicated here.
- Rewriting the VM full-deal e2e suite. Tracked separately
  (`pools-7-storefront-fulfillment-cutover` task 10.14).

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` (already updated, 2026-07-29, ahead of this change's creation -- see "Capacity reservation" and "Discovery and negotiation"; the latter changes again when Section 2 lands, to say what a round negotiates)
- [x] Existing subsystem specification -- `openspec/specs/negotiation-protocol/spec.md` (the delta in `specs/`), and `openspec/specs/vm-storefront-fulfillment/spec.md` for the agreed shape reaching the claim.
- [ ] No further permanent documentation change for Section 1: the extra-field guard is defensive input validation, not new observable behavior, and does not itself warrant a new normative requirement.

### Knowledge to promote

- The negotiated quantity is a multiplier over the listing's minimum rate structure, expressed in basis points; a seller floor is expressed once -- `openspec/specs/negotiation-protocol/spec.md`.
- A round after the first may carry a revised capacity shape as a child of `proposal`, in the family-grouped form, and the agreed shape is what the claim reserves -- `openspec/specs/negotiation-protocol/spec.md`, `openspec/specs/vm-storefront-fulfillment/spec.md`.
- Section 1 shipped no lasting code; its reasoning survives only in this change's own `design.md`.

## Dependencies and Related Changes

- **Depends on `capacity-shape-pricing`** for the rate structure, its evaluation, and the seller's commercial feasibility guard. The multiplier reinterpretation moved from that change to this one on 2026-09-25 so that the additive work lands alone and the deployment boundary is here.
- Consumes `capacity-shape-envelope` and `negotiation-capacity-feasibility-probe` where a domain composes them; neither blocks this change.
- Builds on `fix-vm-fulfillment-capacity-boundary`: the committed reservation is authoritative through scheduling and dispatch, so once the claim is built from the agreed shape, fulfillment follows it with no further work here.
- Hands `resize_reservation`'s first call to `negotiation-time-capacity-hold`.
- Extends `kit/negotiation-runtime`'s `NegotiationDomainHooks`; every domain that composes the runtime is affected only where it opts into shape negotiation.
- Storefront-side consumption of pool VM size defaults at round 0 remains a non-goal and is not a dependency.
