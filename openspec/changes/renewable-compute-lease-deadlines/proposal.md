# Compute lease delivery deadlines

## Why

A storefront can die between committing capacity and delivering it. Today the site
holds that capacity until the deal's agreed end even if no resource becomes usable.
A delivery deadline on the unactivated lease bounds this seller-side exposure
without teaching the site about payment or relying on the storefront to come back,
and the same number is the buyer's published term: the Resource Pool's
`delivery_deadline_seconds`, which the storefront publishes and the site enforces.
The activation instant it is written against is `activate-compute-leases-at-the-site`'s
single `activated_at_utc`, which has landed.

Goal 8's MVP changes do not wait for this change. They ship a stopgap: the option's
deadline is the value the seller's payments clause configures
(`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`), the
storefront's servicing journal classifies a missed deadline as non-delivery
(`kit/deal-servicing/src/market_deal_servicing/journal.py`), `offer-per-period-vm-terms`
amends `deal-lifecycle` to describe that as current state, and
`switch-on-hosted-per-period-vm` gives operators a runbook for a lease abandoned before
delivery. The stopgap also lets a settlement mechanism's model own a lifecycle key,
which `deal-lifecycle` forbids. This change retires it: the pool's tag becomes the
published term again, the site enforces it, `deal-lifecycle` is re-amended to say so,
and the payments-clause parameter is removed.

This is a recommended seller implementation safeguard, not a buyer guarantee or a
condition of the payment protocol. Once activated, a lease runs to its agreed end
unless end service ends it earlier. Buyer protection rests on authority records,
held money and kept signed bytes, not on a deadline inside the seller's site.

## What Changes

- Add a nullable activation-deadline column to the shared site schema
  (`kit/site/src/market_site/migrations.py`), applied by both ledger-hosting services.
  On commit with the composition safeguard enabled, write max(commitment instant, lease
  start) plus the deal's accepted `delivery_deadline_seconds`, bounded by the pool's
  current policy and refused where the pool grants less. Whether a lease is activated
  stays derived from `activated_at_utc`: an unactivated lease is due at the earlier of
  its deadline and its agreed end, an activated one at its agreed end. Activation writes
  nothing new; there is no renewal operation here. Existing leases keep a null deadline
  and their behavior.
- Make expiry claim the state, agreed end, deadline and absence of activation it read,
  before any teardown effect. Activation that wins the race invalidates a stale expiry
  claim; an elapsed deadline may still be activated until expiry claims it.
- Keep admission accounting against the agreed window, not the activation deadline.
  Truncation remains earlier-only and never extends the agreed window.
- Let each provider declare its delivery-deadline default, overridden by a
  validated pool policy tag. Compute providers declare one; API-credit quota holds
  resolve none. The site reads the pool's current value at commit through the injected
  pool-authority port.
- Publish the pool's effective `delivery_deadline_seconds`, read from the site's pool
  projection, as the option's `lifecycle.delivery_deadline_seconds`, and carry the
  accepted value and the deal's commitment instant with the commit.
- Re-amend `deal-lifecycle`'s delivery-deadline requirements from the MVP's
  seller-configured, storefront-enforced wording to the pool's term enforced by the
  site, and retire the payments clause's `delivery_deadline_seconds` parameter.
- Extend the signed `lease_ended` record with `activation_deadline_lapsed` and the
  deadline that caused the claim. This records intended lease end, not proven physical
  completion or authority to move money. Guarded release supplies the separate
  completion fact.
- Ship the explicit compute composition setting `activation_deadlines_enabled`
  false. Provider support/default validation stays active. The injected port resolves
  no effective delivery deadline while off; enabling affects only new commits and never
  backfills legacy leases. This change owns deployed enablement: every caller is
  already wired through the activation contract by `unify-compute-delivery-path`.
- On closeout, retire the MVP's operator runbook for a lease abandoned before delivery,
  which the site's expiry replaces.

