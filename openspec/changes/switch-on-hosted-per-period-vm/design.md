# Design: switch-on-hosted-per-period-vm

## Context

The last of Goal 8's MVP changes. The set is `drive-the-storefront-clock-in-lanes`
and `serve-running-rate-deals` in parallel, then this change. It follows
`serve-running-rate-deals`, which services rate deals in both compute domains and
qualifies them in both lanes against the doubles.

What this change builds on, from the archived `negotiate-open-ended-compute-terms`
and `spot-deals-through-arkhai-payments`:

- The shipped presets charge the buyer's stop through its started period
  (`charged`), return the unstarted remainder on a seller's preemption and at the
  term end (`returned`), and give the dispute authority a `chosen` stop entry
  (`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`). An
  on-demand option carries a default premature-stop penalty of 24 periods' price.
- A composition's servicing declaration lists the treatments it has qualified, under
  `[Settlement].rate_servicing`
  (`kit/settlement-runtime/src/market_settlement_runtime/rate_servicing.py`), and
  publication, acceptance and materialization refuse any treatment it does not list.
- The default buyer refuses `charged` on a seller's preemption and at the term end
  (`kit/settlement-runtime/src/market_settlement_runtime/buyer_terms.py`) and refuses
  an option that promises no delivery deadline. The pool's deadline port is wired in
  no composition, so an option promises a deadline only from its payments clause (D5).

`activate-per-period-compute-servicing` designs the full switch-on: bare metal, the
consolidated matrix run hosted, the mediation `delivery_end` revision and its
mechanical rulings, and Goal 8's completion bar. The MVP switches on VM with
operator-handled disputes; the rest stays with that change.

What the payments service documents, which this change relies on and qualifies
hosted rather than restating as its own behaviour:

- Every hosted deployment runs the vendored contract revision or a later one that
  only adds webhook types.
- Rate execution is implemented: rate parts, the reservation scheduler, partial-period
  billing for `charged`, `returned`, `prorated` and `chosen`, and scheduled stops.
- Running out of funds is an ordinary stop with cause `terms` in the signed snapshot;
  a term end carries the same cause, and nothing yet distinguishes them.
  `serve-running-rate-deals` tells them apart by comparing the stop time with the
  Agreement's end.
- Every mediation stop entry is the mediation account's, with zero notice and
  `chosen` treatment.
- Any account in a part's reverse authorities can reverse still-held money while the
  part runs or after it stops. A stop cannot be backdated. A stop's `settled` figures
  are not restated after a later reversal.
- Approval answers `409 insufficient_funds` when the payer's balance cannot cover the
  first reservation.
- Card auto-recharge is implemented. A top-up landing before the funded boundary
  keeps the part running; after it the `terms` stop is final, since a pending stop
  cannot be withdrawn.
- No key-retention commitment is published, and there is no way yet to announce a
  receipt key rotation. Each environment has its own key, which has not been rotated.
- A seller is paid out 7 days after release. Sellers onboard to a Stripe Connect
  Express account, and withdrawals need payouts and transfers enabled; buyers need an
  account and a card top-up.
- Production is opened by the payments service's own go-live work: live Stripe
  Connect with a small real top-up, deal, payout and reconciliation run, WorkOS checks
  against production, a counsel review before taking real money, and EU VAT.
- Mediation is not yet deployed to the hosted test target.

## Decisions

### D1 — The declaration follows hosted evidence, and is withdrawn without reinterpreting deals

The VM production composition declares `[charged, returned]` only after the live runs
pass: the treatments the shipped presets use, so a buyer who changed no setting can
take on-demand and spot. `activate-per-period-compute-servicing` extends the list if a
later preset offers `prorated`, and declares bare metal's. Withdrawing the declaration
stops new rate deals and leaves existing deals on the authorities and terms they were
made under; servicing continues as `serve-running-rate-deals` defines.

The live runs cover each treatment the declaration names and each operator action the
runbooks use: the buyer's stop under `charged`; a seller's preemption and the term end
under `returned`; funds running out; the dispute authority's stop through the `chosen`
entry; and reversal while running and after a stop. They run only once mediation is
deployed to the hosted test target, since every hosted option names the mediation
authority and its account holds the `chosen` entry. Production waits further on the
payments service's go-live, recorded here as an external gate.

