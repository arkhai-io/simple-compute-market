# Unify the compute delivery path

## Why

VM and bare metal reach capacity commit, dispatch and credential disclosure through
separate implementations. VM derives its lease end from the Agreement but substitutes
an hour for a missing duration during recovery; bare metal commits from `now` and
can move an absolute seller bound. Neither path activates the site's lease after
provisioning. A per-period payment adapter also needs an explicit seam before each
protected transition, rather than discovering after delivery that a start was refused.

One compute-family path removes those divergences without making the market-neutral
fulfillment kit own commercial deal state. It builds on the lifecycle and end-service
boundary of `agreed-evidence-and-early-termination`: money moves at authorities,
end service orders delivery admission, and the cooperative seller self-files when it
fails to deliver. This is the delivery portion of Goal 8 in
[`docs/development/ROADMAP.md`](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops).

## What Changes

- Both compute storefronts compose one path for capacity commit, dispatch, site
  activation, post-activation billing start, availability and access, retaining domain preparation,
  result codecs and route surfaces.
- Every fresh or recovered commit uses `start_utc` and
  `start_utc + duration_seconds` from the Agreement. Missing timing is repair-required,
  not a one-hour default; an exhausted window takes the undelivered path.
- Future-start deals commit at settlement but defer dispatch, activation, billing
  and access until the accepted start. The site deadline is anchored at the later
  of commit and lease start plus its allowance.
- Every compute lease, whatever its payment structure or mechanism, activates by
  reservation identity, adopting the current end (including verified earlier truncation). There is no billing horizon and no periodic lease renewal here.
  The site owns the awaiting-activation deadline under
  `renewable-compute-lease-deadlines`; it is seller-side risk management, not a buyer
  guarantee.
- The shared path calls `authorize_delivery(deal, phase)` before `commit`,
  `dispatch`, `start` and `disclose`, with durable decisions. The prepaid hook has no
  additional financial action; all deals still pass end service's admission check.
  Rate servicing supplies the hook's payment-authority checks through its injected
  payment adapter, with a separate keyed `start_billing` effect after provisioning and activation.
  Neutral protocol/evidence types belong to the foundation lifecycle kit.
- The durable delivery checkpoints are `authorized`, `dispatched`, `activated`,
  `started`, `available` and `converged`, with stable effect identities and recovery
  at each acknowledgement gap. Availability does not depend on a buyer reading it.
- Delivery supplies classified actor/cause/source, accepted start and fixed failure
  time to the foundation's single end-plus-optional-self-filing operation. Lawful
  buyer/terms/ruling ends do not automatically incur a seller penalty. A genuine
  never-delivered failure before a future start needs a valid immediate filing;
  the recommended lifecycle mapping is the earlier of accepted start and failure.
  End service journals the filing; the dispute authority applies any correction. The path does not implement its own refund,
  stop, correction journal or end-deal route.
- Credential reads enforce the delivery checkpoint and end service's recorded end,
  ordered with local end admission. They fetch access material live and recheck
  local eligibility before returning it, never checking payment snapshots on each
  read. VM settle/status remains its access surface. Both authentication middlewares
  retain request identity but exclude credential-capable response bodies, so exact
  retries re-run admission. Physical teardown revokes already disclosed credentials.
- Additive adoption retains exact requests/resource identities and makes old progress
  read-only projections; cutover refuses old writers and purges retained credentials.

## Capabilities

### New Capabilities

- `compute-delivery`: compute-family storefront delivery orchestration, absolute
  windows, authorization phases, checkpoints, activation calls, undelivered handoff
  and access admission. This is separate from provisioning's physical fulfillment
  aggregate and from generic lifecycle state.

### Modified Capabilities

- `vm-storefront-fulfillment`: compose the family path; preserve delivery priority
  without executing unjournaled protected effects; allow the activation call after
  commit while keeping lease ends with end service.

`fulfillment` continues to own provider-neutral execution, not commercial delivery
state. `physical-provisioning`'s activation primitive is specified by
`renewable-compute-lease-deadlines`. The lifecycle final-request and self-filing
requirements belong to `agreed-evidence-and-early-termination`, not a second delta here.

## Non-Goals

- A billing horizon, vouch, minimum spend, backdated stop or local notice scheduler.
- The site's deadline schema, lapse policy or active-lease renewal.
- The rate hook implementation and continuing rate servicing
  (`converge-ongoing-compute-leases`), or payment event translation and rate arithmetic
  (`spot-deals-through-arkhai-payments`).
