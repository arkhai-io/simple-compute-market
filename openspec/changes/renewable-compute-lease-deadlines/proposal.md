# Compute lease delivery deadlines

## Why

A storefront can die between committing capacity and delivering it. Today the site
holds that capacity until the deal's agreed end even if no resource becomes usable.
A delivery deadline on the unactivated lease bounds this seller-side exposure
without teaching the site about payment or relying on the storefront to come back,
and the same number is the buyer's published term. The activation phase and
transition it is written against are `activate-compute-leases-at-the-site`'s, which lands first.

This is a recommended seller implementation safeguard, not a buyer guarantee or a
condition of the payment protocol. Once activated, a lease runs to its agreed end
unless end service ends it earlier. Buyer protection rests on authority records,
held money and kept signed bytes, not on a deadline inside the seller's site.

## What Changes

- Write the deadline at commit into the phase and due-instant columns
  `activate-compute-leases-at-the-site` adds: `awaiting_activation` only when the composition
  safeguard is enabled, with deadline max(commitment instant, lease start) plus the
  deal's accepted `delivery_deadline_seconds`, bounded by the pool's current policy and
  refused where the pool grants less. Existing leases keep their null fields and
  behavior. Activation, as that change defines it, replaces the deadline with the
  agreed end; there is no renewal operation here.
- Make expiry claim the state, deadline, phase and agreed end it read, before any
  teardown effect. Activation that wins the race invalidates a stale expiry claim;
  an elapsed deadline may still be activated until expiry claims it.
- Keep admission accounting against the agreed window, not the activation deadline.
  Truncation remains earlier-only and caps the deadline with the end.
- Let each provider declare its delivery-deadline default, overridden by a
  validated pool policy tag. Compute providers declare one; API-credit quota holds
  resolve none. Read the delivery deadline through the injected pool-authority port.
- Extend the signed `lease_ended`
  record with `activation_deadline_lapsed` and the deadline that caused the claim.
  This records intended lease end, not proven physical completion or authority to
  move money. Guarded release supplies the separate completion fact.
- Ship the explicit compute composition setting `activation_deadlines_enabled`
  false. Provider support/default validation stays active. The injected port resolves
  no effective delivery deadline while off; enabling affects only new commits and never
  backfills legacy leases. This change owns deployed enablement: every caller is
  already wired through the activation change's contract by `unify-compute-delivery-path`,
  which lands first.

Renewal and the site's `reclaim` / bounded `grace` / `continue` lapse policy are
**deferred**, with their design and revisit condition retained in D4. Reclaiming an active lease costs the buyer a working VM and the
honest storefront a self-penalty including the premature-stop penalty capped by
held earnings; hosted bond award is reserved.

## Capabilities

### Modified Capabilities

- `site-capacity`: commit deadline, expiry claim and admission rules.
- `resource-pool-management`: provider-declared delivery deadline and validation.
- `physical-provisioning`: watchdog enforcement and lease-end intent evidence.

### New Capabilities

None.

## Non-Goals

- Renewable active leases, renewal-lapse policy, lease extension or pooled deadlines.
- Any funded-through fact at the site; design records rejected billing alternatives.
- A buyer-facing provisioning SLA or a minimum-spend rule.
- A site-event-triggered refund. Under end service, a delivery that fails or never
  starts is classified by the foundation's single end-plus-optional-filing operation,
  including a pre-start command journaled now and executed at the accepted start;
  the buyer's own case is the backstop. The site event may supply evidence, but is
  neither the refund trigger contract nor a payment operation.
- The activation phase, transition and typed contract: `activate-compute-leases-at-the-site`.
- Wiring every compute delivery caller: `unify-compute-delivery-path` owns that work.

## Dependencies and Related Changes

- **Implementation gates:** `activate-compute-leases-at-the-site` supplies the phase and
  due-instant columns, the activation transition and the typed views this change
  writes into and conditions expiry on; `inject-site-pool-authority` supplies the session-scoped
  pool-facts port; this change adds one fact through it, not a site-to-pool-authority
  import. Reverify against its landed package paths before implementation.
- **Event integration gate:** `agreed-evidence-and-early-termination` supplies end
  service, the signed `lease_ended` record and evidence retention. This change owns
  the activation-lapse cause, not the base event or the seller's exceptional-end
  dispute filing. Ledger work may proceed independently; event integration and closeout
  wait for the foundation.
- `unify-compute-delivery-path` lands before this change and activates every compute
  commit caller once, including recovery and Alkahest, through the activation
  change's contract. Enablement is this change's: deploy storefronts first, then the
  site with the switch off, qualify every path in owned lanes, then enable. Its
  evidence proves activated leases survive the delivery deadline, undelivered leases
  expire, and API credits remain unchanged.
- `capacity-reservation-lifecycle-hardening` owns hold expiry indexing on the same
  table. Coordinate migration order; use a separate lease-deadline due query/index.
  Index coordination is not a behavior dependency. Reservation acknowledgement-gap
  qualification additionally consumes only its negotiation-keyed exact-request
  reservation-idempotency slice, not the whole hardening change; site-local
  activation implementation need not wait for that integration slice.
- `converge-ongoing-compute-leases` uses end service to end an active lease earlier;
  it does not renew this site's deadline.

## Impact and acceptance boundary

This is a design-stage change. Implementation covers the commit snapshot, the conditional
expiry claim, provider declarations, pool validation, watchdog behavior,
activation-lapse evidence and the switch's enablement. It is independently exercisable
through the site API without a storefront or payment authority. It does not claim
full compute delivery until `unify-compute-delivery-path` wires activation callers.
No hosted payments contract revision is required for the site safeguard itself.

The directory retains `renewable-compute-lease-deadlines` to avoid cross-change
reference churn; its active scope is the delivery deadline alone. Renewal is a
recorded deferred option, not an implementation task.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — capacity reservation and recovery workers.
- [x] Existing subsystem specifications — the three capabilities above.
- [ ] New subsystem specification.
- [ ] No permanent documentation change.

### Knowledge to promote

- D1–D2: the commit snapshot, the ceiling, agreed-window accounting and expiry claims
  to `openspec/specs/site-capacity/spec.md` and its architecture companion.
- D3: delivery deadline declaration/validation to
  `openspec/specs/resource-pool-management/spec.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- D5: watchdog, signed lease-end intent and separate proven-release facts to
  `openspec/specs/physical-provisioning/spec.md`.
- Seller-internal deadline versus payment/dispute authority boundaries to
  `docs/development/ARCHITECTURE.md`. D4's deferred design stays in this change,
  not in current-state normative requirements.
