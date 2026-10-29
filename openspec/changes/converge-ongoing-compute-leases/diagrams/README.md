# Scenario diagrams

Sequence diagrams of the continuation's edge cases, one guarantee each, cited from
the decisions in [`../design.md`](../design.md) and promoted to
`docs/development/diagrams/` at `activate-per-period-compute-servicing`'s closeout.
Lifelines, left to right: the buyer's client, the storefront (its physical queue `P`
and financial queue `F` drawn as two activation bars), the site, the payments
service. Solid arrows are calls; dashed arrows are events and responses; boxed
italics are durable writes; a grey band is time passing; a dashed grey box on the
storefront lifeline is the storefront down. The last row states what the scenario
demonstrates.

| # | File | Demonstrates | Cited from |
|---|---|---|---|
| 0 | [`00-on-demand-baseline`](00-on-demand-baseline.svg) | the normal path and where each durable fact is written | D2, D3 |
| 1 | [`01-buyer-cancel-payments-down`](01-buyer-cancel-payments-down.svg) | the end-deal route works alone; the stop lands later; no charge past the decision's physical end | D6 |
| 2 | [`02-site-withdraws-storefront-dead`](02-site-withdraws-storefront-dead.svg) | the horizon lapses billing at *V* on its own; the excess (*E*, *V*] ≤ `reserve_ahead` is journaled as a `refund` | D1, D5 |
| 3 | [`03-crash-between-reverse-and-stop`](03-crash-between-reverse-and-stop.svg) | reverse before stop is safe: the horizon bounds the tail | D5 |
| 4 | [`04-payer-stop-before-disclosure`](04-payer-stop-before-disclosure.svg) | no disclosure after a committed end; the charge runs from `start` to the stop only | D3, D4 |
| 5 | [`05-prepaid-activation-deadline-expires`](05-prepaid-activation-deadline-expires.svg) | the site's `renewal_lapsed` in the awaiting-activation phase commits a full refund | `unify-compute-delivery-path` D5 |
| 6 | [`06-funds-exhausted`](06-funds-exhausted.svg) | `fundedThrough` stops advancing; nothing is vouched or renewed past it; billing stops at the funded horizon | D2 |
| 7 | [`07-spot-preemption-with-notice`](07-spot-preemption-with-notice.svg) | a scheduled end at now + notice; the started period reversed before the stop; an earlier buyer cancel supersedes | D5; `publish-and-preempt-spot-compute` D2 |
| 8 | [`08-start-before-delivery`](08-start-before-delivery.svg) | the buyer's recorded delivery instants against the signed `start` event are its dispute evidence | `settle-ongoing-compute-through-arkhai-payments` D2, D11 |

Convention, as in `docs/development/diagrams/`: each diagram's source is the
`.drawio` file; the `.svg` beside it is the export with the source embedded in its
`content` attribute, so it opens in draw.io. The export is never edited by hand:
after changing a source, redraw the export, and keep the embedded copy equal to the
source.
