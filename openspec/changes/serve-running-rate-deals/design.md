# Design: serve-running-rate-deals

## Context

Goal 8's MVP is three changes: `drive-the-storefront-clock-in-lanes` and this one
in parallel, then `switch-on-hosted-per-period-vm`. Together they let a buyer take
an on-demand or spot deal paid per hour from a prepaid Arkhai payments balance,
with the shipped presets — the buyer's stop charging its started period, a
seller's preemption and the term end returning it, the dispute authority's stop
`chosen` — and Arkhai operators handling disputes by hand. It does not complete
Goal 8.

What exists that this change builds on:

- **The terms and the mandate.** Both compute domains publish recurring options
  through one per-clause step, gated by the composition's servicing declaration,
  a list of qualified treatments under `[Settlement].rate_servicing`
  (`kit/settlement-runtime/src/market_settlement_runtime/rate_servicing.py`). The
  payments kit derives the rate mandate exactly and the buyer re-derives it before
  approval.
- **One payments transaction adapter** serves once and rate parts, recording every
  operation through the caller's store before I/O; its rate `authorize` decides
  delivery phases on a verified snapshot (spot D4, D11).
- **The seller's notice and the buyer's end.** `deals preempt` sends one stop the
  authority holds pending; the buyer's canonical `end` stops at the authority and
  hints; the opt-in watchdog in `buy` sends that stop when the deal's SSH endpoint
  stops answering (spot D6, D6a).
