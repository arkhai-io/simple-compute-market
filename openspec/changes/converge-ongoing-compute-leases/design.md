# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and revised the same day against four rounds of independent design review of the
goal. This change's own design review may reopen any of them with a finding; its
design session verifies them against the code as its dependencies left it and adds
the spec deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning, since every
dependency changes it.

- No storefront watches a transaction after approval: VM's `VmPaymentsCoordinator`
  verifies the approval receipt, spawns provisioning, and does nothing after; bare
  metal's and credits' reconciliation passes skip delivered deals. Refund is
  seller-initiated `reverse`; nothing issues `start` or `stop`.
- The buyer's settle paths approve, poll, then call the storefront; the run log
  records `payment_approved` with the transaction ID. No buyer-side stop exists.
- The storefront operator CLIs read the storefront's configuration and database
  directly; no command issues a payment event.
- The payments contract: a rate part's hold is `{until: stop}`; `PartState` runs
  `held → released`; the payee has `PayoutBalance.withdrawable` and
  `WithdrawalRequest`, reached through the service's own surface and not through the
  storefront; `reverse` reaches held funds only; `PartSnapshot.refunded` exists with
  no command behind it; `EventCommand` carries no effective time. So a stop releases
  a rate part's earned periods toward the payee's balance, where nothing in the
  published contract returns them to the payer, and nothing the storefront does can
  hold the payee's withdrawals.
- The delivery path, its hook, its state machine, and the undelivered path are
  [`unify-compute-delivery-path`](../unify-compute-delivery-path/)'s; the horizon,
  the operations, the refusal table, rotation, and the servicing declaration are
  [`settle-ongoing-compute-through-arkhai-payments`](../settle-ongoing-compute-through-arkhai-payments/)';
  the request log, its retention rule, and the `lease_ended` event are
  [`buyer-initiated-compute-termination`](../buyer-initiated-compute-termination/)'s.

## Goals / Non-Goals

**Goals:** a per-period deal is served exactly while it is funded and wanted, with a
fail-safe on each side that needs no cooperation from the other; physical
convergence never waits on payments; billing is corrected to the earliest
authenticated end, and money is conserved under lost acknowledgements; a deal leaves
the continuation only when it has converged both ways, and every gap is measured.

**Non-Goals:** the site's renewal primitive; the delivery path; seller preemption;
pooled funding; the liability ledger; push delivery; periodic collection of a running
deal's earnings by the seller.

## Decisions

### D1. The billing guarantee, the horizon, and what ships before the service has it

The goal's guarantee is stated once, in one form: *charges after a deal's effective
end are reversed before they are collected*, with one bounded residual stated beside
it on every buyer-facing surface: a buyer may be charged for at most the option's
`reserve_ahead` past an end the storefront did not observe. What keeps it is the
billing horizon (`settle-ongoing-compute-through-arkhai-payments` D5): the storefront
vouches for billing only as far ahead as it has verified the lease is alive and
wanted, and renews the site's lease to the same instant in the same cycle, so a dead
storefront's billing and lease lapse together and nothing accrues that it did not
vouch for while alive. The published contract lacks the horizon. Until the service
vendors it, this change is built and closed out in full against the double's
proposed contract, under a servicing declaration the lane profile alone may make
(`settle-ongoing-compute-through-arkhai-payments` D10); no production composition
declares servicing, so no per-period option is published, accepted, or materialized
anywhere; and the closeout records every per-period scenario as *qualification
against a proposed contract*. The follow-on
[`activate-per-period-compute-servicing`](../activate-per-period-compute-servicing/)
vendors the revision, re-verifies the double against it, declares servicing, and
turns the same scenarios into live evidence.

