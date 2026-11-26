# Rate servicing scenarios

Nine sequence diagrams, one for each of rows 0 to 8 of
[the design's scenario table](../design.md#scenarios-and-evidence); rows 9 to 13 have
none. The buyer client, end service (physical work P, authority work F), the site, the
payment authority and the dispute authority are separate lifelines. Numbered arrows give
the order; self-arrows are local transitions. An absence or crash arrow means the
storefront's loops are held. A diagram is design, not evidence of a run.

| # | Diagram | Draws | State |
|---|---|---|---|
| 0 | [On-demand baseline](00-on-demand-baseline.svg) | The authority's stop and the physical release as separate facts | Its last step, "Record both completion facts", predates `deal-lifecycle`'s "The seller half lists deals"; redraw once the design's Q2 is settled |
| 1 | [Buyer end, payment authority unreachable](01-buyer-cancel-payments-down.svg) | The signed `end_delivery` receipt backing a `delivery_end` case; physical work independent of both authorities | Current |
| 2 | [Site withdrawal, storefront not servicing](02-site-withdraws-storefront-dead.svg) | The buyer's stop and case over held money, then the seller's filing | Its title and its restart arrow assume a stopped storefront; redraw once Q4 is settled |
| 3 | [Interrupted case effects](03-crash-during-case-effects.svg) | One filing identity, partial ruling effects, a revised request netted by the authority | Its revised request depends on Q3 |
| 4 | [Stop before disclosure](04-payer-stop-before-disclosure.svg) | A local end blocking disclosure | The row is proven at integration, not in a lane (Q7); the diagram still draws the admission order |
| 5 | [Delivery deadline](05-prepaid-activation-deadline-expires.svg) | A rate deal never delivered, filed at the Agreement's start | Needs redrawing: it draws a deadline the site enforces and a site-signed end before activation. The storefront enforces the deadline, after a payment read made past it; site enforcement is `renewable-compute-lease-deadlines`' |
| 6 | [Funding timer and exhaustion](06-funds-exhausted.svg) | A seller's funding timer read before an end | Not this change's: the end of a deal at its funded instant is `end-delivery-when-funding-runs-out`'s (design D4), which builds no seller opt-in timer and redraws this pair once its design settles what a storefront does at a funded instant it cannot confirm. Kept until then. Funds running out with no timer runs in both lanes |
| 7 | [Spot notice](07-spot-preemption-with-notice.svg) | A pending stop the payment authority holds; the earliest stop wins | Current |
| 8 | [Started, never available](08-start-before-delivery.svg) | A payee's `delivery_end` filing, with the buyer's case as the backstop | Current |

Each SVG is rendered from the `.drawio` file beside it and embeds that source. Change
the source and regenerate the rendering together; never edit the SVG alone. The 05
file keeps `prepaid` in its name as a stable link.

At closeout the pairs that draw the product as it is are promoted to
`docs/development/diagrams/` and cited from `deal-lifecycle`'s companion; a pair marked
for redrawing is redrawn first or left behind.
