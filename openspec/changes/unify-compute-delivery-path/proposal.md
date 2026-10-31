# Unify the compute delivery path

## Why

VM and bare metal reach capacity commit, dispatch and credential disclosure through
separate implementations. VM derives its lease end from the Agreement but substitutes
an hour for a missing duration during recovery; bare metal commits from `now` and
can move an absolute seller bound. Neither path activates the site's lease after
provisioning. A per-period payment adapter needs an explicit seam before each
protected transition, with billing start a separately journaled effect after
activation, and a refusal there must end the resource through the lifecycle before
any credential is disclosed.

One compute-family path removes those divergences without making the market-neutral
fulfillment kit own commercial deal state. It builds on the lifecycle and end-service
boundary of `agreed-evidence-and-early-termination`: money moves at authorities, end
service orders delivery admission, and a seller that fails to deliver files
`exceptional_end` through the dispute adapter, whose self-penalty mediation rules.
This is the delivery portion of Goal 8 in
[`docs/development/ROADMAP.md`](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops).

## What Changes

- Both compute storefronts compose one path for capacity commit, dispatch, site
  activation, post-activation billing start, availability and access, keeping their
  domain preparation, result codecs and route surfaces.
- Every fresh or recovered commit uses `start_utc` and `start_utc + duration_seconds`
  from the Agreement. Missing timing is repair-required, not a one-hour default; an
  exhausted window takes the undelivered path.
- A future-start deal commits at settlement and waits for its accepted start before
  dispatch, activation, billing and access. The site's activation deadline is
  anchored at the later of the deal's commitment instant and lease start, plus the
  option's published `delivery_deadline_seconds`, which delivery supplies as the anchor
  and the site enforces from its pool.
- Every compute lease, whatever its payment structure or mechanism, is activated by
  reservation identity, adopting the current end (a verified earlier truncation
  included). The transition is `activate-compute-leases-at-the-site`'s; there is no periodic lease
  renewal here, and the awaiting-activation deadline is
  `renewable-compute-lease-deadlines`', which lands after this change.
- The path calls `authorize_delivery(deal, phase)` before `commit`, `dispatch`,
  `start` and `disclose`, with servicing-owned decisions and delivery-held
  references. The prepaid hook takes no financial action, and every deal still
  passes end service's admission. Rate servicing supplies the hook's
  payment-authority checks through its injected payment adapter, with a separately
  keyed `start_billing` effect after provisioning and activation. The foundation
  owns the neutral payment-adapter and evidence types and the servicing
  authorization port; end service alone journals the billing-start intent and key
  under delivery's stable key, and delivery keeps only its reference.
- The durable delivery checkpoints are `authorized`, `dispatched`, `activated`,
  `started`, `available` and `converged`, with stable effect identities and recovery
  at each acknowledgement gap. Availability does not depend on a buyer reading it.
- Delivery supplies the classified actor, cause and source, the accepted start and
  the fixed failure time to the foundation's single end-plus-optional-filing
  operation. The foundation classifies lawful buyer, payer-stop and ruling evidence
  against the non-delivery basis; a clock or a payee stop alone never erases
  non-delivery. A genuine never-delivered failure uses the foundation's fixed
  `min(start, failure observation)` basis after the start; before a future start it
  journals now and acts at the Agreement start, never future-dating a command. End
  service journals the filing; the seller half submits it through the dispute
  adapter, never its own payment stop or reverse; mediation alone rules the
  self-penalty. `end_delivery` carries no `at`, yields signed receipt evidence only
  and grants no billing authority: the buyer half stops at payments, journaling and
  retrying under one key if the authority is unreachable while billing continues
  until the stop lands; an optional `buyer_end` is human triage. The path implements
  no refund, stop, second filing journal or end-deal route.
- Credential reads enforce the delivery checkpoint and end service's recorded end,
  ordered with local end admission. They fetch access material live and recheck
  local eligibility before returning it, and never check a payment snapshot on a
  read. VM settle and status remain its access surface. Both authentication
  middlewares retain request identity but exclude credential-capable response
  bodies, so exact retries re-run admission. Physical teardown revokes credentials
  already disclosed.
- Adoption is additive: exact requests and resource identities are retained, old
  progress rows become read-only projections, and the cutover refuses old writers
  through a mandatory bridge release and purges retained credentials.

## Capabilities

### New Capabilities

- `compute-delivery`: compute-family storefront delivery orchestration — absolute
  windows, authorization phases, checkpoints, activation calls, the undelivered
  handoff and access admission — separate from provisioning's physical fulfillment
  aggregate and from generic lifecycle state.

### Modified Capabilities

- `marketplace-identity`: a narrow per-route exact-retry declaration with the proof,
  reservation, skew and refusal contract unchanged; credential-capable routes re-run
  without retained bodies. Unify archives before `redesign-authenticated-requests`,
  which generalizes the same declaration in a superset delta.
- `physical-provisioning`: verified bare-metal lifecycle adoption and read-only
  legacy progress, with malformed-evidence and source-revalidation refusal retained.
- `vm-storefront-fulfillment`: composes the family path; preserves delivery priority
  without executing unjournaled protected effects; allows the activation call after
  commit while lease ends stay with end service.

