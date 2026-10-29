# Compute lease activation deadlines

## Why

A storefront can die between committing capacity and delivering it. Today the site
holds that capacity until the deal's agreed end even if no resource becomes usable.
An activation deadline bounds this seller-side exposure without teaching the site
about payment or relying on the storefront to come back.

This is a recommended seller implementation safeguard, not a buyer guarantee or a
condition of the payment protocol. Once activated, a lease runs to its agreed end
unless end service ends it earlier. Buyer protection rests on authority records,
held money and kept signed bytes, not on a deadline inside the seller's site.

## What Changes

- Add a nullable lease deadline and activation phase beside `lease_end_utc`. Commit
  sets `awaiting_activation` only when the composition safeguard is enabled, with
  deadline max(commit time, lease start) plus the pool's provisioning allowance.
  Existing leases retain null fields and their current behavior.
- Add an idempotent activation transition. Every compute deal activates to its
  current agreed end, regardless of payment mechanism or billing shape. There is no renewal operation in this change.
- Make expiry claim the state, deadline, phase and agreed end it read, before any
  teardown effect. Activation that wins the race invalidates a stale expiry claim;
  an elapsed deadline may still be activated until expiry claims it.
- Keep admission accounting against the agreed window, not the activation deadline.
  Truncation remains earlier-only and caps the deadline with the end.
- Let each provider declare its provisioning allowance default, overridden by a
  validated pool policy tag. Compute providers declare one; API-credit quota holds
  resolve none. Read the allowance through the injected pool-authority port.
- Expose the deadline, phase and active instant, and extend the signed `lease_ended`
  record with `activation_deadline_lapsed` and the deadline that caused the claim.
  This records intended lease end, not proven physical completion or authority to
  move money. Guarded release supplies the separate completion fact.
- Ship the explicit compute composition setting `activation_deadlines_enabled`
  false. Provider support/default validation stays active. The injected port resolves
  no effective allowance while off; enabling affects only new commits and never
  backfills legacy leases. Unify owns deployed enablement after compatible callers.

Renewal and the site's `reclaim` / bounded `grace` / `continue` lapse policy are
**deferred**, with their design and revisit condition retained in D4. Reclaiming an active lease costs the buyer a working VM and the
honest storefront a self-penalty including the premature-stop penalty capped by
held earnings; hosted bond award is reserved.

## Capabilities

### Modified Capabilities

- `site-capacity`: commit deadline, activation, expiry claim and admission rules.
- `resource-pool-management`: provider-declared provisioning allowance and validation.
- `physical-provisioning`: watchdog enforcement and lease-end intent evidence.
- `compute-provisioning-contract`: typed activation and lease inspection.

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
- Wiring every compute delivery caller: `unify-compute-delivery-path` owns that work.

## Dependencies and Related Changes

- **Implementation gate:** `inject-site-pool-authority` supplies the session-scoped
  pool-facts port; this change adds one fact through it, not a site-to-pool-authority
  import. Reverify against its landed package paths before implementation.
- **Event integration gate:** `agreed-evidence-and-early-termination` supplies end
  service, the signed `lease_ended` record and evidence retention. This change owns
  the activation-lapse cause, not the base event or the seller's exceptional-end
  dispute filing. Ledger work may proceed independently; event integration and closeout
  wait for the foundation.
- `unify-compute-delivery-path` depends on this change and activates every compute
  commit caller once, including recovery and Alkahest. Campaign enablement waits
  for those callers. Deploy storefronts first, then the site off, qualify all paths,
  then enable. Legacy null-phase delivery tolerates absent activation support only
  with a verified legacy view; protected leases without activation require repair. Its complete-deal evidence proves activated leases survive
  the allowance, undelivered leases expire, and API credits remain unchanged.
- `capacity-reservation-lifecycle-hardening` owns hold expiry indexing on the same
  table. Coordinate migration order; use a separate lease-deadline due query/index.
  Index coordination is not a behavior dependency. Reservation acknowledgement-gap
  qualification additionally consumes only its negotiation-keyed exact-request
  reservation-idempotency slice, not the whole hardening change; site-local
  activation implementation need not wait for that integration slice.
- `converge-ongoing-compute-leases` uses end service to end an active lease earlier;
  it does not renew this site's deadline.

## Impact and acceptance boundary

This is a design-stage change. Implementation covers site persistence, conditional
transitions, typed site and compute clients, provider declarations, pool validation,
watchdog behavior and activation-lapse evidence. It is independently exercisable
through the site API without a storefront or payment authority. It does not claim
full compute delivery until `unify-compute-delivery-path` wires activation callers.
No hosted payments contract revision is required for the site safeguard itself.

The directory retains `renewable-compute-lease-deadlines` to avoid cross-change
reference churn; its active scope and title are activation-only. Renewal is a
recorded deferred option, not an implementation task.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — capacity reservation and recovery workers.
- [x] Existing subsystem specifications — the four capabilities above.
- [ ] New subsystem specification.
- [ ] No permanent documentation change.

### Knowledge to promote

- D1–D2: activation, null compatibility, agreed-window accounting and expiry claims
  to `openspec/specs/site-capacity/spec.md` and its architecture companion.
- D3: allowance declaration/validation to
  `openspec/specs/resource-pool-management/spec.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- D5: watchdog, signed lease-end intent and separate proven-release facts to
  `openspec/specs/physical-provisioning/spec.md`; activation/view contracts to
  `openspec/specs/compute-provisioning-contract/spec.md`.
- Seller-internal deadline versus payment/dispute authority boundaries to
  `docs/development/ARCHITECTURE.md`. D4's deferred design stays in this change,
  not in current-state normative requirements.