*Rejected:* shipping an interim per-period product under a narrowed guarantee — an
exposure bounded only by the buyer's vigilance. *Rejected:* blocking the whole
change on the service. *Rejected:* leaving the scenarios unrun until the service
lands — every integration defect would then be found by the one change that is also
absorbing a new schema. *Rejected:* the earlier two required capabilities, an
effective-time payee stop and a post-stop refund entitlement — the refund cannot
reach funds the payee has withdrawn, so the guarantee still needed a hold or a
narrowed scope; the horizon makes the storefront's silence end billing instead of
prolonging it.

### D2. Per-deal continuation state, two completion facts, two queues, one continuation

Every per-period deal has a **continuation state record** from approval, keyed by
negotiation ID: the transaction ID; the stored evidence of approval (the receipt,
replaced by a verified snapshot on re-anchor); the delivery state
(`unify-compute-delivery-path` D4); the last verified event sequence and
`observedAt`; the trusted `fundedThrough`; the instant last vouched and the instant
last renewed to, each written before its call; the financial operation journal (D5);
and two **completion facts**, written by the transitions that earn them, idempotent,
never recomputed from lease state:

- *physical completion* — written by the physical queue when the site's
  `lease_ended` for the lease is recorded, which the site's deadline guarantees
  eventually, by `renewal_lapsed` at the latest, since the storefront stops renewing
  a deal whose billing has ended; or when the operator closes it by hand through the
  stop command (D7) with a reason;
- *financial completion* — written by the financial queue when the stop is
  acknowledged, the amount returned equals the target, and no journal operation is
  pending.

The continuation selects `approved AND NOT (physical AND financial)`; each queue
skips once its own fact is set. The gap between the two is the diagnostic: *financial
without physical* past a threshold is the teardown-failure exposure, the seller's
cost, bounded by the lease deadline and reported; *physical without financial* is a
correction still owed, the buyer's, bounded by `reserve_ahead` and reported.
Retention for the record starts when both are set
(`buyer-initiated-compute-termination` D4).

The continuation lives in `kit/arkhai-payments`' seller stage, runs as a storefront
lifecycle loop on the kit loop controller, and depends on nothing of the compute
domains or the provisioning service; the delivery path supplies the lease handle,
the delivery predicate, and the teardown hook as injected, mechanism-neutral
operations. Each cycle, per deal, it runs **two queues in order**, so physical work
never waits on payments:

1. **Physical.** Every due decision in the request log — a recorded cancel, a
   preemption whose instant has passed, a site event — is terminated at the site if
   not already, and the lease is read for evidence. No payments call is in this
   path, and a failure in it does not skip the other queue.
2. **Financial.** Verify the current snapshot (`settle-ongoing-compute-through-arkhai-payments`
   D4) against the record's transaction, evidence, sequence, and `observedAt`. A
   snapshot that cannot be fetched or verified skips this queue for the deal — it
   vouches nothing, renews nothing, starts nothing, and derives no new financial
   fact; the site's lapse policy decides what an unrenewed lease does. A verified
   snapshot showing a stop, or in the active state a `fundedThrough` not ahead of
   now, is a verified end: append the request and run the physical queue for it
   now. Otherwise, in the active state, vouch and renew to the earliest of now plus
   `reserve_ahead`, `fundedThrough`, and the agreed end, in that order with each
   instant recorded first; then run every pending journal operation (D5).

On restart the loop recomputes every deal from its record, its decision log, and its
verified snapshot, issuing nothing already in the events. The polling cadence plus the
domain's teardown time must fit inside the option's `reserve_ahead`; the storefront
refuses to publish a per-period option whose `reserve_ahead` is shorter than that
floor, derived from real provisioning and teardown latency plus polling, transport,
and clock tolerance, never from the mock profile.

*Rejected:* one pass with the lease read moved first — a throw mid-pass skips the
rest, and independence should be structural. *Rejected:* reading "terminal" from
lease or deal state — a deal whose lease has ended but whose journal still holds a
`refund` marked `unsupported` would leave the selection and never drain. *Rejected:*
one completion fact — the teardown-failure exposure would be neither bounded nor
visible. *Rejected:* recomputing convergence each cycle with no stored fact — a
change to how lease state is read would silently change which deals are served.

