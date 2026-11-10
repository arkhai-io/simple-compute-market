# Design: serve-running-rate-deals-on-vm

## Context

One of Goal 8's MVP changes; `offer-per-period-vm-terms`'s design states the set.
It follows `offer-per-period-vm-terms` and `derive-rate-parts-in-the-payments-kit`,
and its funds-exhausted row follows `drive-the-storefront-clock-in-lanes`.

`converge-ongoing-compute-leases` designs the full servicing of running rate
deals: two work queues, two completion facts, a funding timer that reads the
authority before expiry, durable filing and revision recovery, the on-demand
emergency penalty and identity-rotation overlap, qualified by a fourteen-row
matrix in both lanes. The MVP needs a small part of it because the servicing
cycle it would extend already runs for every deal, and because the payment
authority, not the storefront, records every stop an MVP deal can end on.

## Decisions

### D1 — The authority's recorded stops are the only end source for a running rate

Funding exhaustion, the term end, a spot notice taking effect, the buyer's stop
and the dispute authority's stop all reach the storefront as verified stop
records through the payment watch. The storefront keeps no funding timer. If the
payments service is unreachable, the storefront keeps serving at its own risk and
tears down on the stop once the service answers; the stop's effective time, not
the time it was observed, bounds what the buyer paid for.

Not in the MVP: convergence's funding timer with an authority read before expiry,
which bounds a seller's loss during a payments outage at the cost of a
self-penalty when it ends a deal a hidden top-up had funded.
`converge-ongoing-compute-leases` adds it as a seller opt-in; the MVP accepts the
outage risk.

### D2 — Stop causes map to lawful ends; nothing in the MVP files a case automatically

Each verified stop cause is classified as the lawful end it is. A seller-side
failure on an on-demand deal is not classified mechanically: the operator stops
billing through the dispute account and handles the case by hand
(`switch-on-hosted-per-period-vm`'s runbooks).

### D3 — Four lane rows, VM only

The MVP's lane evidence is the on-demand baseline, spot preemption with notice,
the maximum term, and funds running out, each on its own deal against both
doubles. Notice and term-end waits are on instants the Agreement and the stage's
own request fix; the funds-exhausted row moves every perceived clock together
through `drive-the-storefront-clock-in-lanes`'s fixture.

### D4 — The kit owns each deal's servicing step order

Today each storefront has its own servicing cycle
(`domains/vms/storefront/src/market_storefront/deal_lifecycle.py`,
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py`).
This change moves the per-deal step order — physical work, then authority work,
then physical work again — and its error isolation into one `kit/deal-servicing`
helper both cycles call, registers the loop through `kit/storefront` as the single
point, and makes the VM cycle's cursor durable like bare metal's. Each composition
keeps the recovery that is its own: site reports, delivery recovery and respondent
work.

Adopting the helper in bare metal fixes a defect outside this change's stated
scope: bare metal's cycle runs `drive_physical` and the authority work in one
`try`, so a physical failure skips that deal's payment and dispute reads for the
cycle (`lifecycle.py`, the per-deal block of `cycle`). Its fix is small and
understood, and is recorded here under "Defects found during a change"
(`openspec/README.md`).

One kit loop with whole-page passes, the eventual form, is
`converge-ongoing-compute-leases`' task 2.2.

### D5 — *Ended* means physically and financially finished

A deal in the seller's lifecycle list is *ended* only when it is physically
released, every payment part has a verified authority stop or end, and no
end-related case is open; otherwise it is *ending*, with its reason, such as "rate
still running at the authority". The MVP observes all three facts already: its
watch verifies stops, and the list reports open cases. A deal with an open case
stays *ending* until an operator resolves it, which is the default manual dispute
handling needs. Today's list calls a deal *ended* on physical release alone
(`kit/deal-servicing/src/market_deal_servicing/seller.py`); this changes that
meaning once, and `converge-ongoing-compute-leases` later refines the financial
fact without changing it.

### D6 — The loop's journal allowance

`settlement-servicing`'s "Payment settlement is retryable and idempotent" keeps
domain progress domain-owned, never a local ledger or a payment-servicing daemon.
This change's loop is the first to journal rate stops, so it carries the
allowance that a neutral lifecycle loop may journal observations and
injected-adapter effects, never balances.

## Open Questions

- Whether the existing servicing journal already records physical release in a
  form the operator signal can read, or a migration is needed.
- Whether the spot notice's wait fits `TESTING.md`'s wording as written — an
  instant derived from the stage's own preempt request and the Agreement's notice
  — or should also move the clocks, so that no row waits on wall time.