`fulfillment` keeps provider-neutral execution and no commercial delivery state.
The site's activation primitive is specified by
`activate-compute-leases-at-the-site`. The lifecycle final-request and exceptional-end
filing requirements belong to `agreed-evidence-and-early-termination`.

## Non-Goals

- Minimum spend, backdated stops or a local notice scheduler (rejected in the design).
- The site's deadline schema, lapse policy or active-lease renewal.
- The rate hook implementation and continuing rate servicing
  (`converge-ongoing-compute-leases`); payment event translation and rate arithmetic
  (`spot-deals-through-arkhai-payments`).
- Lifecycle routes, `end_delivery`, evidence-store retention, authority watches,
  final-request selection or the exceptional-end journal
  (`agreed-evidence-and-early-termination`).
- The broader settlement-start unification, evidence publication and verification
  extraction in `kit-owned-listing-and-fulfillment-lifecycles`.
- A new Alkahest dispute adapter, or a guarantee that an uncooperative seller refunds.

## Dependencies and Acceptance Boundary

- Depends on `agreed-evidence-and-early-termination` — its seller half, end-service
  admission, journaled dispute-filing interface, neutral delivery protocols,
  pre-start command policy and signed site-end report — and on
  `activate-compute-leases-at-the-site` — the activation phase, transition and typed contract —
  as whole changes. Buyer termination is part of the former. Neither waits on
  `inject-site-pool-authority`; the deadline change that does lands after this one.
- Sections 1–2 of the plan need only the negotiation-keyed reservation-idempotency
  slice of `capacity-reservation-lifecycle-hardening`. The HTTP lane drives in tasks
  3.3 and 4.3 need `add-arkhai-payments-lane-double`; library integration uses the
  shared clock-injected payments engine in kit-owned fixtures, which the HTTP double
  wraps, with no dependency on runnable tooling.
- `renewable-compute-lease-deadlines` ships its compute composition safeguard off and
  owns its enablement, after this change has wired every caller: compatible
  storefronts deploy first, then the site with the safeguard off, then every caller is
  qualified, then the default changes for new commits. Verified legacy null-phase views stay compatible; protected leases
  without working activation are repair-required.
- This change lands before `converge-ongoing-compute-leases`, which depends on it and
  owns the rate hook and the whole rate qualification matrix. The prepaid path and
  the hook interface do not wait for rate servicing; rate publication and
  materialization stay fail-closed until that servicing is composed.
- The archived `resolve-compute-family-findings` supplies the current VM recovery and
  admission baseline, whose exact-request recovery and release safeguards are
  preserved while those paths are rebound.
- `kit-owned-listing-and-fulfillment-lifecycles` consumes this narrow path and adds no
  other commit, dispatch, activation or access gate.

Acceptance: both domains and every compute mechanism use the shared protected
transitions; the Agreement window survives retries; every delivered lease activates
to its current site end before billing; genuine seller non-delivery durably reaches
the classified end-and-filing operation while lawful ends keep their attribution; no
locally ended deal discloses access, exact authenticated retries included; restart
recovers each effect without a replacement resource. Reserved VM and bare-metal
deals prove activation beyond the delivery deadline, expiry before activation proves
recovery plus the journaled exceptional-end filing, and API-credit delivery is
unchanged. Rate-path qualification is convergence's; no prepaid result proves it.

## Impact

A separate compute-family library distribution at `domains/compute/delivery`, with
its repository in the storefront database, depending downward on the neutral
lifecycle protocols and compute contracts and adding no commercial orchestration to
the physical provisioning base distribution. Both storefront composition roots
inject provisioning clients, domain preparation and result ports, and lifecycle
ports. VM payment and Alkahest recovery paths, bare-metal fulfillment paths, their
access routes and the lane deal stages change. API credits is a regression
consumer, not a caller.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — family-kit ownership, the fulfillment
  flow, the authority boundary and release.
- [x] Existing subsystem specifications — `vm-storefront-fulfillment`,
  `physical-provisioning`, `marketplace-identity`.
- [x] New subsystem specification — `compute-delivery` and its architecture companion.
- [ ] No permanent documentation change.

### Knowledge to promote

- Family delivery ownership, windows, phases, checkpoints, the activation caller and
  the access rule: `compute-delivery` spec and architecture companion; the capability
  index in `openspec/specs/README.md`.
- Bare-metal verified lifecycle adoption and retained-evidence refusal:
  `physical-provisioning` spec and architecture. The credential retry declaration:
  `marketplace-identity` spec and the repository's authentication architecture.
- VM convergence and activation obligations: `vm-storefront-fulfillment` spec and
  architecture companion.
- The cross-system flow with one end-service owner: `docs/development/ARCHITECTURE.md`,
  linking to the compute delivery and lifecycle contracts rather than duplicating
  their rules.
- Staged activation enablement, legacy compatibility and deployment order:
  `docs/development/DEPLOYMENT_AND_CONFIG.md` and the `compute-delivery` architecture.
- Additive cutover, downgrade refusal and credential-replay retirement:
  `vm-storefront-fulfillment` and `compute-delivery` specifications and companions.
- `fulfillment`'s architecture companion distinguishes its physical aggregate from the
  storefront delivery record; no new neutral fulfillment requirement.
