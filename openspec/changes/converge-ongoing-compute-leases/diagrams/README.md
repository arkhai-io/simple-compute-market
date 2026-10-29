# Rate-part servicing scenarios

Nine sequence diagrams illustrate cases 0–8 of [the design](../design.md#scenarios-and-evidence).
The qualification matrix also includes maximum term, the on-demand emergency and
identity-rotation overlap. Interim rows record buyer-policy opt-in and separate
default refusal from returned-capable acceptance.
Lane absence/crash arrows mean pause/resume; durable restart is integration evidence.
Buyer client, end service (physical P / authority-work F), site, payment authority
and dispute authority are separate lifelines. Numbered arrows give scenario order;
self-arrows are local transitions. A diagram is design, not evidence of a run.
`exceptional_end` is a seller dispute filing. Only a qualifying payee self-penalty
is mechanically ruled by mediation; it applies returned rate stops, refunds and
any full bond through its own authority entries. Seller sends no stop/reverse for
that path, and spot emergency uses the same filing. end_delivery carries no at;
storefront receipt is evidence only, not payment authority. Buyer half alone
journals/retries payment stop under the same key during outage, with billing until
it lands. buyer_end is human-triaged with exact Agreement and signed evidence.

| # | Diagram | Guarantee |
|---|---|---|
| 0 | [On-demand baseline](00-on-demand-baseline.svg) | authority stop and physical recovery earn separate facts |
| 1 | [Payments-down buyer end](01-buyer-cancel-payments-down.svg) | signed end_delivery acknowledgement supports buyer_end; physical work is independent |
| 2 | [Site withdrawal, storefront absent](02-site-withdraws-storefront-dead.svg) | buyer stop/case and held money, then seller self-penalty filing on recovery |
| 3 | [Crash during case effects](03-crash-during-case-effects.svg) | original filing identity, partial ruling effects after stop, revised request with prior-ruling netting |
| 4 | [Stop before disclosure](04-payer-stop-before-disclosure.svg) | local end blocks disclosure; remote observation has a measured window |
| 5 | [Activation expiry](05-prepaid-activation-deadline-expires.svg) | failed rate delivery corrects exceptional_end at start, including setup once |
| 6 | [Funding/exhaustion](06-funds-exhausted.svg) | read before end; renewal replaces timer, exhaustion supplies authority end |
| 7 | [Spot notice](07-spot-preemption-with-notice.svg) | authority-hosted pending stop survives absent storefront; earliest stop wins |
| 8 | [Started but undelivered](08-start-before-delivery.svg) | mechanically ruled payee self-penalty plus human buyer-case backstop |

Each SVG is rendered from its adjacent `.drawio` XML and embeds that exact editable
source in its content attribute. Update source and regenerate the rendering
together; never edit the SVG alone. At servicing closeout, promote the pairs to
`docs/development/diagrams/` and cite them from deal-lifecycle's architecture
companion, which owns end-service behavior. The 05 filename retains `prepaid` as a
stable link: its fixture is a prepaid-balance rate deal, not a once-only scenario.
Activation does not promote a second copy.