### D3. The hook's per-period implementation

`unify-compute-delivery-path` D3's `authorize_delivery(deal, phase)` is implemented
here for per-period deals. Before `start` (`commit`, `dispatch`): the verified
snapshot shows no `stop` and its embedded receipt shows the rate part's first batch
reserved to cover `reserve_ahead` — `fundedThrough` is not consulted. At `start`: the
same, then the mechanism's `start` is journaled with the delivery evidence the path
hands it and issued; `start` is the payee's alone, so the state machine has one
issuer and `started` is reached only from `dispatched`. At `disclose`: the same
checks, and the recorded delivery state. A refusal at any phase takes the path's
undelivered route, which for a per-period deal is this hook's stop and the return of
the reserved batch, the minimum spend following its committed refund rule; the
started-but-undelivered case — the site answering at activation that the lease
expired — is stopped and corrected from the `start` instant, since the buyer was
billed for nothing.

*Rejected:* a payer-issued `start` accepted as the deal's
(`settle-ongoing-compute-through-arkhai-payments` D2).

### D4. What the access guarantee says

Four guarantees, each enforceable by the party that holds it:

1. **No disclosure after a locally committed end.** The credential read route
   enforces the recorded delivery state and decision on every read — never a live
   snapshot — serialized with local termination by the decision row's
   compare-and-set. Absolute, and local; the delivery path's
   (`unify-compute-delivery-path` D6).
2. **A remote stop is incorporated within one continuation interval while the
   storefront is healthy.** The window between a payer's stop at the service and
   the storefront's observation of it is bounded by the polling cadence, which
   `reserve_ahead` bounds; a disclosure inside it is served on funds the service had
   reserved, and the stop ends it at the next cycle.
3. **When the storefront is not healthy, the site's deadline bounds physical
   service** under `reclaim`, and the operator's chosen exposure under `grace` or
   `continue`; and the horizon bounds billing to the same instant.
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
`reverse`, `refund`), part, amount, its own request identity, and outcome `pending |
confirmed | unsupported | refused`. A new operation is issued only when every earlier
one is resolved, for the delta between the target and the amount returned, which is
the snapshot's `reversed + refunded` — `reverse` lands in `reversed` while the part is
held, `refund` in `refunded` after release, and that is how the two fields reconcile.
Each operation is written before the external call so a retry resends the same amount
under the same identity; an unresolved operation is resolved first from the snapshot
and the events. Whole refunds and dispute reversals the storefront did not issue count
toward the target, never beyond it. When the financial effective end moves earlier on
authenticated evidence (`buyer-initiated-compute-termination` D4), the target rises
and the next delta is issued the same way; it never moves later.

**Order.** Reverse before stop, always (`settle-ongoing-compute-through-arkhai-payments`
D5); the horizon is what makes a crash between the two bounded. A correction that
becomes due after the stop is a `refund`, `unsupported` until the service provides
the command, retried every cycle and never terminal. Refusals are classified by the
kit's table; `unsupported` and the retry class are never surfaced as failures,
`refused` is surfaced to the operator.

**The arithmetic.** The service interval is half-open, `[start, end)`; period *k*
spans `[start + k·period, start + (k+1)·period)` and is charged iff its start is
before `end`; the excess is every charged period whose start is at or after `end`.
**The started period** — the one in which `end` falls — is charged in full for a
buyer-caused end, disclosed as such, and reversed for a seller-caused one: a
preemption, a site withdrawal, or a storefront termination for the seller's reasons,
read from the decision's cause, so a seller cannot time an end to the first second of
a period and collect it whole. With no `start` ever issued the target is the whole
reserved batch; the minimum spend, once it exists, follows its refund rule outside
the target.

