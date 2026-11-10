## Why

With per-period terms offered (`offer-per-period-vm-terms`) and rate parts
derivable (`derive-rate-parts-in-the-payments-kit`), nothing yet runs a
per-period deal in the VM storefront. Its settlement composition binds only the
once-only adapter, the payment watch classifies no stop cause, the seller has no
command to preempt a spot deal, and the buyer's end does not stop a running rate.

Most of what a running deal needs already exists. The storefront's servicing
cycle recovers site reports, drives physical work, watches the payment and
dispute authorities and drives physical work again, each step isolated
(`domains/vms/storefront/src/market_storefront/deal_lifecycle.py`). The watch
turns a verified payment stop into a final request, and the end service
truncates at a future stop and tears down once it is due
(`kit/deal-servicing/src/market_deal_servicing/watch.py`, `end.py`). Billing
starts on delivery, after site activation and before disclosure
(`domains/compute/delivery/src/compute_delivery/path.py`). Funding exhaustion,
the term end and a notice's effective time are stops the payment authority
records, so the storefront keeps no funding timer of its own.

This change is one of Goal 8's MVP changes (see `offer-per-period-vm-terms`'s
design for the set). It composes the rate servicing in the VM storefront, adds
the seller's and buyer's commands, declares `charged` servicing in the lanes,
and qualifies the MVP's four lane rows against the payments and mediation doubles.

## What Changes

- **Composition.** The VM storefront composes the rate adapter and authorization
  hook beside the once-only adapter, and binds the rate policy into the delivery
  path's billing start.
- **Stop causes classified.** The payment watch maps each verified stop cause —
  the buyer's stop, the seller's entitled notice, funding exhaustion, the term end
  and the dispute authority's stop — to the lawful end it is.
- **What *ended* means.** A deal records its physical release, and the seller's
  lifecycle list calls it *ended* only when it is physically released, every
  payment part has a verified authority stop or end, and no end-related case is
  open; otherwise it is *ending* with its reason, such as "rate still running at
  the authority", which is what manual triage acts on.
- **One owner of the servicing step order.** The per-deal step order and its error
  isolation move into a `kit/deal-servicing` helper both storefronts' cycles call;
  the loop registers through `kit/storefront`; the VM cycle's cursor becomes
  durable. Bare metal adopting the helper fixes a defect in its cycle, where a
  physical failure skips that deal's payment and dispute reads.
- **The loop's journal allowance.** `settlement-servicing` states that a neutral
  lifecycle loop may journal observations and injected-adapter effects, never
  balances.
- **Spot preemption.** The seller's `deals preempt` submits a stop with notice
  against the accepted payee entitlement; the authority holds the pending stop
  and the storefront tears down when it takes effect. The VM admin route
  delegates notice; an on-demand deal refuses it and points to the operator
  procedure instead.
- **The buyer's rate end.** The buyer's end on a per-period deal stops the rate
  at the payment authority, retrying under the same key after a lost response,
  then tells the storefront.
- **Startup coherence.** A storefront holding per-period deals refuses to start
  without a rate adapter composed; withdrawing the per-period declaration stops
  new deals and keeps servicing existing ones.
- **Restart recovery.** A restarted storefront rebuilds every running deal's
  servicing from its database and the authorities' records.
- **Lane qualification, VM only, against both doubles.** The on-demand baseline
  (start, the buyer's stop, teardown); spot preemption with notice; the maximum
  term ending the deal; and funds running out, which needs the storefront's clock
  moved with the doubles'. Each run is labelled lane-double evidence, never live.

## Capabilities

### Modified Capabilities

- `market-composition`: rate servicing in the VM composition; startup coherence and withdrawal; loop registration through `kit/storefront`.
- `settlement-servicing`: the neutral lifecycle loop's journal allowance.
- `deal-lifecycle`: stop-cause classification for rate parts; the seller's notice; the buyer's rate end; the kit-owned per-deal step order; what *ended* means in the seller's list.
- `vm-storefront-fulfillment`: `deals preempt`, the admin route's notice, and the operator signal.
- `buyer-orchestration`: the buyer's rate end with same-key stop retry.
- `test-compatibility`: the four MVP lane rows and their evidence labels.

### New Capabilities

None.

## Non-Goals

- The opt-in seller funding timer, revision netting, and the financial completion fact's revision scoping, pending and unknown operations and manual acknowledgement (convergence tasks 2.1 and 2.3 beyond what this change takes).
- One kit loop with whole-page passes (convergence task 2.2).
- Self-penalty filings and mechanical rulings on rate parts (convergence 3.2), and execution of a ruling's `stop` or `penalty` effects in the mediation double.
- The stateless recovery runner and evidence export (convergence 3.4).
- Convergence's matrix rows 1–5, 8 and 10–13, and the extra windows and races of its task 4.2.
- Identity rotation overlap; the MVP's operating rule is to drain deals before the payments signing key retires (`switch-on-hosted-per-period-vm`).
- Bare metal.

## Impact

- Composition: the VM storefront gains a rate adapter and its configuration; the servicing declaration lists `charged` in the lanes and nothing elsewhere until `switch-on-hosted-per-period-vm`.
- CLI: a new seller verb, `deals preempt`; the buyer's end stops a running rate.
- No database migration is expected beyond the physical completion fact, if the existing journal does not already record it.

## Dependencies and Related Changes

- Depends on `offer-per-period-vm-terms` and `derive-rate-parts-in-the-payments-kit`. Its funds-exhausted row depends on `drive-the-storefront-clock-in-lanes`; its other rows do not.
- `switch-on-hosted-per-period-vm` follows it.
- Parts taken from `spot-deals-through-arkhai-payments` (task numbers in its `tasks.md`): 4.1–4.3 (notice, pending stop in lifecycle read, `deals preempt`), 4.4 (first-use fixtures, without opt-in variants), 4.5 (the buyer's rate end), 4.6 (the admin route, notice only), 5.1 (the lane's test-mode declaration).
- Parts taken from `converge-ongoing-compute-leases`: 1.3 (composition), 2.1 (the physical fact, and the simple financial fact *ended* reads), 2.2's per-deal step order as a helper (not the whole-page loop), 2.3 (stop-cause classification, without timers), 2.4 (one operator signal), 2.5 (stop to teardown, authority outage, restart), 3.1 (the rate delivery binding), 3.5 (startup coherence and withdrawal, without rotation), 4.1 (matrix rows 0, 6, 7 and 9, reduced to their MVP form, VM only), 4.3 (evidence labels), and the loop-journal allowance in its `settlement-servicing` delta.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `market-composition`, `deal-lifecycle`, `vm-storefront-fulfillment`, `buyer-orchestration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `deal-lifecycle`'s spec and architecture companion — authority-recorded stops as the only end source for a running rate.
- D2: `deal-lifecycle`'s spec — stop-cause classification.
- D3: `test-compatibility`'s spec and `docs/development/TESTING.md` — the MVP lane rows.
- D4: `deal-lifecycle`'s spec and architecture companion — the kit-owned per-deal step order and its isolation.
- D5: `deal-lifecycle`'s spec — what *ended* and *ending* mean in the seller's list.
- D6: `settlement-servicing`'s spec — the loop's journal allowance.
