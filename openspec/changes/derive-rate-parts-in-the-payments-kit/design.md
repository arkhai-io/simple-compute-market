# Design: derive-rate-parts-in-the-payments-kit

## Context

One of Goal 8's MVP changes; `offer-per-period-vm-terms`'s design states the set
and the MVP's scope.

What exists:

- The vendored contract has `RatePart`, per-part `RateAuthorities` with payee-only
  `start`, `StopAuthority{account, notice, partialPeriod}`, `PartEnd`, `afterStop`
  and `for` holds, and auto-recharge; the vectors cover the rate cases the MVP
  uses (`kit/arkhai-payments/schema/SOURCE.md`).
- `derive_part_terms(kind="rate")` already emits rate authorities, end and holds;
  `derive_mandate` assembles only a once part
  (`kit/arkhai-payments/src/market_arkhai_payments/mandates.py`).
- `kit/deal-lifecycle/src/market_deal_lifecycle/authorities.py` always adds the
  dispute authority's stop entry with `chosen` treatment to a rate part.
- The lifecycle contracts already name `start` and `stop` commands
  (`kit/deal-lifecycle-contracts`); there is no separate notice command, so a
  notice is a stop with an effective time.
- The delivery path already calls `begin_billing`, which reaches the adapter's
  `start_billing`; the once policy returns a no-op
  (`domains/compute/delivery/src/compute_delivery/path.py`,
  `kit/deal-servicing/src/market_deal_servicing/end.py`).
- The in-process engine and the payments double implement full rate semantics.

## Decisions

### D1 — The kit derives and services rate parts against the vendored contract

There is no older contract with plain rate parts to target; the historical
publication's mandates are refused by current models. The kit therefore derives
the vendored contract's rate part, and the MVP uses the subset of it listed in
D2.

### D2 — Only declared treatments are derived; the MVP declares `charged`

Derivation and materialization read the composition's servicing declaration, the
list of started-period treatments it has qualified (`offer-per-period-vm-terms`).
A rate mandate or option asking for an undeclared treatment is refused, so no deal
depends on a treatment its composition has not qualified. The MVP's declaration is
`[charged]`, so every stop entry and the part end carry `partialPeriod: charged`;
`spot-deals-through-arkhai-payments` adds the others as compositions declare them. The MVP's use of the
contract is then: rate approval, payee `start`, payer and payee `stop` with
notice, reserve-ahead refill and exhaustion at funded-through, the term `end`,
`reverse` while held, and signed snapshots.

### D3 — Operators stop billing through the dispute account's stop entry

On-demand gives the seller no stop, so after a seller-side failure only the buyer's
stop or the dispute authority's stop ends billing. The MVP's dispute authority is
Arkhai operators, who use the dispute account's stop entry the kit already adds
and the payments service's `reverse`. If the hosted service cannot execute
`chosen` treatment on that entry, the entry carries fixed `charged` treatment
instead; which one ships is settled with the payments team (`switch-on-hosted-per-period-vm`).

If the fallback ships, the dispute entry's treatment is bound into the option's
settlement parameters from the first deal, so it is part of the option ID. The
buyer's exact check re-derives the mandate from the Agreement and the option; a
derivation rule that later changed from `charged` to `chosen` would make every
running deal re-derive differently. With the treatment bound, MVP-era options keep
re-deriving as `charged`, and `spot-deals-through-arkhai-payments`' restoration of
`chosen` gives new options new IDs.

Rejected: a zero-notice seller stop on on-demand, which changes the product's
terms; and an administrative stop outside the deal's terms, which the deal's
signed authorities would not record.

### D4 — Earnings stay held until the stop plus the dispute window

The derivation keeps the `afterStop` hold. A seller is paid for a running deal
only after its part stops and the window passes. This is an accepted MVP
limitation: early deals are expected to last less than a day. In the full product
the hold becomes a seller-chosen option term the buyer sees: a shorter `for` hold
releases earnings sooner and is displayed as reduced buyer protection, since a
case can reach only money still held (`negotiate-open-ended-compute-terms` owns
the term, `spot-deals-through-arkhai-payments` its derivation).

## Open Questions

- Whether the hosted payments service executes `chosen` treatment on the dispute
  stop entry (D3's fallback), to be answered by the payments team.
- How a Stripe-funded balance's top-up interacts with reserve-ahead refill timing,
  and whether funding exhaustion is observed as a stop record the adapter can
  verify like any other.
