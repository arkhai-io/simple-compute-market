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
- **Section 2+ remains unplanned**, with its placement/vocabulary
  questions resolved but the field itself deliberately not added until
  seller negotiation policy exists to evaluate it (out of scope for this
  change) -- see "Non-Goals" and `design.md`'s "Section 2 resolutions".
  In
  particular: whether/when to add an explicit shape-change field to
  `NegotiateContinueRequest`/`AdvanceRequest`, whether seller/buyer
  negotiation policy is built to generate or evaluate such a field, and
  where in that flow `resize_reservation` gets called are all open.

## Non-Goals (for now)

- Building buyer or seller negotiation *policy* that generates, evaluates,
  or accepts a shape-changing counter-offer. Per repository-owner
  direction (2026-07-29): schema/guard work now, policy work later, as
  its own scoped decision. When it is in scope, any nested revised-terms
  content must be limited to what seller policy can actually reason
  about and price -- an unexamined field that passes content through
  unchecked risks a buyer claiming resources (disk, RAM, etc.) the seller
  never agreed to give away.
- Storefront-side consumption of pool VM size defaults at negotiation
  round 0. Depends on `pools-8-capacity-projection-and-listing-hints` task
  3.5 (projecting those defaults to the storefront) landing first; that
  task is this change's explicit dependency, not duplicated here.
- Rewriting the VM full-deal e2e suite. Tracked separately
  (`pools-7-storefront-fulfillment-cutover` task 10.14).

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` (already updated, 2026-07-29, ahead of this change's creation -- see "Capacity reservation" and "Discovery and negotiation")
- [ ] Existing subsystem specification -- pending Section 2+ scope decisions
- [ ] No further permanent documentation change for Section 1: the extra-field guard is defensive input validation, not new observable behavior, and does not itself warrant a new normative requirement.

### Knowledge to promote

- Section 1 shipped no lasting code; its reasoning survives only in this change's own `design.md` (Section 1's "Correction" and Section 2+'s notes), not in-code, since the code it would have annotated was reverted.
- Further promotion is deferred until Section 2+ scope is decided (see `design.md`).

## Dependencies and Related Changes

- Requires `pools-8-capacity-projection-and-listing-hints` task 3.5 before any storefront-side consumption of pool VM size defaults can be built.
- Builds on `fix-vm-fulfillment-capacity-boundary`'s corrected understanding of scheduled-vs-committed dimensions authority (that change's `design.md`, "Resolution" section) and the `ARCHITECTURE.md` sections it added.
- Relies on `kit/site`'s existing `resize_reservation` (implemented, unwired).
