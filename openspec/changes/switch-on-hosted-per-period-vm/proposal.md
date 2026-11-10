## Why

`serve-running-rate-deals-on-vm` proves on-demand and spot VM deals against the
lane doubles. No production composition declares per-period servicing, so no
real buyer can take one, and the MVP replaces the automated remedies Goal 8
designs with operator procedures that do not yet exist.

The external gate is the hosted payments service running the vendored contract
revision — at least the subset the MVP uses: rate approval, payee start, payer
and payee stops with notice under charged treatment, reserve-ahead refill and
exhaustion from a Stripe-funded balance, the term end, reversal while held, and
signed snapshots (`derive-rate-parts-in-the-payments-kit`, D2). The repository
shows hosted once-only payments accepting mandates that already carry per-part
authorities, holds and partial-period terms; it shows nothing about hosted rate
parts. Only the payments service's maintainers can say what the hosted target
runs.

This change is the last of Goal 8's MVP changes (see `offer-per-period-vm-terms`'s
design for the set). It takes the switch-on from
[`activate-per-period-compute-servicing`](../activate-per-period-compute-servicing/),
reduced to VM, charged treatment and operator-handled disputes, and adds the
operator runbooks. Turning the MVP on does not complete Goal 8.

## What Changes

- **Confirm the hosted revision.** Establish, with the payments service's
  maintainers, which revision the hosted test and production targets run and that
  they execute the MVP's subset; record the answer as the gate's evidence.
- **Prepare the hosted target** through existing setup tooling and run its
  readiness check before any deal scenario.
- **Live runs.** A complete on-demand deal, the buyer's stop, funds running out
  and spot preemption, against the hosted target, recorded as live evidence apart
  from lane-double evidence.
- **The production declaration.** The VM production composition declares
  `charged` servicing only after the hosted checks pass, with startup and
  withdrawal requalified under it, and a recorded rollback.
- **The dispute authority's policy.** Arkhai operators are the MVP's dispute
  authority; a published policy states key retention for the life of a deal,
  continuity, how cases are dismissed or ruled by hand, and the expected time to
  rule as advisory.
- **Operator runbooks**, in `docs/operator-handbook.md`:
  - stopping billing after a seller-side failure on an on-demand deal, through the
    dispute account's stop entry;
  - refunding through the payments service's reversal while money is held;
  - truncating a lease the storefront abandoned before delivery, and monitoring
    committed reservations still unactivated past their delivery deadline;
  - draining running deals before the payments signing key retires.

## Capabilities

### Modified Capabilities

- `settlement-configuration`: the deployment-qualified production declaration and its rollback.
- `test-compatibility`: hosted live evidence distinct from lane-double evidence.

### New Capabilities

None.

## Non-Goals

- Bare metal, `returned` or `prorated` treatment, and Goal 8's completion bar (an unconfigured buyer taking on-demand and spot live under the shipped presets, with a live preemption returning the unstarted remainder), which stays with `activate-per-period-compute-servicing`.
- The hosted mediation `delivery_end` revision and every mechanical ruling; filings that reach the hosted mediation service are triaged by hand.
- Convergence's full matrix in both domains.
- A site-enforced delivery deadline (`renewable-compute-lease-deadlines`); the runbook covers abandoned leases until it lands.
- Identity rotation of running deals (`spot-deals-through-arkhai-payments` 5.2–5.3); the runbook drains instead.

## Impact

- Deployment: the VM production profile declares per-period servicing once qualified; the declaration can be withdrawn without reinterpreting existing deals.
- Operations: Arkhai operators hold the dispute account's payments credentials and follow the runbooks.
- No wire or database change beyond those of the earlier MVP changes.

## Dependencies and Related Changes

- Depends on `serve-running-rate-deals-on-vm`.
- Blocked on the hosted payments deployment executing the MVP's subset; nothing in this repository can unblock that. The questions for the payments service's maintainers are in `design.md`.
- Parts taken from `activate-per-period-compute-servicing` (task numbers in its `tasks.md`): 1.1 (without the discovery and delivery-deadline gates), 1.2 (the hosted revision), 1.3 (the authority's commitments, as a published policy rather than mediation requalification), 2.3–2.4 (target preparation and readiness), 3.1–3.2 (live runs, reduced to the MVP rows), 3.3 (the production declaration), 3.4 (startup and withdrawal requalification).

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `settlement-configuration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `settlement-configuration`'s spec and `docs/development/DEPLOYMENT_AND_CONFIG.md` — the hosted-revision gate and the declaration's rollback.
- D2: `docs/operator-handbook.md` — the runbooks; `deal-lifecycle/architecture.md` — operators as the MVP's dispute authority.
- D3: `test-compatibility`'s spec — live evidence apart from lane-double evidence.
