# Design: switch-on-hosted-per-period-vm

## Context

The last of Goal 8's MVP changes; `offer-per-period-vm-terms`'s design states the
set. It follows `serve-running-rate-deals-on-vm` and is blocked on the hosted
payments deployment.

`activate-per-period-compute-servicing` designs the full switch-on: both compute
domains, the consolidated matrix run hosted, the mediation `delivery_end`
revision, and Goal 8's completion bar: an unconfigured buyer taking on-demand and
spot live under the shipped presets, with a live preemption returning the unstarted
remainder. The MVP
switches on VM with charged treatment and operator-handled disputes; the rest
stays with that change.

## Decisions

### D1 — The declaration follows hosted evidence, and is withdrawn without reinterpreting deals

The VM production composition declares `charged` servicing only after the hosted
revision is confirmed and the live runs pass; `activate-per-period-compute-servicing`
extends the list as further treatments are qualified hosted. Withdrawing it stops new
per-period deals and leaves existing deals on the authorities they were made
under.

### D2 — Operators are the MVP's dispute authority

Arkhai operators hold the dispute account and act through its stop entry and the
payments service's reversal, following runbooks in the operator handbook. A
published policy states key retention, continuity and case handling; no response
bound is promised.

### D3 — Live evidence is recorded apart from lane-double evidence

Only runs against the hosted target are live evidence; lane runs remain
lane-double evidence.

## Open Questions

Questions for the payments service's maintainers, which gate this change:

1. Which contract revision runs on the hosted test target, and which on production?
2. Does it execute rate parts: payee start, payer and payee stops with notice
   under charged treatment, reserve-ahead refill from a Stripe-funded balance,
   exhaustion at funded-through, and the term end?
3. Does approval accept the dispute authority's stop entry with `chosen`
   treatment, and can the dispute account execute it? (If not,
   `derive-rate-parts-in-the-payments-kit` derives fixed `charged` treatment.)
4. Can the dispute account stop and reverse on a running rate part as the
   runbooks require?
5. What key-retention commitment does the payments service make for the life of a deal?
6. What does production (livemode) onboarding and seller payout require?