- **The refusal.** End service refuses the commit of every deal whose seller
  projection is not once-only, with code `rate_servicing_unavailable`, before
  asking the adapter (`kit/deal-servicing/src/market_deal_servicing/end.py`,
  `_unserviceable`). The refused deal waits in repair; a buyer stop the authority
  recorded before the delivery deadline wins over seller non-delivery, through an
  observation barrier in admission (spot D12–D14; `deal-lifecycle`'s "Neutral
  delivery decisions delegate payment interpretation").
- **Delivery and ends.** The shared delivery path activates the lease at the site
  before it starts billing and before disclosure
  (`domains/compute/delivery/src/compute_delivery/path.py`). The payment watch
  records each part's verified final stop as the deal's selected end with the
  authority's cause (`kit/deal-servicing/src/market_deal_servicing/watch.py`).
- **The lanes.** Each compute lane already declares `charged` and `returned` and
  runs one recurring purchase that is approved, refused at commit and ended by the
  buyer's own stop (spot D16).

`converge-ongoing-compute-leases` designs the full servicing of running rate
deals. This change takes the slice an MVP deal needs, because the payment
authority, not the storefront, records every stop an MVP deal can end on.

## Decisions

### D1 — The refusal is removed, and a refused deal's next commit is keyed apart

End service's commit refusal goes, in both domains at once: it is kit code and
mechanism-neutral, and spot rejected a switch or an injected servicer that would
lift it for one composition (its D13). Bare metal is served by this change for
the same reason.

A deal refused before this change has its refusal journaled as a completed commit
authorization at its revision, and `EndSession.acknowledge` refuses to change a
completed intent (spot D14). The design session chooses how the next commit of
such a deal is keyed — a new revision for the commit after a coded refusal, or a
refusal journaled as not completed — so that a deal still within its delivery
deadline is delivered on its next drive. The observation barrier stays: a rate
deal's missed deadline is admitted only on a payment read at or after it.

Rejected: keeping the refusal for compositions that do not register rate
servicing, which is the injected-servicer seam spot rejected.

### D2 — The authority's recorded stops are the only end source for a running rate

Funding exhaustion, the term end, a spot notice taking effect, the buyer's stop
and the dispute authority's stop all reach the storefront as verified stop
records through the payment watch. The storefront keeps no funding timer. While
the payments service is unreachable the storefront keeps serving at its own risk
and tears down on the stop once the service answers; the stop's effective time,
not the time it was observed, bounds what the buyer paid for.

Not here: convergence's opt-in funding timer with an authority read before
expiry, which bounds a seller's loss during a payments outage.

### D3 — Stop causes map to lawful ends; `terms` is split by time

Each verified stop cause is classified as the lawful end it is. The payment
authority records funding exhaustion and the term end with the same cause,
`terms`, and nothing in the snapshot tells them apart; a `terms` stop whose
effective time is the Agreement's end is the term end, and one before it is
exhaustion. A seller-side failure on an on-demand deal is not classified
mechanically: operators stop billing through the dispute authority's `chosen`
entry and reverse what is held (`switch-on-hosted-per-period-vm`'s runbooks).

### D4 — The kit owns each deal's servicing step order

Each storefront has its own servicing cycle
(`domains/vms/storefront/src/market_storefront/deal_lifecycle.py`,
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py`).
This change moves the per-deal step order — authority read, physical work, then
authority work, then physical work again — and its error isolation into one
`kit/deal-servicing` helper both cycles call, registers the loop through
`kit/storefront`, and makes the VM cycle's cursor durable like bare metal's. Each
composition keeps its own recovery: site reports, delivery recovery and respondent
work.

Adopting the helper in bare metal fixes a defect outside this change's stated
scope. Bare metal's cycle already reads the payment authority in its own `try`,
but runs `drive_physical`, local reconciliation, site corrections and filing
dispatch in one, so a physical failure skips that deal's corrections and filings
for the cycle (`lifecycle.py`, the per-deal block of `cycle`).

One kit loop with whole-page passes, the eventual form, stays convergence's task
2.2.

### D5 — *Ended* means physically and financially finished

A deal in the seller's lifecycle list is *ended* only when it is physically
released, every payment part has a verified authority stop or end, and no
end-related case is open; otherwise it is *ending*, with its reason, such as "rate
still running at the authority". A deal with an open case stays *ending* until an
operator resolves it, which is what manual dispute handling needs. Today's list
calls a deal *ended* on physical release alone
(`kit/deal-servicing/src/market_deal_servicing/seller.py`); this changes that
meaning once, and convergence later refines the financial fact without changing
it.

### D6 — The loop's journal allowance

`settlement-servicing`'s "Payment settlement is retryable and idempotent" keeps
domain progress domain-owned, never a local ledger or a payment-servicing daemon.
This change's loop is the first to journal running rate stops, so it carries the
allowance that a neutral lifecycle loop may journal observations and
injected-adapter effects, never balances.

### D7 — Both compositions build their payments seller stage

Bare metal's settlement composition builds its payments seller stage over the
declaration in `__post_init__`; the VM composition builds none, and its root
builds the stage instead, which the VM storefront's tests repeat themselves (the
unowned row in the campaign index). Composing rate servicing in VM touches this,
so this change takes it: the VM composition builds its stage as bare metal's does,
and the root and the test helper stop building their own.

A storefront holding rate deals refuses to start without rate servicing
composed. Withdrawing a treatment from the declaration withdraws new offers and
acceptances only; deals already accepted keep being serviced, as the declaration's
own contract states.

### D8 — What the buyer is shown

The pre-approval display states that an on-demand option's premature-stop penalty
is collectible only from the seller's earnings still held: under `afterStop`
holds that is what the deal has earned so far, nothing in the first period
without a setup charge. After a funding stop the buyer is told that a top-up
cannot revive the deal, since the authority's `terms` stop is final, and that a
new deal is needed.

### D9 — Rate lane rows in both lanes

The lane evidence is convergence's matrix rows 0, 6, 7 and 9, each on its own
deal in both lanes against both doubles, under the shipped presets with a default
buyer:

- row 0, the on-demand baseline: start, the buyer's stop, teardown, *ended*;
- row 6, funds running out: the exhaustion stop ends delivery at its effective
  time, moving every perceived clock together through
  `drive-the-storefront-clock-in-lanes`' fixture;
- row 7, spot preemption with notice: the authority holds the pending stop and the
  deal ends when it takes effect, with the unstarted period returned;
- row 9, the maximum term: the term end with `returned`, told apart from
  exhaustion.

Beside them, the buyer watchdog's delivered-deal cases spot could not run while
every rate commit was refused: the real `buy` with the opt-in from `available`;
access lost with the storefront stopped yielding a single buyer stop; a killed
command reading `unmonitored` once its last probe goes stale; and the resumed run
reading `monitored`. The existing recurring purchase scenario changes from a
refused commit to a delivered deal.

The lane sellers configure a delivery deadline in their payments clause, which
publication carries when the pool supplies none
(`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`), so
the default buyer accepts every row's option without `--allow-unprotected-terms`
or any other waiver, as today's recurring purchase scenario already does
(`e2e-tests/tests/e2e/roles/helpers/recurring_purchase_stages.py`,
`recurring_settlement`). The clause deadline is enforced by the storefront,
a known divergence `renewable-compute-lease-deadlines` retires.

Notice and term-end waits are on instants the Agreement and the stage's own
request fix. Each run is labelled lane-double evidence, never live. Setup parts,
timer variants and convergence's other rows stay with convergence.

## Open Questions

- How a refused deal's next commit is keyed (D1).
- Whether the existing servicing journal already records physical release in a
  form the seller's list can read, or a migration is needed (D5).
- Whether bare metal's teardown on a stop needs more than end service driving its
  `drive_physical`, given that its term-end handling differs from VM's.
- Whether the spot notice's wait fits `TESTING.md`'s wording as written — an
  instant derived from the stage's own preempt request and the Agreement's notice
  — or should also move the clocks, so that no row waits on wall time.