*Rejected:* one correction under a fresh key each time evidence moves — a lost
acknowledgement plus earlier evidence pays the buyer twice. *Rejected:* the first
correction final and later evidence to dispute. *Rejected:* charging the started
period for seller-caused ends and disclosing it — disclosure does not remove the
incentive. *Recommendation left to `negotiate-open-ended-compute-terms`' session:*
prorating every end locally by reverse, buyer-caused included, which the service's
prorated final period would do without local arithmetic.

### D6. Stopping payment first is safe for the buyer; reclaiming first for the seller; neither is required

Each party holds one lever it can pull without anyone's cooperation, and the
storefront reconciles whichever came first:

- The **buyer's** cancel attempts the payer stop at the payments service first — the
  mandate names the payer as a stop authority, and that stop is authoritative the
  moment the service records it — and then calls the end-deal route *whether or not
  the first step succeeded*. The route records the request and terminates the lease
  while the payments service is unreachable; the decision's financial convergence
  reverses and stops when the service returns, as the payee if the payer's never
  appears. A buyer who never calls the storefront is still not paying, and the
  continuation terminates within a polling interval.
- The **site** reports its intent to reclaim the moment it forms it, to the
  storefront only, durably. The storefront runs D5 at the reported instant.
- The **seller** ends billing through the storefront, which also terminates the
  lease; if the storefront is unreachable, through the operator stop command (D7).

A storefront that keeps billing after the site reclaimed, or never corrects, is
answered by the buyer's own stop and a dispute against the payments service's event
record, the signed site event the buyer's status read returns, and the delivery
instants the buyer's client recorded
(`settle-ongoing-compute-through-arkhai-payments` D11). A site that is a separate
business from the storefront is the seller's responsibility to the buyer.

### D7. The seller's stop lever works with the storefront process down

An operator command (`market-storefront settlement stop <negotiation>`, name to be
settled) reads the mandate and transaction ID from the storefront's stored
`settlement_data` and issues the payee stop with the operator's credential, without
the running process, journaled by the identity it records if it can and reconciled by
the continuation on return if it cannot. The same command, with a reason, records
physical completion by hand for a deal whose site event will never come (D2).

### D8. Rotation is composed, not designed here

Identity rotation is `settle-ongoing-compute-through-arkhai-payments` D7's; the
continuation re-anchors a running deal on the first snapshot it verifies under the
new key and reports deals not yet re-anchored in system status. The acceptance
scenario — one deal running across a rotation window in the double — is this
change's to run.

### D9. Declaring servicing, and the startup rule

A production composition declares per-period servicing against the `published`
contract only once the horizon is vendored, which is the follow-on's act; the lane
profile declares it against the `proposed` contract, refused by startup in any other
configuration (`settle-ongoing-compute-through-arkhai-payments` D10). Disabling new
publication is withdrawing the declaration; it is not removing the continuation. A
storefront that holds accepted per-period deals and starts without the continuation
composed refuses to start, under the existing rule that a service refuses its own
incoherent state and never a dependency. A tree with the continuation composed and
servicing undeclared starts, services nothing new, and publishes, accepts, and
materializes nothing per-period — D1's dark posture, enforced at three doors
(`negotiate-open-ended-compute-terms` D9).

## Scenarios

Nine sequence diagrams, draw.io sources with SVG exports under
[`diagrams/`](diagrams/), one guarantee each; the decisions above cite them, and
`activate-per-period-compute-servicing`'s closeout promotes them to
`docs/development/diagrams/` beside the `settlement-servicing` architecture
companion. Lifelines: the buyer's client, the storefront (its physical and financial
queues as two activation bars), the site, the payments service.

