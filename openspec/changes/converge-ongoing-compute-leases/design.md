# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and revised the same day against three rounds of independent design review of the
goal. This change's own design review may reopen any of them with a finding; its
design session verifies them against the code as its four dependencies left it and
adds the spec deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning, since every
dependency changes it.

- VM's `VmPaymentsCoordinator.start` verifies the approval receipt
  (`check_receipt_now`, which reads nothing of the snapshot's stop state), deposits,
  inserts the delivery, spawns `_provision`, which sets `ready` or `failed` and does
  nothing after; `list_unsettled_payment_negotiations` skips deals with a delivery
  record; `delivery_facts` records `lease_end_utc = start + duration` from the
  Agreement. VM persists credentials into its delivery record, which the buyer's
  result read returns. Bare metal's `settle_payment` starts delivery once; its
  `fulfillment_service.py` commits `lease_start = now`, `lease_end = now +
  duration`, ignoring the Agreement's `start_utc`, and dispatches;
  `/fulfillments/{negotiation_id}/access` and `/result` expose delivery
  independently; `reconcile_payments_once` converges `accepted`, `refunding`, and
  verified-without-lifecycle deals. Neither re-reads the transaction after delivery,
  and the two domains reach commit, dispatch, and disclosure through different code
  with different windows — the kind of divergence `ARCHITECTURE.md` says to resolve
  by choosing one behaviour and composing it.
- Delivery start and refund intent are ordered by single-statement compare-and-set
  writes in each domain's tables; credentials are fetched uncached from the provider
  at `GET /fulfillment/{id}/result` for an `active` fulfillment.
- Refund is seller-initiated `reverse`; nothing issues `start` or `stop`.
- The buyer's settle paths approve, poll, then call the storefront; the run log
  records `payment_approved` with the transaction ID. No buyer-side stop exists.
- The storefront operator CLIs read the storefront's configuration and database
  directly; no command issues a payment event.
- A stored receipt is re-verified at restart against the current `service_identity`
  and `livemode`, which is why a rotation drains open deals today.
- The payments contract: a rate part's hold is `{until: stop}`; `PartState` runs
  `held → released`; the payee has `PayoutBalance.withdrawable` and
  `WithdrawalRequest`; `reverse` reaches held funds only; `PartSnapshot.refunded`
  exists with no command behind it; `EventCommand` carries no effective time. So a
  stop releases a rate part's earned periods toward the payee's balance, where
  nothing in the contract returns them to the payer.
- `kit-owned-listing-and-fulfillment-lifecycles` carries a proposed unified
  fulfillment path for the compute family, not yet designed; it records that this
  change takes the protected transitions and the access rule.
- Retention precedent: contact exchange's `retention_seconds`, applied by a
  held-and-stepped sweep; `buyer-initiated-compute-termination` D4 applies it to the
  request log.

## Goals / Non-Goals

**Goals:** a per-period deal is served exactly while it is funded and wanted, with a
fail-safe on each side that needs no cooperation from the other; both compute
domains get it through one implementation and one delivery path; physical
convergence never waits on payments; billing is corrected to the earliest
authenticated end, and money is conserved under lost acknowledgements; running deals
survive a service-identity rotation; the product is switched on only when its
billing guarantee can be kept.

**Non-Goals:** the site's renewal primitive; seller preemption; pooled funding; the
liability ledger; push delivery; the rest of the compute fulfillment unification;
periodic collection of a running deal's earnings by the seller.

## Decisions

### D1. The billing guarantee, and what ships before the service can keep it

The goal's guarantee is stated once, in one form: *charges after a deal's effective
end are reversed before they are collected.* The published payments contract cannot
keep it: a stop takes effect at receipt, releases the rate part's earned periods
toward the payee's withdrawable balance, and offers no command that returns released
funds to the payer, so a storefront that learns of an end late — or crashes between
a stop and its correction — cannot guarantee the correction lands before collection,
and a cooperative double that never collects in that gap would hide it.

So the guarantee depends on two service capabilities, required and recorded in
`settle-ongoing-compute-through-arkhai-payments`' requests: a payee stop carrying its
own effective time, with `settled` computed to it; and a correction entitlement after
a stop — a refund of released, unwithdrawn funds up to `settled` within a stated
horizon — for evidence that arrives later. Until both land, this change is built and
closed out in full, and the composition **does not declare per-period servicing**:
the publication gate (`negotiate-open-ended-compute-terms` D9) stays closed, no
per-period listing exists, and the feature is dark. The declaration carries a stated
reason, the roadmap row says what turns it on, and the closeout records the collection
scenarios as unrun behind an explicit external blocker. A follow-on re-vendors the
contract, adds the two calls to the kit, turns the hostile collection scenario from
failing to passing, and declares servicing; nothing else changes. Meanwhile the
mechanism does what the contract allows and the design records it as such: stop at
once on learning of an end, reverse what is still held, and journal the shortfall.

*Rejected:* shipping an interim per-period product under a narrowed guarantee — an
exposure bounded only by the buyer's vigilance, and a wording that would have to be
narrowed and later re-widened. *Rejected:* blocking the whole change on the service —
the integration work would wait idle against four moving changes. *Rejected:* keeping
the strong wording over the weak mechanism.

### D2. Per-deal continuation state, two work queues, and one continuation

Every per-period deal has a **continuation state record** from approval, keyed by
negotiation ID: the transaction ID; the stored evidence of approval (the receipt,
replaced by a verified snapshot on re-anchor, D8); the delivery state (D3); the last
verified event sequence and `observedAt`; the trusted `fundedThrough`; the financial
operation journal (D5); and its retention, under the request log's rule
(`buyer-initiated-compute-termination` D4): pruned once the deal is terminal and every
operation resolved, the current row kept with the deal.

The continuation lives in `kit/arkhai-payments`' seller stage, runs as a storefront
lifecycle loop on the kit loop controller, and depends on nothing of the compute
domains or the provisioning service; the compute-family delivery path (D3) supplies
the lease handle, the delivery predicate, and the teardown hook as injected,
mechanism-neutral operations. Each cycle, per deal, it runs **two queues in order**,
so physical work never waits on payments:

1. **Physical.** Every due decision in the request log — a recorded cancel, a
   preemption whose instant has passed, a site event — is terminated at the site if
   not already, and the lease is read for evidence. No payments call is in this
   path, and a failure in it does not skip the other queue.
2. **Financial.** Verify the current snapshot (`settle-ongoing-compute-through-arkhai-payments`
   D4) against the record's transaction, evidence, sequence, and `observedAt`. A
   snapshot that cannot be fetched or verified skips this queue for the deal — it
   renews nothing, starts nothing, and derives no new financial fact; the site's
   lapse policy decides what an unrenewed lease does. A verified snapshot showing a
   stop, or in the active state a `fundedThrough` not ahead of now, is a verified
   end: append the request and run the physical queue for it now. Otherwise, in the
   active state, renew the lease to `fundedThrough`, capped by the agreed end; then
   run every pending journal operation (D5).

Incomplete financial work stays runnable after the physical end is final. On restart
the loop recomputes every deal from its record, its decision log, and its verified
snapshot, issuing nothing already in the events. The polling cadence plus the
domain's teardown time must fit inside the option's `reserve_ahead`; the storefront
refuses to publish a per-period option whose `reserve_ahead` is shorter than that
floor, derived from real provisioning and teardown latency plus polling, transport,
and clock tolerance, never from the mock profile.

*Rejected:* one pass with the lease read moved first — a throw mid-pass skips the
rest, and independence should be structural. *Rejected:* a continuation over
delivered deals only; the sequence mark on the decision row.

### D3. One compute-family delivery path, and its state machine

The protected transitions — committing the hold, dispatching the create, and making
the service available — and the activation of every lease after delivery become one
compute-family delivery path both domains compose, in place of VM's and bare metal's
separate code; each domain keeps only its provider-specific preparation and its
access surface. This is the narrow part of the unification
`kit-owned-listing-and-fulfillment-lifecycles` proposes, taken here because the gate
needs it; that change absorbs the rest.

**The window.** The path derives the lease window from the accepted Agreement —
`lease_start_utc = start_utc`, `lease_end_utc = start_utc + duration_seconds` — in
both domains, commits against that absolute end, and commits the same window on
resume or retry, which the site's repeated-commit rule returns unchanged. When
settlement completes so late that no window remains, the path refuses delivery and
takes the undelivered path. Bare metal's commit from `now` is retired: a slow
settlement shortens served time rather than shifting the end past the seller's bound.

**The authorization.** The kit exposes `authorize_delivery(deal, phase)` for the
phases `commit`, `dispatch`, and `disclose`. It reads the continuation state and,
where the phase needs one, the current verified snapshot; applies the gate rule;
records the decision durably *before* answering; and at `disclose` drives the state
machine below. The gate rule by phase: before `start` (`commit`, `dispatch`), the
verified snapshot shows no `stop` and its embedded receipt shows the rate part's
first batch reserved to cover `reserve_ahead` — `fundedThrough` is not consulted; at
`disclose`, the same. The path calls it before each transition and keeps the
transition.

**The state machine.** The final transition spans three authorities and cannot be
one transaction, so the continuation state records a delivery state, each step
written before the effect it precedes and advanced by the acknowledgement it waits
for, with a recovery obligation per boundary:

| State | Written when | Recovery |
|---|---|---|
| `authorized` | the `disclose` gate passed; nothing external yet | re-run the gate; a stop seen now takes the undelivered path |
| `start_sent` | the `start` operation's identity journaled, the call made | read the events: the start present advances; absent, resend under the same identity. A `start` the *payer* issued is accepted as the start and recorded as such — the invariant is that every start the storefront *acts on* has a recorded authorization, not that every start was ours |
| `started` | billing runs; the lease is in its provisioning phase | activate the lease; if the site answers that it expired, this is the started-but-undelivered case: stop, and correct from the start instant — the buyer was billed for nothing |
| `activated` | the lease is on its funded horizon | publish availability |
| `available` | the durable transition: credentials retrievable, the deal served — written by the storefront when delivery is verified, independent of any buyer read | advance |
| `active` | the continuation's steady state | — |

The acceptance test is a crash injected between each adjacent pair followed by a
restart, in both domains, with the double. A deal found stopped before delivery
takes the undelivered path: refuse access; release the hold where nothing was
dispatched, else terminate; `stop` and `reverse` the reserved batch, with the minimum
spend, where one exists, following its committed refund rule. A seller issuing
`start` before the fulfillment is active is refused by the machine's own ordering.

*Rejected:* ordering the effects so `start` is last — a buyer with access and no
`start` is served free until recovery. *Rejected:* making `start` the buyer's — it
hands the seller's revenue to the buyer's client. *Rejected:* gating inside the
polling continuation; routing the transitions through the kit as hooks; one gate at
delivery start only; scoping the payer's stop authority by phase.

### D4. What the access guarantee says

Four guarantees, each enforceable by the party that holds it:

1. **No disclosure after a locally committed end.** The credential read route
   enforces the recorded delivery state and decision on every read — never a live
   snapshot — serialized with local termination by the decision row's
   compare-and-set. Absolute, and local.
2. **A remote stop is incorporated within one continuation interval while the
   storefront is healthy.** The window between a payer's stop at the service and
   the storefront's observation of it is bounded by the polling cadence, which
   `reserve_ahead` bounds; a disclosure inside it is served on funds the service had
   reserved, and the stop ends it at the next cycle.
3. **When the storefront is not healthy, the site's renewal deadline bounds physical
   service** under `reclaim`, and the operator's chosen exposure under `grace` or
   `continue`.
4. **After any end, physical termination is the revocation.** A credential already
   disclosed is made useless by tearing the resource down, never by refusing reads;
   the end-deal path terminates whether or not credentials were ever read.

The tests inject a remote stop between `start` and disclosure and between disclosure
and the next cycle, and assert the bound. *Rejected:* an absolute "no access after an
authoritative stop" — no pair of authorities can provide it. *Rejected:* a snapshot
fetch on every read — a smaller number, not a different guarantee, and a payments
dependency on the physical path.

### D5. Corrections: a financial operation journal with a cumulative target

The financial convergence of a decision is a **target** — a pure function of the
stopped snapshot's `settled` and the decision's financial effective end — and a
**journal** of operations, each immutable once written: kind (`start`, `stop`,
`reverse`), part, amount, its own request identity, and outcome `pending |
confirmed | refused`. A new operation is issued only when every earlier one is
resolved, for the delta between the target and the confirmed sum, and is written
before the external call so a retry resends the same amount under the same identity.
An unresolved operation is resolved first from the snapshot — `PartSnapshot.reversed`
and the events say whether it landed. Whole refunds and dispute reversals the
storefront did not issue count toward the target, never beyond it. When the
financial effective end moves earlier on authenticated evidence
(`buyer-initiated-compute-termination` D4), the target rises and the next delta is
issued the same way; it never moves later.

The arithmetic: the service interval is half-open, `[start, end)`; period *k* spans
`[start + k·period, start + (k+1)·period)` and is charged iff its start is before
`end`; the excess is every charged period whose start is at or after `end`; with no
`start` ever issued the target is the whole reserved batch; the minimum spend, once it
exists, follows its refund rule outside the target. The buyer-facing surfaces say the
period in which an end falls is charged in full.

Under D1 the journal runs against the double for everything but collection, where it
reports a refused operation until the service delivers. *Rejected:* one correction
under a fresh key each time evidence moves — a lost acknowledgement plus earlier
evidence pays the buyer twice. *Rejected:* the first correction final and later
evidence to dispute.

### D6. Stopping payment first is safe for the buyer; reclaiming first for the seller; neither is required

Each party holds one lever it can pull without anyone's cooperation, and the
storefront reconciles whichever came first:

- The **buyer's** cancel attempts the payer stop at the payments service first — the
  mandate names the payer as a stop authority, and that stop is authoritative the
  moment the service records it — and then calls the end-deal route *whether or not
  the first step succeeded*. The route records the request and terminates the lease
  while the payments service is unreachable; the decision's financial convergence
  issues the stop when the service returns, as the payee if the payer's never
  appears. A buyer who never calls the storefront is still not paying, and the
  continuation terminates within a polling interval.
- The **site** reports its intent to reclaim the moment it forms it, to the
  storefront only, durably. The storefront runs D5 at the reported instant.
- The **seller** ends billing through the storefront, which also terminates the
  lease; if the storefront is unreachable, through the operator stop command (D7).

A storefront that keeps billing after the site reclaimed, or never corrects, is
answered by the buyer's own stop and a dispute against the payments service's event
record and the signed site events an honest storefront retains. A site that is a
separate business from the storefront is the seller's responsibility to the buyer.

### D7. The seller's stop lever works with the storefront process down

An operator command (`market-storefront settlement stop <negotiation>`, name to be
settled) reads the mandate and transaction ID from the storefront's stored
`settlement_data` and issues the payee stop with the operator's credential, without
the running process, journaled by the identity it records if it can and reconciled by
the continuation on return if it cannot.

### D8. Identity rotation re-anchors running deals

The configuration lists a retiring service identity beside the current one with its
retirement date. During the overlap a stored receipt signed by the retiring key still
re-verifies and a fresh snapshot signed by the new key verifies, so nothing drains.
A running deal re-anchors on the first snapshot it verifies under the new key, stored
in the continuation state as its evidence of approval; system status reports deals
not yet re-anchored; when none remain the retiring identity is removed, and only
stragglers are drained. `livemode` cannot be re-anchored. A seller credential is read
at each call; an unavailable one is "cannot verify" and renews nothing. The
acceptance scenario is one deal running across a rotation window in the double.

### D9. Declaring servicing, and the startup rule

Composing the continuation *and* the service capabilities of D1 being vendored is
what declares per-period servicing in the payments registration, and so what turns
per-period publication on (`negotiate-open-ended-compute-terms` D9); the declaration
carries its reason. Disabling new publication is withdrawing the declaration; it is
not removing the continuation. A storefront that holds accepted per-period deals and
starts without the continuation composed refuses to start, under the existing rule
that a service refuses its own incoherent state and never a dependency. A tree with
the continuation composed and servicing undeclared starts, services nothing new, and
publishes nothing per-period — D1's dark posture.

## Accepted limitations and gaps (recorded in the goal)

- **Provisioning churn.** Until the minimum spend exists, a buyer who provisions and
  cancels before `start` pays nothing for the seller's provisioning. An explicit
  product decision; a scenario provisions, cancels before `start`, and asserts the
  buyer was charged nothing, labelled as the accepted risk, so it is never reported as
  mitigated.
- **Seller cash.** Under `{until: stop}` the payee collects nothing until the deal
  stops; a months-long lease pays the seller at its end. Accepted for this goal;
  periodic collection of earned periods is a request to the service, unowned here.
- **Pooled funding**, the **storefront–site liability ledger**, and **push delivery**.

## Open questions

- The continuation's default cadence and the `reserve_ahead` floor each domain passes
  the kit; settled in design from measured real latencies with a stated margin.
- Whether the operator stop command and the buyer's cancel share one kit operation
  for their financial convergence; settled in design.
- Where the continuation state, the journal, and the decision log live — core's
  common schema or each domain's persistence — is one answer for all, under the
  `kit-owned-storefront-auth-and-persistence` boundary; settled in
  `buyer-initiated-compute-termination`'s design session.
- The home of the compute-family delivery path: the family kit, or `kit/fulfillment`
  if it proves family-neutral; settled in design.

## Implementation cadence (recommended)

Three rounds. Round 1: the compute-family delivery path with the window derivation,
the authorization interface, the delivery state machine, both domains composed onto
it, the credential read enforcing the recorded state, and activation of every lease
after delivery. Round 2: the kit continuation with its state record, the two queues,
the journal, the restart recomputation, the operator stop command, the rotation
overlap, and the startup rule. Round 3: the buyer's cancel with its fallback and the
end-to-end scenarios in both lanes — the crash matrix, the remote-stop windows,
collection between stop and correction (failing until the service delivers), lost
acknowledgements followed by earlier evidence, payment outage during physical
recovery, delayed settlement against an absolute bound, the churn scenario, and the
rotation window. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1 | `openspec/specs/settlement-servicing/spec.md` and architecture companion; `ROADMAP.md` Goal 8 (the dependency and what turns the product on) |
| D2 | `settlement-servicing` spec and architecture companion; `market-composition` spec (the loop) |
| D3 | `settlement-servicing` spec; `fulfillment` spec and architecture companion (the delivery path and its state machine); `vm-storefront-fulfillment` spec; `ARCHITECTURE.md`, "Fulfillment" |
| D4 | `settlement-servicing` spec; `ARCHITECTURE.md`, "Deciding which party is authoritative" |
| D5 | `settlement-servicing` spec and architecture companion |
| D6 | `ARCHITECTURE.md`, "Deciding which party is authoritative"; `settlement-servicing` architecture companion; `buyer-orchestration` spec |
| D7 | `settlement-servicing` spec; the storefront operator CLI reference |
| D8 | `settlement-servicing` spec; `DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration and cutover" |
| D9 | `settlement-configuration` spec; `deployment-state` spec (the startup rule) |
