# Design: offer-a-seller-chosen-payout-hold

## Context

The lifecycle foundation fixed one hold for every payments part: the seller's
earnings stay held from the part's start until its stop plus the option's dispute
window (`kit/arkhai-payments/src/market_arkhai_payments/mandates.py` derives
`{afterStop: <dispute window>}`). A case extends the hold while it is open, up to the
option's `case_hold_max_seconds`. The payments service pays a seller out a fixed seven
days after release, so a seller is paid at the earliest at the stop, plus the dispute
window, plus seven days.

Held money is the remedy's only source. The foundation's standard self-penalty, for a
seller's end its terms do not entitle, stops the rate, returns what the buyer did not
receive and takes the premature-stop penalty out of earnings still held, capped by
them (`openspec/specs/deal-lifecycle/architecture.md`, its external-authorities
section). The archived `negotiate-open-ended-compute-terms` shipped an on-demand
default penalty of 24 periods' price and a default buyer that refuses an on-demand
option without a positive penalty
(`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`); its
design records the penalty as a ceiling, not a guarantee. In Goal 8's MVP an
unentitled seller end is ruled by Arkhai operators by hand, out of held funds.

The vendored payments contract offers two hold shapes on a part: `afterStop` a
duration, and `for` a duration (`kit/arkhai-payments/schema/payments.schema.json`).

## Decisions

### D1 — The hold is a seller-chosen option term, not a uniform rule

Each option states its payout hold as a codec-owned lifecycle term, so it is in the
option ID and the buyer approves exactly what it read. The default — the term absent —
is the foundation's hold until the stop plus the dispute window, so every option
published today keeps its ID and meaning. A seller may state a shorter hold. The
market does not choose one hold for everyone: a hold as long as the part plus the
dispute window converges on the foundation's behaviour, and a shorter one is a visible
property of that listing.

Rejected: one uniform hold, which either keeps every seller waiting or removes the
protection for every buyer.

### D2 — Derivation and the exact check

The payments kit derives `afterStop` for the default and `for` the stated duration
otherwise; the buyer re-derives the mandate before approval and refuses any difference,
as it does for every other field. Whether a `for` hold may be shorter than the dispute
window, and how it meets `case_hold_max_seconds`, is open below.

### D3 — A shorter hold is shown, never refused by default

The buyer's display states the hold, when the seller is paid, and, for a hold shorter
than the stop plus the dispute window, that the option gives reduced protection. The
default buyer does not refuse it; a buyer may refuse it by policy.

### D4 — The penalty's collectibility is decided with the hold

Open, decided in this change's design session. A shorter hold reduces what a penalty
can reach, so the penalty a buyer reads must say what is behind it. Candidates:

- **A ceiling stated as a function of the hold.** The display and the term state the
  penalty as collectible up to the earnings the hold keeps; the default buyer's
  penalty refusal reads the collectible figure, not the nominal one.
- **A floor of held funds.** A seller choosing a hold shorter than the default must
  keep held at least its penalty, so the hold releases earnings only above that floor;
  this needs a hold shape the contract may not offer.
- **Operator enforcement beyond what is held.** The penalty stays nominal and
  operators pursue the remainder outside the payments service, which the MVP's manual
  disputes already rely on and which binds no one mechanically.

The default buyer should not require a penalty it cannot collect; whichever rule is
chosen, the refusal and the display follow it.

## Open Questions

- Whether a `for` hold may end before the stop plus the dispute window can be filed
  on, and how it interacts with case extensions capped by `case_hold_max_seconds`.
- D4's rule, and whether the floor of held funds is expressible in the vendored
  contract.
- Whether the hold term is offered on once-only options as well as rate parts.
- The registry filter's shape: a maximum hold, a protection flag, or both.
