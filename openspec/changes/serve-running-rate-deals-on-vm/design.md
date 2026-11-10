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

Rejected: convergence's replaceable funding timer with an authority read before
expiry, which protects the seller during a payments outage — a risk the MVP
accepts.

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

## Open Questions

- Whether the existing servicing journal already records physical release in a
  form the operator signal can read, or a migration is needed.
- Whether the spot notice's wait fits `TESTING.md`'s wording as written — an
  instant derived from the stage's own preempt request and the Agreement's notice
  — or should also move the clocks, so that no row waits on wall time.
