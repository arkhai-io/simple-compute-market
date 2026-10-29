# Rate-part servicing scenarios

Nine reconciled sequence diagrams illustrate [the design](../design.md#scenarios-and-evidence).
Buyer client, end service (physical P / authority-work F), site, payment authority
and dispute authority are separate lifelines. Numbered arrows give scenario order;
self-arrows are local transitions. A diagram is design, not evidence of a run.

| # | Diagram | Guarantee |
|---|---|---|
| 0 | [On-demand baseline](00-on-demand-baseline.svg) | authority stop and physical recovery earn separate facts |
| 1 | [Payments-down buyer end](01-buyer-cancel-payments-down.svg) | signed end_delivery acknowledgement supports buyer_end; physical work is independent |
| 2 | [Site withdrawal, storefront absent](02-site-withdraws-storefront-dead.svg) | buyer stop/case and held money, then seller self-filing on recovery; no horizon cap |
| 3 | [Crash during case effects](03-crash-during-case-effects.svg) | stable case/effect keys, partial reverse after stop, late evidence append |
| 4 | [Stop before disclosure](04-payer-stop-before-disclosure.svg) | local end blocks disclosure; remote observation has a measured window |
| 5 | [Activation expiry](05-prepaid-activation-deadline-expires.svg) | failed delivery files exceptional_end at start, including once-part consequences |
| 6 | [Funding/exhaustion](06-funds-exhausted.svg) | renewable local timer, not speculative lease truncation |
| 7 | [Spot notice](07-spot-preemption-with-notice.svg) | authority-hosted pending stop survives absent storefront; earliest stop wins |
| 8 | [Started but undelivered](08-start-before-delivery.svg) | cooperative self-filing plus buyer-case backstop |

Each SVG is rendered from its adjacent `.drawio` XML and embeds that exact editable
source in its content attribute. Update source and regenerate the rendering
together; never edit the SVG alone. At servicing closeout, promote the pairs to
`docs/development/diagrams/` and cite them from settlement-servicing's architecture
companion. Activation does not promote a second copy.
