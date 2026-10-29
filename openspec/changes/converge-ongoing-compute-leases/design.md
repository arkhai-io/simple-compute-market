# Design

## Context and authority

This is rate-part servicing inside end service, not a second deal lifecycle. The
frame is `agreed-evidence-and-early-termination`: commitment, lifecycle, final
request, `early_termination {entitlements, notice_seconds, exposure_seconds,
max_term_seconds}`, adjudication, payment/dispute adapters and evidence stores.
The protocol ends at commitment; post-commitment records are lifecycle and evidence.
The storefront and site are one seller from the buyer's perspective.

The current storefronts verify approval before delivery but do not keep rate-part
funding, authority stops and lease effects converged after delivery. The new kit is
planned, not current architecture. This change extends the foundation rather than
claiming to supply its routes or the hosted adapter's mechanics.

## Goals and non-goals

Both VM and bare-metal compositions service committed rate-part deals across
restarts and authority outages, revoke access after ends, and report unfinished
physical and financial work separately. Buyer safety rests on authority records
and exact kept signed bytes even if the storefront does not cooperate.

No vouch, billing horizon, site renewal protocol, local stop scheduler, independent
financial-effective-end register, payment ledger or minimum spend is introduced.
Rate-part mechanics, presets, option publication and seller notice commands belong
to `spot-deals-through-arkhai-payments`. The buyer half and `end_delivery` route
belong to `agreed-evidence-and-early-termination`; the one delivery state machine
belongs to `unify-compute-delivery-path`.

## Decisions

### D1. Ownership and dependency gates

`kit/deal-servicing` owns the storefront's loop, lifecycle observation state,
evidence store, end-service journal and domain-neutral physical ports. It receives
payment and dispute adapters through the lifecycle tables; it imports neither
mechanism kit, dispute kit nor domain implementation. Both storefront compositions
supply lease lookup, delivery/admission state, terminate/truncate and evidence
ports. No second state machine is created in a domain payment coordinator.

Implementation starts only after the foundation's final-request/admission,
watch/cursor, evidence and command contracts, the spot change's rate mechanics,
and the unified delivery path's authorization/activation ports are available.
Scenario execution additionally gates on the in-lane payment and mediation doubles.

### D2. Durable state and two completion facts

From a verified commitment, persist negotiation/commitment references, accepted
Agreement binding, domain delivery/lease handle, verified payment and dispute
cursors, latest verified funding observation, local funding timer, earliest final
request with actor/cause/source, immutable effect identities and completion facts.
Evidence bytes live in the evidence store, not solely in mutable replay state.

- Physical completion: the site's signed `lease_ended` is recorded, or the delivery
  state proves no resource was dispatched. A dispatched operation with an unknown
  result is adopted and terminated before this fact is earned. A reasoned,
  seller-authenticated manual recovery acknowledgement may record physical
  completion when site evidence is unavailable; it is labelled manual and is not
  represented as site evidence.
- Financial completion: for the current end revision, authority records confirm
  all required parts stopped (or never earning and terminal), every end-related
  filing/ruling effect and adapter correction is resolved, and no operation has a
  pending or unknown outcome. Acceptance of a case alone is not completion.

A running deal has neither end completion merely because an observation succeeded.
End processing selects committed deals not complete on both sides. Watching and
evidence retention continue under the foundation's rules even after end work
completes: a newly observed earlier end or relevant ruling reopens financial work
for a new end revision, preserving prior completion history. **Recommendation
supplied here:** scope the financial fact to an end revision rather than deleting
its history when late evidence reopens work. Physical completion never resurrects
a resource. Thus late evidence is not dropped by a terminal filter.

Expose the time between the facts, pending case/operation references and repair
reasons in lifecycle read/list diagnostics. Physical completion before financial
completion can be normal during priced notice or a case; do not label that entire
gap an overcharge. Financial completion before physical completion is the seller's
unpaid-service exposure. An operator cannot declare money corrected by hand.

**Recommendation supplied here:** warn when a physical gap exceeds the configured
watchdog-plus-teardown budget; warn for authority work after one configured retry
budget and immediately surface permanent refusals as repair required. Numerical
budgets are deployment settings validated from real latency, not double timings.
The loops continue after a warning.

### D3. Two independent queues inside end service

Each cycle services physical work first, then authority work, with independent
error handling and bounded I/O so an unavailable authority cannot stall later
physical cycles. The physical queue executes due final requests and reads the
site for recovery evidence. No payment/dispute call is required to admit that work.
A failed physical effect does not suppress authority work either.

The authority-work queue consumes verified payment and dispute observations,
updates renewable funding timers, journals final requests and drives pending
lifecycle commands. A newly observed due end schedules physical work immediately,
without waiting another normal polling interval. Each record's cursor advances
only after its effect is journaled; there is no ordering invented across records.
Unknown outcomes are resolved by read and retry with the same operation key.
Invalid/unavailable snapshots produce no new funding or financial fact and do not
block physical work or erase previously journaled requests.

