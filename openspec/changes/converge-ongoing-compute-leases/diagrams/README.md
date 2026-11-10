# Rate-part servicing scenarios

Nine sequence diagrams illustrate cases 0–8 of [the design](../design.md#scenarios-and-evidence).
The qualification matrix also includes maximum term, the seller emergency,
identity-rotation overlap, the seller that never files, the late anchor, asserted
availability and a case over paid-out money (rows 9–13). Rows 7 and 9 record the
buyer acceptance policy the terms change ships.
`serve-running-rate-deals-on-vm` qualifies reduced forms of rows 0, 6, 7 and 9 in
the VM lane — charged treatment, no setup part, no funding timer — without
promoting these diagrams; they show the full product and are promoted at this
change's closeout. Diagram 06 shows the seller's opt-in funding timer; with the
timer disabled, the verified exhaustion stop alone ends delivery.
Lane absence/crash arrows mean pause/resume; durable restart is integration evidence.
Buyer client, end service (physical P / authority-work F), site, payment authority
and dispute authority are separate lifelines. Numbered arrows give scenario order;
self-arrows are local transitions. A diagram is design, not evidence of a run.
delivery_end is one claim for either filer and either cause. Payee filing or valid SignedDeliveryEndClaim concurrence enables mechanical ruling only with clean mapping, ended_at >= Agreement start and no prior mechanical end ruling. Receipt-backed payer claims qualify; unsigned, contested, repeat and unanswered cases stay with operators, never a silence default. Cause=payee uses returned rates, refunds and capped penalty; cause=payer preserves notice/treatment and pays no penalty. Setup returns iff delivered=false for either cause. Seller sends no payment effects for its case. The end_delivery receipt embeds the reusable signed claim; buyer payment-stop retry remains separate. SCM polls unanswered cases and signs matching durable facts or contests them.

| # | Diagram | Guarantee |
|---|---|---|
| 0 | [On-demand baseline](00-on-demand-baseline.svg) | authority stop and physical recovery earn separate facts |
| 1 | [Payments-down buyer end](01-buyer-cancel-payments-down.svg) | signed end_delivery acknowledgement supports delivery_end; physical work is independent |
| 2 | [Site withdrawal, storefront absent](02-site-withdraws-storefront-dead.svg) | buyer stop/case and held money, then seller self-penalty filing on recovery |
| 3 | [Crash during case effects](03-crash-during-case-effects.svg) | original filing identity, partial ruling effects after stop, revised request with prior-ruling netting |
| 4 | [Stop before disclosure](04-payer-stop-before-disclosure.svg) | local end blocks disclosure; remote observation has a measured window |
| 5 | [Activation expiry](05-prepaid-activation-deadline-expires.svg) | failed rate delivery corrects delivery_end at start, including setup once |
| 6 | [Funding/exhaustion](06-funds-exhausted.svg) | with the seller's opt-in timer: read before end; renewal replaces timer, exhaustion supplies authority end |
| 7 | [Spot notice](07-spot-preemption-with-notice.svg) | authority-hosted pending stop survives absent storefront; earliest stop wins |
| 8 | [Started but undelivered](08-start-before-delivery.svg) | payee-agreed delivery_end or contested-case human backstop |

Each SVG is rendered from its adjacent `.drawio` XML and embeds that exact editable
source in its content attribute. Update source and regenerate the rendering
together; never edit the SVG alone. At servicing closeout, promote the pairs to
`docs/development/diagrams/` and cite them from deal-lifecycle's architecture
companion, which owns end-service behavior. The 05 filename retains `prepaid` as a
stable link: its fixture is a prepaid-balance rate deal, not a once-only scenario.
Activation does not promote a second copy.
