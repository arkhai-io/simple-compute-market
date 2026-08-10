## Why

A storefront never asks the site authority whether a shape can actually be served until
it places a hold at terms acceptance. Everything before that point runs against the
advisory projection, and the seller's only shape check
(`has_matching_inventory_guard`) compares `region` and `gpu_model` by equality.

The consequence is that a negotiation can run to completion, price a shape, agree
terms, and only then discover the site has nothing to give — the failure surfaces after
both parties have committed, which is the worst point to discover it.

`kit/site` already has the primitive: `probe()` runs the same matching logic as
`reserve()` and consumes nothing. `SiteCapacityClient.probe` and the aggregate client
expose it, and `vm_job_spec_service` already calls it in the fulfillment path. Nothing
calls it during negotiation.

This change is a shared prerequisite. Multidimensional shape negotiation needs it to
distinguish a shape the seller will not sell from one the site cannot currently serve,
and the parked capacity-economics thread needs it to let a buyer learn feasibility
before any hold — and therefore any charge — exists.

## What Changes

- Check a requested capacity shape against the site authority during negotiation,
  before the seller commits to terms, using the existing non-consuming probe.
- Report an unservable shape as a distinct outcome from an unacceptable one. A shape the
  seller will not sell and a shape the site cannot currently supply are different
  answers and lead to different counter-offers: change the ask, or retry later.
- Keep the check non-consuming. It reserves nothing, holds nothing, and creates no
  state, so it cannot be used to exclude other buyers and needs no protection against
  being used that way.
- Treat the result as a point-in-time answer with no guarantee. Two negotiations may
  both be told a shape is servable and one may lose the race at reservation — the same
  guarantee the advisory projection already offers, made explicit rather than implied.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `negotiation-protocol`: a requested capacity shape is verified against the
  authoritative site before terms are agreed, with unservable reported distinctly from
  unacceptable, and the verification consuming no capacity.

## Non-Goals

- Do not move the capacity hold earlier than terms acceptance. Holding at inquiry
  requires the parked capacity-economics work; this change deliberately delivers the
  early-failure benefit without it.
- Do not decide whether a shape is one the seller will consider —
  `capacity-shape-envelope` owns admissibility, and it is evaluated before this check
  so an inadmissible shape never causes a site round trip.
- Do not price the shape. `capacity-shape-pricing` owns that.
- Do not add the protocol field carrying a shape change between rounds —
  `negotiation-driven-capacity-resize` owns it. This change verifies whatever shape the
  round already carries, which today is the listing's own.
- Do not eliminate the race between concurrent negotiations. Accepted explicitly.
- Do not change `probe()` itself, its matching semantics, or the aggregate client's
  site selection.

## Impact

- Affected code: `domains/vms/storefront/src/market_storefront/utils/sync_negotiation.py`
  (the negotiation path), `domains/vms/negotiation/policies.py` (outcome vocabulary
  alongside the existing guard), and the storefront's capacity client usage.
- Affected tests: negotiation unit suites, and an e2e path proving an unservable shape
  fails during negotiation rather than at settlement.
- Performance: adds one site round trip per checked round. `kit/site`'s ledger
  serializes `probe` behind the same process-wide lock as `reserve`, so this is not
  free — see `design.md`.
- Not affected: reservation admission, hold lifecycle, settlement, fulfillment.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the "Discovery and negotiation" section, on
      when the authoritative site is consulted.
- [x] Existing subsystem specification — `openspec/specs/negotiation-protocol/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- A requested shape is verified against the authoritative site before terms are agreed,
  non-consuming, with unservable distinct from unacceptable —
  `openspec/specs/negotiation-protocol/spec.md`.
- That the verification is advisory and does not exclude concurrent buyers — same
  requirement, as a scenario.

## Dependencies and Related Changes

- Shared prerequisite for `capacity-shape-pricing` and
  `negotiation-driven-capacity-resize`, and for the parked capacity-economics thread.
  It does not belong exclusively to any roadmap goal.
- Complements `capacity-shape-envelope`: admissibility first, from declared policy and
  without a round trip; then this check, authoritative and remote.
- Relies on `kit/site`'s existing `probe()` and `SiteCapacityClient.probe`; changes
  neither.