An entitled stop's notice lives at the payment authority. A pending stop is not a
stop now: its effective time supplies the future final request, and the earliest
pending stop wins. The storefront can truncate physical service to that final
instant, but its survival is not what makes the payment stop fire. Funding is
separate: a verified funded-through deadline is a replaceable local timer; funding
can advance it. It becomes a final request only on expiry without a verified
renewal, never by truncating the lease speculatively. An expiry during an outage
may cost the seller a working lease; if no entitlement covers that local end, D5
requires self-filing. No site deadline is required to follow that timer.

### D4. Delivery authorization and access

Implement `authorize_delivery(deal, phase)` through the injected rate-part adapter.
Before dispatch/start, validate current authority evidence, first-batch reservation
and absence of an effective stop under the spot change's rules. Provision before
payee-only `start`; journal its stable identity with delivery evidence, and resolve
an unknown start before retrying or disclosing. Recheck admission and authority
evidence at disclosure. A pending stop in the future permits only the remaining
service window. Refusal enters the unified path's undelivered route and D5.

A local due final request is serialized with dispatch and disclosure. Nothing is
disclosed after it. In-flight fulfillment is adopted and ended; a started lease
that expired before activation is treated as undelivered from the deal's start.
Credential reads enforce local delivery state rather than requiring an authority
network request each time. Revocation of already disclosed credentials means
physical teardown, not just refusing future reads.

A remote effective stop is incorporated within one polling interval while healthy,
then the configured watchdog/teardown budget applies. `exposure_seconds` must cover
that entire window at publication and acceptance, as the foundation specifies.
A proposed configuration that breaks an active deal's exposure budget is refused;
runtime shortfalls warn but never stop servicing. There is no absolute no-access
claim between remote stop and observation. With the storefront absent, service can
continue to the maximum lease term; that is the seller's liveness risk. An optional
site activation deadline protects seller capacity before delivery, not buyer money.

### D5. Holds, self-filing and bounded residual

Every rate part holds earnings under `{afterStop: dispute_window}`. A timely case
accepted as held at the payment authority extends protection; a filing response
alone does not prove that extension. Stops are never backdated. A site withdrawal,
failed or never-started delivery, or any other local end not covered by entitlement
journals `exceptional_end(at)` atomically with the final request. For failed or
never-started delivery, `at` is the deal's start. The dispute adapter builds the
request; Arkhai mediation's mechanical self-penalty stops now and reverses earnings
since `at` (and applies the applicable once-part/bond consequences). End service
never turns that filing into a bare payee stop on an on-demand mandate.

Financial work uses the spot change's cumulative correction target, immutable
operation keys, half-open arithmetic and started-period rule through its adapter.
It does not introduce a `refund` journal kind, require reverse-before-stop, or own
a financial-effective-end register. The dispute authority applies case outcomes;
the seller neither applies them nor computes replacement rulings. If earlier site
evidence arrives after a filing, journal an append to an open case with the kept
evidence and observe the resulting ruling/correction. A confirmed closed case is
not appended to: while protection permits, file a new exceptional_end for the new
end revision with prior effects as evidence. Use a stable revision-bound filing
key, not a fresh arbitrary payout key. The authority determines any further remedy.

The residual is **not** at most reserve-ahead after an unnoticed end. A silent or
malicious seller can continue billing until the buyer's authority stop becomes
effective, exhaustion, or the maximum term. The buyer's priced stop notice bounds
its authorized stop tail; reserve-ahead bounds seller exposure on exhaustion.
Held earnings and a timely case make the unserved interval reversible, including
after stop; recovery depends on the agreed dispute authority and timely action,
not on seller liveness. No automatic crash-to-stop guarantee is claimed. If both
authorities are unavailable, unresolved filings remain durable and financial
completion stays false; no finite authority-recovery time is promised.

### D6. Buyer and seller commands compose the same lifecycle

The buyer half tries its payer stop first and sends `end_delivery {at}` regardless
of payment reachability. The storefront acts on this authenticated peer message
without an authority read, persists the final request and returns a signed
acknowledgement. It moves no money. If the payment authority is unavailable the
buyer files `buyer_end(at)` with that acknowledgement; if both authorities are
unavailable it journals and retries the filing. Without an acknowledgement, the
buyer still has its own kept evidence and a case, but no mechanical-ruling claim.
This change exercises that foundation-owned flow rather than duplicating it.

The site-signed `lease_ended` is ingested idempotently, kept as exact signed bytes,
and returned on the buyer's lifecycle read; it is seller evidence, not a payment
or dispute authority record. Late evidence can cause D5 work without reviving a
lease. Seller notice/preemption uses the spot change's seller-half command. An
operator can run the seller half against the owned persisted state with the
storefront stopped; entitled stops retain authority-hosted notice, while an
unentitled emergency files `exceptional_end`. Never run a competing database
writer beside the storefront. Manual physical recovery is an explicitly audited
operation, distinct from these authority actions.

### D7. Restart, rotation and activation