| # | Scenario | Demonstrates |
|---|---|---|
| 0 | On-demand baseline: approve, commit, `start`, activate, disclose, vouch-and-renew cycles, buyer stop, reverse, stop, `lease_ended`, both completion facts | the normal path and where each fact is written |
| 1 | Buyer cancels with the payments service down | the end-deal route works alone; the payer stop lands later; no charge past the decision's physical end |
| 2 | Site withdraws while the storefront is dead | horizon lapse stops billing at *V*; late `lease_ended` at *E* on resume; `refund` journaled `unsupported`; excess ≤ `reserve_ahead` |
| 3 | Crash between `reverse` and `stop` | the horizon bounds the tail; resume finds the service's lapse-stop and the reverse acknowledged |
| 4 | Payer stop between `start` and disclosure | no disclosure after a committed end; teardown; charge from `start` to the stop only |
| 5 | Prepaid deal, activation deadline expires | site's `renewal_lapsed` in the awaiting-activation phase; full refund through the delivery path |
| 6 | Funds exhausted mid-lease | `fundedThrough` not advancing; vouch and renewal held; site lapse policy; stop at the funded horizon |
| 7 | Spot preemption with notice | scheduled stop at now + notice; started period reversed before the stop; a buyer cancel earlier supersedes |
| 8 | A `start` issued before delivery | the buyer's recorded delivery instants against the signed `start` event; the dispute path |

## Accepted limitations and gaps (recorded in the goal)

- **Provisioning churn on VM.** Until the minimum spend exists, a buyer who
  provisions and cancels before `start` pays nothing for the seller's provisioning.
  An explicit product decision; a scenario provisions, cancels before `start`, and
  asserts the buyer was charged nothing, labelled as the accepted risk, so it is never
  reported as mitigated. Bare metal publishes no per-period option without a minimum
  (`negotiate-open-ended-compute-terms` D13).
- **The bounded residual.** A buyer may be charged for at most `reserve_ahead` past
  an end the storefront did not observe (D1); the `refund` kind returns it once the
  service provides the command.
- **Teardown after billing stops.** Between a stop and the site's reclaim the seller
  serves unpaid; bounded by the lease deadline, measured as the gap between the two
  completion facts (D2), the seller's cost.
- **Seller cash.** Under `{until: stop}` the payee collects nothing until the deal
  stops; a months-long lease pays the seller at its end. Accepted for this goal;
  periodic collection of earned periods is a welcome request to the service.
- **Pooled funding**, the **storefront–site liability ledger**, and **push delivery**.

## Open questions

- The continuation's default cadence and the `reserve_ahead` floor each domain passes
  the kit; settled in design from measured real latencies with a stated margin.
- Whether the operator stop command and the buyer's cancel share one kit operation
  for their financial convergence; settled in design.
- The thresholds at which each completion gap is reported (D2); settled in design.

## Implementation cadence (recommended)

Two rounds. Round 1: the kit continuation with its state record and completion
facts, the two queues, vouch-and-renew, the hook's per-period implementation, the
journal with its order and arithmetic, the restart recomputation, the operator stop
command, and the startup rule. Round 2: the buyer's cancel with its fallback, the
buyer's evidence record, and the end-to-end scenarios in both lanes under the lane
profile's `proposed` declaration — the nine diagrams' scenarios, the remote-stop
windows, lost acknowledgements followed by earlier evidence, payment outage during
physical recovery, the churn scenario, and the rotation window — each recorded as
qualification against a proposed contract. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1 | `openspec/specs/settlement-servicing/spec.md` and architecture companion; `ROADMAP.md` Goal 8 (the dependency and what turns the product on) |
| D2 | `settlement-servicing` spec and architecture companion; `market-composition` spec (the loop) |
| D3 | `settlement-servicing` spec; `fulfillment` spec (the hook's per-period implementation) |
| D4 | `settlement-servicing` spec; `ARCHITECTURE.md`, "Deciding which party is authoritative" |
| D5 | `settlement-servicing` spec and architecture companion |
| D6 | `ARCHITECTURE.md`, "Deciding which party is authoritative"; `settlement-servicing` architecture companion; `buyer-orchestration` spec |
| D7 | `settlement-servicing` spec; the storefront operator CLI reference |
| D9 | `settlement-configuration` spec; `deployment-state` spec (the startup rule) |
| Scenarios | `docs/development/diagrams/`, cited from the `settlement-servicing` architecture companion |