- Lifecycle routes, `end_delivery`, evidence-store retention, authority watches,
  final-request selection or the exceptional-end journal
  (`agreed-evidence-and-early-termination`).
- The broader settlement-start unification, evidence publication and verification
  extraction in `kit-owned-listing-and-fulfillment-lifecycles`.
- A new Alkahest dispute adapter or a guarantee that an uncooperative seller refunds.

## Dependencies and Acceptance Boundary

- Implementation requires `agreed-evidence-and-early-termination`'s seller half,
  end-service admission and journaled self-filing interface, and
  `renewable-compute-lease-deadlines`' activation half, including its signed site-end
  report. Buyer termination is folded into the former, not a separate dependency.
  The foundation also owns neutral delivery protocols and pre-start filing policy;
  renewable transitively waits on `inject-site-pool-authority`.
- Sections 1–2 require only the negotiation-keyed reservation-idempotency slice of
  `capacity-reservation-lifecycle-hardening`. Sections 3.3/4.3/4.4 require
  `add-arkhai-payments-lane-double` for HTTP qualification; library integration uses
  in-process contract-vector fakes with no dependency on runnable tooling.
- Renewable ships its compute composition safeguard off. This change owns final
  enablement: deploy compatible storefronts first, then the site off, qualify every
  caller, then enable for new commits. Verified legacy null-phase views remain
  compatible; protected leases without working activation are repair-required.
- The prepaid path and hook interface can be implemented before rate servicing.
  Per-period composition and its qualification wait for
  `spot-deals-through-arkhai-payments` and `converge-ongoing-compute-leases`; publication
  and materialization remain gated until that servicing is composed.
- The archived `resolve-compute-family-findings` supplies the current VM
  recovery/admission baseline. Preserve its exact-request recovery and release
  safeguards while rebinding those paths.
- `kit-owned-listing-and-fulfillment-lifecycles` consumes this narrow shared path and
  must not introduce another commit, dispatch, activation or access gate.

Acceptance: both domains and every compute mechanism use the shared protected
transitions; the Agreement window survives retries; every delivered lease activates
to its current site end before billing; genuine seller non-delivery durably reaches
the classified end/filing operation, while lawful ends retain their attribution;
no locally ended deal discloses access, including exact authenticated retries;
restart recovers each effect without
replacement resources. Reserved VM and bare-metal deals prove activation beyond the
pool allowance, expiry before activation proves recovery plus the journaled filing,
and API-credit delivery remains unchanged. Rate-path qualification is explicitly
blocked until its implementation dependencies are ready; no prepaid result proves it.

## Impact

Recommended home: a separate compute-family library distribution at
`provisioning/compute/delivery`, with its repository in the storefront database.
It depends downward on neutral lifecycle protocols and compute contracts, without
adding commercial orchestration to the physical provisioning base distribution.
Both storefront composition roots inject
provisioning clients, domain preparation/result ports and lifecycle ports. VM payment
and Alkahest recovery paths, bare-metal fulfillment paths, their access routes and
lane deal stages change. API credits is a regression consumer, not a caller.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — family-kit ownership, fulfillment flow,
  authority boundary and release.
- [x] Existing subsystem specification — `vm-storefront-fulfillment`.
- [x] New subsystem specification — `compute-delivery` and its architecture companion.
- [ ] No permanent documentation change.

### Knowledge to promote

- Family delivery ownership, windows, phases, checkpoints, activation caller and
  access rule: `compute-delivery` spec and architecture companion; capability index
  in `openspec/specs/README.md`.
- VM convergence/activation obligations: `vm-storefront-fulfillment` spec and
  architecture companion.
- Cross-system flow and one end-service owner: `docs/development/ARCHITECTURE.md`,
  with links to the compute delivery and lifecycle contracts, not duplicated rules.
- Staged activation enablement, legacy compatibility and deployment order:
  `docs/development/DEPLOYMENT_AND_CONFIG.md` and `compute-delivery` architecture.
- Additive cutover/downgrade refusal and credential-replay retirement:
  `vm-storefront-fulfillment` and `compute-delivery` specifications/companions.
- Update `fulfillment`'s architecture companion to distinguish its physical aggregate
  from the storefront delivery record. No new neutral fulfillment requirement.