Restart recovers journaled effects and both record cursors; it does not infer
convergence from a lease status or historical approval receipt. Compose the spot
change's verified-snapshot identity re-anchoring and report unreanchored deals.
The servicing declaration is required at publish, accept and materialize. With
accepted rate-part deals persisted, startup without the servicing loop is an
incoherent local configuration and is refused. Withdrawing new publication never
removes servicing of existing commitments. A dependency outage alone does not
refuse startup.

The lane alone may declare proposed-contract servicing. Production waits for
`activate-per-period-compute-servicing` to verify the hosted deployment of the
payments revision with per-part authorities and hold extensions. There is no
horizon capability gate and no request for one.

## Scenarios and evidence

The diagrams in [diagrams/](diagrams/) illustrate these nine cases. Run in VM and
bare-metal lanes against the in-lane payment and mediation doubles, pausing loops
and advancing explicit side effects, with exact signed records and both facts:

| # | Scenario | Required observation |
|---|---|---|
| 0 | On-demand baseline | setup once + rate, provision/start/activate/disclose, payer stop with priced notice, end service, both facts |
| 1 | Buyer ends with payments down | before provisioning, during dispatch and after delivery: physical work and signed acknowledgement; buyer_end, stop-now/reverse on recovery; both-down replay |
| 2 | Site withdraws with storefront dead | buyer can stop/file independently; on recovery late lease_ended triggers exceptional_end/append; no reserve-ahead residual claim |
| 3 | Crash after filing, before ruling effects finish | same case/key on replay, stop and partial reverse after stop observed once, no double correction |
| 4 | Payer stop between start and disclosure | no disclosure after local due end; remote-stop windows measured before/after disclosure |
| 5 | Activation deadline expires, once or rate deal | undispatched completes empty; dispatched is adopted/ended; exceptional_end at start, once reversal and rate correction through ruling |
| 6 | Funds exhausted | verified funding timer advances without truncation, expires if not renewed, authority exhaustion stop and physical recovery |
| 7 | Spot notice, then earlier payer stop | authority-hosted pending stop survives dead storefront, earliest effective stop wins; cause-specific period treatment, including seller-only notice variant |
| 8 | Seller starts but never delivers | kept start/delivery evidence, seller self-filing and buyer-case backstop against a noncooperative seller |

Focused integration additionally exercises payment outage during teardown, failure
of physical work with successful authority work, invalid/stale/wrong-transaction/
regressed snapshots, lost acknowledgements then earlier site evidence, restart
between final-request and filing, manual physical recovery, startup declaration
checks, short-deal setup pricing, and rotation re-anchoring. Contract qualification
is labelled proposed or published; double evidence is never live evidence.

## Rejected alternatives

- Payee-advanced billing horizon/vouch: a dishonest seller can advance it; buyer protection must use its own stop and held-money case.
- Coupled site renewal and billing horizon: seller hardware policy cannot guarantee buyer billing; keep activation protection, defer renewal until separately operated sites need it.
- Storefront-local stop scheduling: it dies with the process; payment authority hosts pending notice stops.
- Backdated/effective-time payee stops: stop now plus reversal under held money covers correction without backdating authority records.
- Required minimum spend or a bare-metal gate on it: sellers price setup once parts and may refuse churners in negotiation policy.
- Refund-after-release journal and mandatory reverse-before-stop: afterStop holds and case extensions keep corrections reversible after stop.
- Separate physical/financial effective-end log: end service owns earliest delivery T; financial corrections are authority records and rulings.
- Bare payee stop for unentitled on-demand exit: mandate enforces no payee entitlement; self-filed exceptional_end supplies the honest exit.
- One queue or one completion fact: authority outages must not stall hardware recovery or hide unresolved corrections.
- Automatic physical completion on lease status alone: an unknown dispatched operation may still own a resource.
- Automatic financial completion on accepted filing: ruling and payment effects can remain pending.

## Recommendations and accepted limitations

Recommendations supplied here are the financial-fact end-revision implementation
and completion-gap warning policy in D2, and using the existing seller-half
offline composition for operator recovery in D6,
not a separate payment command implementation. Numeric cadence/retry budgets are
chosen during implementation from real domain measurements; they must pass the
foundation's exposure gate. Site renewal/lapse remains seller policy, not required.

Seller cash remains held until stop plus dispute window, and longer for held cases;
periodic collection, pooled funding, a storefront/site liability ledger, push
observation and lease top-up are outside this change. The buyer must retain bytes
and act within its dispute protection; there is no guarantee of a cooperative
seller or instantaneous adjudication. Setup once parts mitigate but need not fully
cover provisioning churn. These limitations are disclosed, not protocol additions.

## Permanent documentation destinations

Promote D1/D3/D7 composition ownership to market-composition and ARCHITECTURE's kit
areas/settlement servicing. Promote D2–D6 behavior to settlement-servicing spec and
its architecture companion, with lifecycle links for foundation-owned behavior.
Promote scenario requirements to test-compatibility and the diagrams to
`docs/development/diagrams/`. Record the Goal 8/index update at closeout. See tasks
for the decision-by-decision promotion record; no permanent document is changed
while this remains a proposed design.