Renewal and the site's `reclaim` / bounded `grace` / `continue` lapse policy are
**deferred**, with their design and revisit condition retained in D4. Reclaiming an active lease costs the buyer a working VM and the
honest storefront a self-penalty including the premature-stop penalty capped by
held earnings; hosted bond award is reserved.

## Capabilities

### Modified Capabilities

- `site-capacity`: commit deadline, expiry claim and admission rules.
- `resource-pool-management`: provider-declared delivery deadline and validation.
- `physical-provisioning`: watchdog enforcement and lease-end intent evidence.
- `storefront-publication`: the pool's deadline published as the option's term.
- `deal-lifecycle`: the delivery deadline's source and enforcer restored to the pool and site.
- `settlement-configuration`: the payments clause's `delivery_deadline_seconds` parameter retired.

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
- The activation instant, transition and typed views: `activate-compute-leases-at-the-site`.
- Wiring every compute delivery caller: `unify-compute-delivery-path` did that work.

## Dependencies and Related Changes

- **Implementation gate:** `inject-site-pool-authority` supplies the session-scoped
  pool-facts port through which the site reads the pool's current deadline at commit;
  this change adds one fact through it, not a site-to-pool-authority import. Reverify
  against its landed package paths before implementation.
- **Landed:** `activate-compute-leases-at-the-site` (the `activated_at_utc` instant, the
  activation transition and both lease views), `unify-compute-delivery-path` (every
  commit and recovery caller, the commit through the storefront's capacity effects, the
  seller-failure classification of a refused commit and the activation-lapse hand-off)
  and `agreed-evidence-and-early-termination` (end service, the signed `lease_ended`
  record and evidence retention). This change owns the activation-lapse cause, not the
  base event or the seller's exceptional-end dispute filing.
- Goal 8's MVP changes (`offer-per-period-vm-terms`, `switch-on-hosted-per-period-vm`)
  ship the seller-configured stopgap this change retires; this change does not wait for
  them, but its `deal-lifecycle` re-amendment and runbook retirement build on their text.
- `activate-per-period-compute-servicing` depends on this change: the full product
  publishes the pool's deadline, which the site enforces.
- `capacity-reservation-lifecycle-hardening` owns hold expiry indexing on the same
  table. Coordinate migration order; use a separate lease-deadline due query/index.
  Index coordination is not a behavior dependency.
- `converge-ongoing-compute-leases` uses end service to end an active lease earlier;
  it does not renew this site's deadline.

## Impact and acceptance boundary

This is a design-stage change. Implementation covers the commit snapshot, the
conditional expiry claim, provider declarations, pool validation, the publication read,
watchdog behavior, activation-lapse evidence, the stopgap's retirement and the switch's
enablement. The site half is independently exercisable through the site API without a
storefront or payment authority. No hosted payments contract revision is required for
the site safeguard itself.

The directory retains `renewable-compute-lease-deadlines` to avoid cross-change
reference churn; its active scope is the delivery deadline alone. Renewal is a
recorded deferred option, not an implementation task.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — capacity reservation and recovery workers.
- [x] Existing subsystem specifications — the capabilities above.
- [ ] New subsystem specification.
- [ ] No permanent documentation change.

### Knowledge to promote

- D1–D2: the commit snapshot, the ceiling, agreed-window accounting and expiry claims
  to `openspec/specs/site-capacity/spec.md` and its architecture companion.
- D3: delivery deadline declaration/validation to
  `openspec/specs/resource-pool-management/spec.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`; the publication read to
  `openspec/specs/storefront-publication/spec.md`; the restored source and enforcer to
  `openspec/specs/deal-lifecycle/spec.md`; the retired clause parameter to
  `openspec/specs/settlement-configuration/spec.md`.
- D5: watchdog, signed lease-end intent and separate proven-release facts to
  `openspec/specs/physical-provisioning/spec.md`.
- The retired abandoned-lease runbook to `docs/operator-handbook.md`.
- Seller-internal deadline versus payment/dispute authority boundaries to
  `docs/development/ARCHITECTURE.md`. D4's deferred design stays in this change,
  not in current-state normative requirements.
