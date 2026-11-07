# Unify the compute delivery path

## Why

The post-commitment lifecycle and the site's lease activation are implemented, but no
compute storefront uses the parts that order delivery: nothing calls
`authorize_delivery`, `begin_billing` or the site's `activate_lease`. The two domains
still reach commit, dispatch and access through different code. VM substitutes the
current time for a missing start and an hour for a missing duration; bare metal's
registered core hook builds its service without admission and commits from the
current time; both dispatch a deal that starts later as soon as it settles; VM stores
the tenant password and both storefronts replay recorded credential responses to an
exact retry after an end; and a VM reserve whose acknowledgement is lost is reserved
again, leaving a reservation that never expires.

One compute-family path removes those divergences without making the market-neutral
kits own compute delivery. This is the delivery portion of Goal 8 in
[`docs/development/ROADMAP.md`](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops).

## What Changes

- A compute-family library at `domains/compute/delivery` owns the delivery order —
  window, future-start wait, commit, dispatch, readiness, activation, billing start,
  availability, the end hand-off, recovery and the access check — and keeps no
  table. Each storefront implements two ports over its existing progress row and
  domain preparation, and the library exposes one operation, `drive`.
- Each storefront's progress table gains `activated_at_utc` by an additive startup
  migration; in-flight deals continue on their rows.
- Both domains enter through core's fulfillment hook: bare metal's settle and Alkahest
  continuation call `fulfill_domain`, and its hook builds the path from `ports` and
  `domain_input`. Core does not change.
- Every commit and recovery uses the Agreement's `start_utc` and `duration_seconds`;
  missing timing is repair-required. A deal that starts later commits at settlement
  and nothing physical, financial or disclosed happens before its start; each
  domain's existing worker wakes it.
- Every compute lease is activated through `CapacityEffects.activate_lease` after
  readiness and before billing start and availability; a refusal is read through
  `LeaseView`, and a site that cannot activate leaves the delivery repair-required.
- Billing start calls end service's `begin_billing` with the foundation's
  `DeliveryEvidence`; Alkahest deals authorize through a once-only adapter in
  `kit/alkahest`.
- An undelivered deal is handed to `record_end` with classified evidence; any commit
  refusal after a reservation is seller failure before dispatch, released through the
  no-dispatch path.
- VM reads credentials live, stops storing them and clears the stored copies. The
  credential-capable routes are declared, recorded without access material, and an
  exact retry of a credential read runs the guarded read again.
- `kit/site`'s `reserve` gains a placement key, `<negotiation_id>:<placement>`, under
  which an exact replay returns the recorded reservation and a changed replay is
  refused; both domains recover through it, and VM's hold uses it.

## Capabilities

### New Capabilities

- `compute-delivery`: the compute family's delivery order, ports and `drive`
  operation, Agreement windows and the future-start wait, activation, billing-start
  evidence, the end hand-off, the settle wait's terminal `ended` for a deal ended
  before delivery, and the access check.

### Modified Capabilities

- `vm-storefront-fulfillment`: delivery through the family path; the site's
  activation as a lease writer after commit; live credential reads with nothing
  stored; credential routes regenerated on exact retry.
- `physical-provisioning`: bare metal enters through core's fulfillment hook.
- `marketplace-identity`: a per-route exact-retry declaration for credential-capable
  routes, with the proof, reservation, skew and refusal contract unchanged.
- `site-capacity`: reserve replay keyed by the deal's placement.
- `deal-lifecycle`: the billing-start requirement names the evidence types as built.

## Non-Goals

- A provisioning lead time before the Agreement start (a separate change, if wanted).
- Extracting the storefront authentication middleware into a kit
  (`kit-owned-storefront-auth-and-persistence`) or redesigning the replay store
  (`redesign-authenticated-requests`).
- The site's delivery deadline, lapse policy, renewal and the safeguard switch
  (`renewable-compute-lease-deadlines`, `lapse-billing-with-the-site-lease`).
- The rate hook and continuing rate servicing (`converge-ongoing-compute-leases`);
  rate arithmetic (`spot-deals-through-arkhai-payments`).
- Reservation expiry indexing and retention (`capacity-reservation-lifecycle-hardening`).
- An Alkahest dispute adapter, refunds, a second end journal or a payment stop from
  the seller.

## Dependencies and Acceptance Boundary

- Builds on the archived `agreed-evidence-and-early-termination` and
  `activate-compute-leases-at-the-site`. No other change gates it.
- The lane runs of the filing and restart drives wait for
  `add-arkhai-payments-lane-double`; library integration uses the clock-injected
  payments engine in kit fixtures and the in-process mediation fake.