**Contingency, not a plan.** If the hosted `returned` runs fail and the payments
service cannot correct them in time, the VM production composition may declare
`[charged]` alone, with sellers configuring charged presets and buyers passing
`--allow-charged-preemption` and `--allow-charged-term-end`. The gap is then recorded
in Goal 8 of `docs/development/ROADMAP.md` with the hosted evidence, including that a
charged term end bills past the agreed maximum, since billing starts at activation and
the term end falls within a period.

Rejected: declaring from the documented behaviour alone, since the producer's hosted
run did not cover `returned`, a term end, the `chosen` stop or reversal; and declaring
`[charged]` by design, which configures the product into a worse state than the code
supports and requires two buyer waivers on every deal.

### D2 — Operators are the MVP's dispute authority

Arkhai operators staff the mediation authority the options name. They rule by hand,
acting through its stop entry and the payments service's reversal, following runbooks
in the operator handbook. Mechanical rulings stay with
`activate-per-period-compute-servicing`.

The runbooks follow the payments service's semantics. A seller-side failure on an
on-demand deal is remedied by a stop now through the `chosen` entry with `returned`,
then a reversal of what was earned since the failure; "stop at a past time" is never
available. An unentitled seller end is ruled with the premature-stop penalty, up to
what is still held for the seller: under `afterStop` holds that is everything the deal
has earned and not yet been paid out, and in its first period, with no setup charge,
nothing. The buyer's display states the same bound (`serve-running-rate-deals`).

A published policy states case dismissal and hand rulings, continuity, and the
expected time to rule as advisory; no response bound is promised. On key retention it
states the assumption the MVP rests on — each environment's payments receipt key
stays stable for the life of a deal — and that a key change is a drained cutover, as
the archived spot change decided: the operator drains or refunds every running deal
first, following the runbook. It does not promise retention the payments service has
not committed to.

### D3 — Live evidence is recorded apart from lane-double evidence

Only runs against the hosted target are live evidence; lane runs remain lane-double
evidence.

### D4 — What sellers and buyers are told

The seller documentation and the operator handbook state the payout timing: at the
earliest the part's stop, plus the dispute window, plus 7 days. The buyer
documentation states that approval is refused when the balance cannot cover the first
reservation, and that a top-up after a deal stops for lack of funds does not revive it;
the buyer opens a new deal.

### D5 — The production deadline comes from the seller's payments clause, as a stopgap

The VM production configuration sets `delivery_deadline_seconds` in the seller's
payments clause. Publication takes the pool's effective deadline when the pool's port
supplies one and the clause's otherwise
(`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`); no
composition wires the port yet, so every VM production option publishes the clause's
value, promises a deadline, and is accepted by the default buyer without a waiver.

It is the storefront-enforced stopgap the foundation's design set aside: the
storefront's servicing journal classifies a missed deadline as seller non-delivery
(`kit/deal-servicing/src/market_deal_servicing/journal.py`), while the site neither
knows nor enforces it, and a payments mechanism's clause carries a lifecycle term.
`renewable-compute-lease-deadlines` retires it after the MVP: the pool's
`delivery_deadline_seconds` tag supplies the value through the port, and the site
refuses a commit beyond it and reclaims the lease on expiry. Until then the runbooks'
abandoned-lease truncation and the monitoring of committed reservations still
unactivated past their deadline stay, since nothing at the site lapses them.

Rejected: shipping with no deadline and asking every buyer for
`--allow-no-delivery-deadline`, which makes the MVP unusable by a buyer who changed no
setting; and waiting for `renewable-compute-lease-deadlines`, whose pool-authority
prerequisite is still in design.

## Open Questions

- When mediation is deployed to the hosted test target, and when to the production
  target; the payments service's maintainers have deferred both until the stack is
  close to production.
- Whether the payments service will distinguish funds running out from a term end in
  the signed stop cause, which would let `serve-running-rate-deals` drop its
  comparison with the Agreement's end.
- How the payments service will announce a receipt key rotation, which decides
  whether the drain runbook can be triggered by notice rather than by operator
  coordination.
