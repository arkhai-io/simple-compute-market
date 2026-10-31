# Unify the compute delivery path

## Why

VM and bare metal reach capacity commit, dispatch and credential disclosure through
separate implementations. VM derives its lease end from the Agreement but substitutes
an hour for a missing duration during recovery; bare metal commits from `now` and
can move an absolute seller bound. Neither path activates the site's lease after
provisioning. A per-period payment adapter also needs an explicit seam before each
protected transition, with billing start a separately journaled effect after activation. A refusal there
ends the resource through lifecycle before any credential disclosure.

One compute-family path removes those divergences without making the market-neutral
fulfillment kit own commercial deal state. It builds on the lifecycle and end-service
boundary of `agreed-evidence-and-early-termination`: money moves at authorities,
end service orders delivery admission, and the cooperative seller files exceptional_end
through the dispute adapter when it fails to deliver; mediation rules its self-penalty. This is the delivery portion of Goal 8 in
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
  reservation identity, adopting the current end (including verified earlier truncation). There is no periodic lease renewal here.
  The site owns the awaiting-activation deadline under
  `renewable-compute-lease-deadlines`; it is seller-side risk management, not a buyer
  guarantee.
- The shared path calls `authorize_delivery(deal, phase)` before `commit`,
  `dispatch`, `start` and `disclose`, with servicing-owned decisions and delivery-held references. The prepaid hook has no
  additional financial action; all deals still pass end service's admission check.
  Rate servicing supplies the hook's payment-authority checks through its injected
  payment adapter, with a separate keyed `start_billing` effect after provisioning and activation.
  The foundation owns neutral payment-adapter/evidence types and the servicing
  authorization port; end service alone journals billing-start intent/key under
  delivery's stable key, with delivery keeping only its reference.
- The durable delivery checkpoints are `authorized`, `dispatched`, `activated`,
  `started`, `available` and `converged`, with stable effect identities and recovery
  at each acknowledgement gap. Availability does not depend on a buyer reading it.
- Delivery supplies classified actor/cause/source, accepted start and fixed failure
  time to the foundation's single end-plus-optional-filing operation. Lawful
  buyer/payer-stop/ruling evidence is classified by foundation against the non-delivery
  basis; a clock or payee stop alone cannot erase non-delivery. A genuine
  never-delivered failure uses the foundation's fixed min(start, failure-observation)
  basis after start; before a future start it journals now and acts at Agreement
  start, never future-dating a command. End service journals the filing; the seller half submits it through the dispute
  adapter, never its own payment stop/reverse. Mediation alone rules the self-penalty.
  end_delivery carries no at, only signed receipt evidence, and grants no billing
  authority: the buyer half stops at payments, journaling/retrying under the same key
  if unreachable while billing continues until it lands. Optional buyer_end is human
  triage, not a mechanical ruling. The path implements no refund, stop, second filing
  journal or end-deal route.
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

- `marketplace-identity`: narrow per-route exact-retry declaration with unchanged
  proof/reservation/skew/refusal contract; credential-capable routes re-run without
  retained bodies. Archive unify before `redesign-authenticated-requests`, which
  generalizes the same declaration and must preserve it in a superset delta.
- `resource-pool-management`: post-qualification compute composition default;
  supersets renewable's off-by-default introduction, archiving renewable first.
- `physical-provisioning`: verified bare-metal lifecycle adoption and read-only
  legacy progress, retaining malformed-evidence and source-revalidation refusal.
- `vm-storefront-fulfillment`: compose the family path; preserve delivery priority
  without executing unjournaled protected effects; allow the activation call after
  commit while keeping lease ends with end service.

`fulfillment` continues to own provider-neutral execution, not commercial delivery
state. `physical-provisioning`'s activation primitive is specified by
`renewable-compute-lease-deadlines`. The lifecycle final-request and exceptional-end filing
requirements belong to `agreed-evidence-and-early-termination`, not a second delta here.

## Non-Goals

- Minimum spend, backdated stop or local notice scheduler; see design's rejected alternatives.
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
  end-service admission and journaled dispute-filing interface, and
  `renewable-compute-lease-deadlines`' activation half, including its signed site-end
  report. Buyer termination is folded into the former, not a separate dependency.
  The foundation also owns neutral delivery protocols and pre-start command policy;
  renewable transitively waits on `inject-site-pool-authority`.
- Sections 1–2 require only the negotiation-keyed reservation-idempotency slice of
  `capacity-reservation-lifecycle-hardening`. Sections 3.3/4.3/4.4 require
  `add-arkhai-payments-lane-double` for HTTP qualification; library integration uses
  the shared clock-injected payments engine in kit-owned fixtures (HTTP wraps it),
  with no dependency on runnable tooling.
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
pool allowance, expiry before activation proves recovery plus the journaled exceptional-end filing,
and API-credit delivery remains unchanged. Rate-path qualification is explicitly
blocked until its implementation dependencies are ready; no prepaid result proves it.

## Impact

Recommended home: a separate compute-family library distribution at
`domains/compute/delivery`, with its repository in the storefront database.
It depends downward on neutral lifecycle protocols and compute contracts, without
adding commercial orchestration to the physical provisioning base distribution.
Both storefront composition roots inject
provisioning clients, domain preparation/result ports and lifecycle ports. VM payment
and Alkahest recovery paths, bare-metal fulfillment paths, their access routes and
lane deal stages change. API credits is a regression consumer, not a caller.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — family-kit ownership, fulfillment flow,
  authority boundary and release.
- [x] Existing subsystem specifications — `vm-storefront-fulfillment`,
  `physical-provisioning`, `marketplace-identity`.
- [x] New subsystem specification — `compute-delivery` and its architecture companion.
- [ ] No permanent documentation change.

### Knowledge to promote

- Family delivery ownership, windows, phases, checkpoints, activation caller and
  access rule: `compute-delivery` spec and architecture companion; capability index
  in `openspec/specs/README.md`.
- Bare-metal verified lifecycle adoption and retained evidence refusal:
  `physical-provisioning` spec/architecture. Credential retry declaration:
  `marketplace-identity` spec and repository authentication architecture.
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