- Lands before `converge-ongoing-compute-leases` and `renewable-compute-lease-deadlines`.
- `kit-owned-listing-and-fulfillment-lifecycles` consumes `drive` and the access check.

Acceptance: both domains deliver through the one path and enter through core's hook;
the Agreement window survives every retry; nothing physical, financial or disclosed
precedes the Agreement start; every delivered lease is activated before billing start
and availability; a lost reserve, dispatch, activation or billing acknowledgement
recovers the same resource; an undelivered deal reaches `record_end` with its filing;
no locally ended deal discloses credentials, exact retries included; VM stores no
credential. Reserved VM and bare-metal deals are driven through activation, delayed
settlement and restart in the lanes. API-credit delivery is unchanged. Rate-path
qualification is convergence's.

## Impact

A new library distribution at `domains/compute/delivery`. Both storefront
composition roots implement and inject its ports; VM's payment and Alkahest recovery
paths, bare metal's settlement service and Alkahest continuation, both access routes
and both response middlewares change; each storefront gains one migration. `kit/site`
and its route gain the placement key; `kit/alkahest` gains a once-only adapter. The
lane deal stages change. API credits is a regression consumer.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — family kits, fulfillment, capacity
  reservation, results and identity.
- [x] Existing subsystem specifications — `vm-storefront-fulfillment`,
  `physical-provisioning`, `marketplace-identity`, `site-capacity`, `deal-lifecycle`.
- [x] New subsystem specification — `compute-delivery` and its architecture companion.
- [ ] No permanent documentation change.

### Knowledge to promote

- D1 family path, ports and `drive`: `compute-delivery` spec and architecture
  companion; `docs/development/ARCHITECTURE.md` "Family kits" and "Fulfillment";
  `openspec/specs/fulfillment/architecture.md` "Storefront pull composition"
  (boundary only); both tables of the capability index in `openspec/specs/README.md`.
- D2 additive upgrade: `docs/development/DEPLOYMENT_AND_CONFIG.md` "Migrations at
  startup"; `openspec/specs/vm-storefront-fulfillment/architecture.md` "Evidence and
  delivery ownership".
- D3 bare metal through core's hook: `physical-provisioning` spec;
  `openspec/specs/physical-provisioning/architecture.md` "Bare-metal storefront pull
  boundary".
- D4 Agreement window and future-start wait: `compute-delivery` spec and architecture
  companion.
- D5 live access and credential routes: `compute-delivery`,
  `vm-storefront-fulfillment` and `marketplace-identity` specs;
  `docs/development/ARCHITECTURE.md` "Fulfillment status and results" and
  "Marketplace identity".
- D6 placement key: `site-capacity` spec;
  `openspec/specs/site-capacity/architecture.md` "Reservation lifecycle";
  `docs/development/ARCHITECTURE.md` "Capacity reservation".
- D7 no compatibility for a site without activation: `compute-delivery` spec.
- D8 activation through `CapacityEffects` and refusals through `LeaseView`:
  `compute-delivery` spec; `docs/development/ARCHITECTURE.md` "Capacity reservation"
  (activation is now called by delivery).
- D9 billing-start evidence: `compute-delivery` spec; `deal-lifecycle` spec.
- D10 Alkahest once-only adapter: `openspec/specs/deal-lifecycle/architecture.md`
  "Package and counterpart boundaries".
- D11 end hand-off: `compute-delivery` spec, referencing `deal-lifecycle`.
- D12: no permanent destination — the deltas themselves are merged by the archive.
- D13: no permanent destination — index rows are planning state.
- D14: no permanent destination — the cadence is the plan's, not current behaviour.
- D15 lane qualification: `docs/development/TESTING.md` — the stage discipline's
  wait for an Agreement instant, the VM and bare-metal lane entries, and the
  real-provisioning lane's clock precondition.
- D16 implementation refinements: `openspec/specs/compute-delivery/architecture.md`
  "Ports and `drive`", "The delivery order" and "Domain compositions";
  `openspec/specs/site-capacity/architecture.md` "Reservation lifecycle";
  `openspec/specs/deal-lifecycle/architecture.md` "Package and counterpart
  boundaries"; `openspec/specs/vm-storefront-fulfillment/architecture.md` "Evidence
  and delivery ownership"; `openspec/specs/physical-provisioning/architecture.md`
  "Bare-metal storefront pull boundary". Its versions and classification items have
  no permanent destination: the first is release planning, and the second is unowned
  work in `openspec/changes/README.md`.
