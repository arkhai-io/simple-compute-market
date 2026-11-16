## Why

`serve-running-rate-deals` proves on-demand and spot deals in both compute lanes
against the lane doubles. No production composition declares rate servicing, so no
real buyer can take one, and the MVP replaces the automated remedies Goal 8 designs
with operator procedures that do not yet exist.

The contract side of the hosted gate is clear. Every hosted payments deployment runs
the vendored contract revision (`kit/arkhai-payments/schema/SOURCE.md`) or a later,
additive one, and the payments service documents rate execution as implemented: rate
parts and their scheduler, partial-period billing for every treatment, scheduled
stops, and the dispute authority's `chosen` stop entry. What has not run against a
hosted target is narrower. The producer's own hosted run covered a payee stop under
`charged` and funds running out; it did not cover `returned`, a term end, the `chosen`
dispute stop or reversal, which the archived `spot-deals-through-arkhai-payments`
leaves to the switch-on. And every hosted option names the mediation authority — the
`chosen` stop entry is the mediation account's, and a storefront files `delivery_end`
with mediation when it ends delivery — while mediation is not yet deployed to the
hosted test target.

This change is the last of Goal 8's MVP changes, after `drive-the-storefront-clock-in-lanes`
and `serve-running-rate-deals`. It takes the switch-on from
[`activate-per-period-compute-servicing`](../activate-per-period-compute-servicing/),
reduced to VM and to operator-handled disputes, and adds the operator runbooks.
Turning the MVP on does not complete Goal 8.

## What Changes

- **Prepare the hosted target** through existing setup tooling and run its readiness
  check before any deal scenario.
- **Live runs**, VM only, recorded as live evidence apart from lane-double evidence:
  a complete on-demand deal; the buyer's stop, charged through its started period;
  funds running out; spot preemption with notice, returning the unstarted remainder;
  the term end, returning the unstarted remainder; the dispute authority's stop
  through the `chosen` entry; and reversal of held money while the part runs and
  after it stops. They are gated on mediation being deployed to the hosted test
  target; everything else in this change proceeds before it.
- **The production declaration.** The VM production composition declares
  `[charged, returned]` — the treatments the shipped presets use — only after the
  live runs pass, with startup and withdrawal requalified under it, and a recorded
  rollback. The production presets carry no setup charge.
- **A delivery deadline from the seller's payments clause, as a stopgap.** The VM
  production configuration sets `delivery_deadline_seconds` in the seller's payments
  clause, which publication uses when the pool's deadline port supplies none
  (`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`), so
  every option promises a deadline and the default buyer accepts without a waiver. The
  storefront enforces it, classifying a missed deadline as seller non-delivery; the
  site does not. `renewable-compute-lease-deadlines` retires it after the MVP, when the
  pool's tag supplies the deadline and the site enforces it.
- **The dispute authority's policy.** Arkhai operators staff the MVP's dispute
  authority and rule by hand. A published policy states how cases are dismissed or
  ruled, the expected time to rule as advisory, and continuity. On key retention it
  states the MVP's assumption — each environment's payments receipt key stays stable
  for a deal's life, and a key change is a drained cutover — rather than promising a
  retention the payments service has not committed to.
- **Operator runbooks**, in `docs/operator-handbook.md`:
  - a seller-side failure on an on-demand deal: stop now through the `chosen` entry
    with `returned`, then reverse what was earned since the failure, since a stop
    cannot be backdated;
  - an unentitled seller end: rule the premature-stop penalty, up to what is still
    held for the seller;
  - refunding through the payments service's reversal while money is held;
  - truncating a lease the storefront abandoned before delivery, and monitoring
    committed reservations still unactivated past their delivery deadline;
  - draining running deals before the payments receipt key changes.
- **Payout and funding, stated for sellers and buyers.** A seller is paid at the
  earliest at the part's stop, plus the dispute window, plus the payments service's
  fixed payout delay of 7 days. Approval is refused when the buyer's balance cannot
  cover the first reservation; a top-up or recharge landing before the funded
  boundary keeps the part running, and after it the stop is final and the buyer
  opens a new deal.

## Capabilities

### Modified Capabilities

- `settlement-configuration`: the deployment-qualified production declaration and its rollback.
- `test-compatibility`: hosted live evidence distinct from lane-double evidence.

### New Capabilities

None.

## Non-Goals

- Bare metal's switch-on, which waits on a qualified real host, and Goal 8's completion bar, which stay with `activate-per-period-compute-servicing`.
- `prorated` treatment, which no shipped preset offers.
- Setup charges in production: a setup charge's return on non-delivery is a mechanical `delivery_end` remedy, which waits on hosted mediation's rulings.
- Mechanical rulings and the hosted mediation `delivery_end` revision; filings that reach the hosted mediation service are triaged by hand.
- Convergence's full matrix.
- A site-enforced delivery deadline, the pool's tag and wiring the pool's deadline port (`renewable-compute-lease-deadlines`); the clause's storefront-enforced deadline stands in, and the runbook covers abandoned leases until it lands.
- Re-anchoring running deals across a receipt key change; the runbook drains instead, as the archived spot change decided.
- The payments service's own production readiness, which this change records as an external gate and does not perform.

## Impact

- Deployment: the VM production profile declares `[charged, returned]` once qualified, and sets the payments clause's `delivery_deadline_seconds`; the declaration can be withdrawn without reinterpreting existing deals.
- Operations: Arkhai operators hold the dispute authority's credentials and follow the runbooks.
- No wire or database change beyond those of the earlier MVP changes.

## Dependencies and Related Changes

- Depends on `serve-running-rate-deals`.
- The hosted live runs are gated on mediation deployed to the hosted test target, which the payments service's maintainers schedule; design and runbooks are not.
- Production is gated externally on the payments service going live: live Stripe Connect, WorkOS in production, a counsel review and EU VAT. Nothing in this repository can unblock it.
- Parts taken from `activate-per-period-compute-servicing` (task numbers in its `tasks.md`): 1.1 (without the discovery and delivery-deadline gates), 1.2 (the hosted revision and the treatments the shipped presets use), 1.3a's policy in the MVP's operator-ruled form, 2.3–2.4 (target preparation and readiness), 3.1, 3.1a and 3.2 (live runs, VM only), 3.3 (the VM production declaration), 3.4 (startup and withdrawal requalification under it).

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `settlement-configuration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `settlement-configuration`'s spec and `docs/development/DEPLOYMENT_AND_CONFIG.md` — the hosted gate and the declaration's rollback.
- D5: `docs/development/DEPLOYMENT_AND_CONFIG.md` — the production clause deadline, and that it is the storefront-enforced stopgap `renewable-compute-lease-deadlines` retires.
- D2: `docs/operator-handbook.md` — the runbooks and the payout timing; `deal-lifecycle/architecture.md` — operators as the MVP's dispute authority and the key-retention assumption.
- D3: `test-compatibility`'s spec — live evidence apart from lane-double evidence.
- D4: the buyer and seller documentation that already describes funding and payout.
