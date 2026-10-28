# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
revised the same day against three independent design reviews of the goal, and again
against a second review of the revision. This change's own design review may reopen
any of them with a finding; its design session verifies them against the code as its
four dependencies left it and adds the spec deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning, since every
dependency changes it.

- VM's `VmPaymentsCoordinator.start` verifies the approval receipt
  (`check_receipt_now`, which reads nothing of the snapshot's stop state), deposits,
  inserts the delivery, spawns `_provision`, which sets `ready` or `failed` and does
  nothing after; `list_unsettled_payment_negotiations` skips deals with a delivery
  record; `delivery_facts` records `lease_end_utc = start + duration` and
  `funding_expiration_unix = mandate.expires`. VM persists credentials into its
  delivery record, which the buyer's result read returns. Bare metal's
  `settle_payment` starts delivery once; its `fulfillment_service.py` commits and
  dispatches, and `/fulfillments/{negotiation_id}/access` and `/result` expose
  delivery independently; `reconcile_payments_once` converges `accepted`,
  `refunding`, and verified-without-lifecycle deals. Neither re-reads the transaction
  after delivery, and the two domains reach commit, dispatch, and disclosure through
  different code — the kind of divergence `ARCHITECTURE.md` says to resolve by
  choosing one behaviour and composing it.
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
- `kit-owned-listing-and-fulfillment-lifecycles` carries a proposed unified
  fulfillment path for the compute family — one start path, a layered evidence
  envelope, a verification contract, one access rule — not yet designed.

## Goals / Non-Goals

**Goals:** a per-period deal is served exactly while it is funded and wanted, with a
fail-safe on each side that needs no cooperation from the other; no access after an
authoritative stop; both compute domains get it through one implementation and one
delivery path; running deals survive a service-identity rotation; billing is
corrected to the earliest authenticated end.

**Non-Goals:** the site's renewal primitive; seller preemption; pooled funding; the
liability ledger; push delivery; the rest of the compute fulfillment unification.

## Decisions

### D1. Per-deal continuation state, and one continuation over every approved deal

Every per-period deal has a **continuation state record** from approval, keyed by
negotiation ID, in the storefront's persistence: the transaction ID; the stored
evidence of approval (the receipt, replaced by a verified snapshot on re-anchor, D7);
the phase — `pre_start`, `active`, `ended`; whether `start` has been issued; the last
verified event sequence (the replay high-water mark); the trusted `fundedThrough`;
and the last delivery authorization decision (D2). It exists whether or not anything
has requested an end; the decision log references it. It is the first thing the
restart recomputation reads.

The continuation lives in `kit/arkhai-payments`' seller stage and runs as a storefront
lifecycle loop on the kit loop controller, over every approved deal that is not
terminal — from approval, through provisioning, through delivery, to the end. The kit
owns the snapshot reads, the authorization decisions, the renewals, the stops, the
corrections, and the restart recomputation, and depends on nothing of the compute
domains or the provisioning service: the compute-family delivery path (D2) supplies
the delivery predicate, the lease handle, and the teardown hook as injected,
mechanism-neutral operations.

Per cycle, per deal, in this order:

1. **Verify.** Fetch the snapshot and verify it under the kit's rules
   (`settle-ongoing-compute-through-arkhai-payments` D4) against the continuation
   state's transaction, evidence, and sequence. A snapshot that cannot be fetched or
   verified ends the cycle for this deal: renew nothing, terminate nothing, issue
   nothing; the site's lapse policy decides what an unrenewed lease does.
2. **Interpret.** A `stop` in the snapshot, or in phase `active` a `fundedThrough` not
   ahead of now, is a verified end: append a request to the deal's log with the
   stop's effective instant and its cause. In `pre_start`, an absent `fundedThrough`
   is expected and means nothing.
3. **Act.** On a verified end, terminate the lease at once through the terminate
   route and run the financial convergence (D4). Otherwise, in `active`, renew the
   lease to `fundedThrough`, capped by the agreed end; in `pre_start`, do nothing —
   the delivery path drives the transitions (D2), and the site's provisioning
   deadline bounds them.

On restart the loop recomputes every deal's state from its continuation record, its
verified snapshot, and its decision log, issuing nothing already in the events. The
polling cadence plus the domain's teardown time must fit inside the option's
`reserve_ahead`; the storefront refuses to publish a per-period option whose
`reserve_ahead` is shorter than that floor, derived from real provisioning and
teardown latency plus polling, transport, and clock tolerance, never from the mock
profile.

*Rejected:* a continuation over delivered deals only — the approval-to-delivery
window is where a payer stop and a historical receipt disagree. *Rejected:* keeping
the sequence high-water mark on the decision row, which a healthy deal does not have.

### D2. One compute-family delivery path, calling one delivery authorization

The three protected transitions — committing the hold, dispatching the create, and
disclosing credentials — and the activation of the lease after delivery become one
compute-family delivery path both domains compose, in place of VM's and bare metal's
separate code for them; each domain keeps only its provider-specific preparation and
its access surface. This is the narrow part of the unification
`kit-owned-listing-and-fulfillment-lifecycles` proposes, taken here because the gate
needs it; that change absorbs the rest and is noted as doing so.

The kit exposes `authorize_delivery(deal, phase)` for the phases `commit`,
`dispatch`, and `disclose`. It reads the continuation state and, where the phase
needs one, the current verified snapshot, applies the gate rule, records the decision
durably in the continuation state *before* answering, and at `disclose` issues
`start` on success — so every accepted `start` corresponds to a recorded delivery
authorization. The gate rule by phase:

- before `start` (`commit`, `dispatch`): the verified snapshot shows no `stop`, and
  its embedded receipt shows the rate part's first batch reserved to cover
  `reserve_ahead`; `fundedThrough` is not consulted;
- at `disclose`: the same, then `start`, with the service's refusal of `start` on a
  stopped transaction as the final check; the lease is activated to the first
  verified horizon (`renewable-compute-lease-deadlines` D1) — a reserved deal's
  delivery path activates to its agreed end at the same point, through the same call.

The delivery path calls it before each transition and keeps the transition. The
credential read route enforces the *recorded* decision on every read — a deal whose
last decision is refused, or whose decision log holds a final physical end, answers
as an unverified deal answers today — never a live snapshot, so the read is
serialized with local termination by the decision row's compare-and-set, as refund
intent is. Two invariants the acceptance tests exercise, per domain with a fake
authorization port: *no access is granted after an authoritative stop*, and *every
accepted `start` corresponds to a durable delivery authorization decision*.

A deal found stopped before delivery takes the undelivered path: refuse access;
release the hold where nothing was dispatched, else terminate (the site's release
decision already distinguishes them); then `stop` and `reverse` the reserved batch,
with the minimum spend, where one exists, following its committed refund rule. A deal
found stopped during provisioning takes the same path once the create settles. A
seller treating approval as delivery — issuing `start` before the fulfillment is
active — is refused by the gate's own ordering.

*Rejected:* gating inside the polling continuation — a loop that only inspects status
cannot stop a route it does not own from answering, and a fresh snapshot in the loop
is not atomic with a read on another request. *Rejected:* routing the transitions
through the kit as hooks — it makes the kit own a compute fulfillment lifecycle it
must not know. *Rejected:* one gate at delivery start only — it leaves the whole
provisioning window open. *Rejected:* scoping the payer's stop authority by phase —
not expressible, and it would leave a buyer whose seller never delivers unable to end
the reservation of their own funds.

### D3. The site's lease-ended event, the lapse policy, and the division of labour

The storefront renews only on *verified* funding and terminates on a *verified* end,
so a lapse the site sees is only ever the unverifiable case — the payments service
unreachable, or the storefront itself down. Under the site's `continue` policy an
exhausted buyer is still cut off, because exhaustion is verified and terminated by the
storefront, whenever the storefront runs; while it does not, `continue` is the
operator's accepted credit risk. What the storefront does with the site's
`lease_ended` event is D4; what the site does with a lapse is
`renewable-compute-lease-deadlines` D4.

### D4. Billing ends with the lease: stop first, then reverse the excess the stop fixed

On every verified end of its own and on every `lease_ended` event — expiry at the
agreed end, a lapsed deadline, termination, force-release — the storefront runs the
financial convergence of the decision: issue the stop, keyed by the decision, unless
the events already hold one; then compute, from the stopped snapshot's `settled` and
the decision's *financial effective end*, the periods started strictly after that
end at the per-period charge, and reverse them on the rate part, keyed by the
decision and the evidence. The stop freezes the amount, so the excess is a pure
function of two durable facts and any retry recomputes the same number; there is no
window in which it can grow. The period in which the end falls is charged in full,
since billing is per started period, and the buyer-facing surfaces say so.

When the financial effective end later moves earlier on authenticated evidence
(`buyer-initiated-compute-termination` D4) — a site event that arrives after a local
termination, a payer stop seen late — the convergence re-runs from the new instant
and reverses the additional excess; it never moves later. The guarantee: *charges
after a deal's effective end are reversed before they are collected.* The one
contract confirmation it rests on, and the fallback if it fails, are
`settle-ongoing-compute-through-arkhai-payments` D5's.

The pull path is the lease read the storefront already has: every cycle reads each
live deal's lease state, so a lost event costs one polling interval, never the deal.

*Rejected:* reverse-then-stop — the window between the last reversal and the stop
always admits one more started period, and a crash between them leaves an excess that
keeps growing. *Rejected:* relying on payee backdating — not in the contract.
*Rejected:* ending billing at receipt and leaving the rest to dispute.

### D5. Stopping payment first is safe for the buyer; reclaiming first for the seller; neither is required

Each party holds one lever it can pull without anyone's cooperation, and the
storefront reconciles whichever came first:

- The **buyer's** cancel attempts the payer stop at the payments service first — the
  mandate names the payer as a stop authority, and that stop is authoritative the
  moment the service records it — and then calls the end-deal route *whether or not
  the first step succeeded*. The route records the request and terminates the lease
  while the payments service is unreachable; the decision's financial convergence
  issues the stop when the service returns, as the payee if the payer's never
  appears, which ends billing the same way and harms nobody. A buyer who never calls
  the storefront is still not paying, and the continuation terminates within a
  polling interval.
- The **site** reports its intent to reclaim the moment it forms it, to the
  storefront only (it knows no mechanism and holds no credential), durably. The
  storefront runs D4 at the reported instant.
- The **seller** ends billing through the storefront, which also terminates the
  lease; if the storefront is unreachable, through the operator stop command (D6),
  which stops charging without stopping service and so harms nobody but the seller.

A storefront that keeps billing after the site reclaimed, or never corrects, is
answered by the buyer's own stop and a dispute against the payments service's event
record and the signed site events an honest storefront retains. A site that is a
separate business from the storefront is the seller's responsibility to the buyer, as
a subcontractor is; the Agreement binds the seller principal.

*Rejected:* the payer stop as a prerequisite of the storefront route — an outage of
the payments service would then refuse a cancellation the lease authority is healthy
to honour.

### D6. The seller's stop lever works with the storefront process down

An operator command (`market-storefront settlement stop <negotiation>`, name to be
settled) reads the mandate and transaction ID from the storefront's stored
`settlement_data` and issues the payee stop with the operator's credential, without
the running process, keyed by a decision it appends to the log if it can and the
continuation reconciles on return if it cannot. The site's event is likewise durable
while the storefront is down.

### D7. Identity rotation re-anchors running deals

The configuration lists a retiring service identity beside the current one with its
retirement date. During the overlap a stored receipt signed by the retiring key still
re-verifies and a fresh snapshot signed by the new key verifies, so nothing drains.
A running deal re-anchors on the first snapshot it verifies under the new key: that
snapshot, stored in the continuation state as the deal's evidence of approval in
place of the bare receipt, vouches for the embedded receipt, and the deal needs the
retiring key for nothing after. System status reports deals not yet re-anchored; when
none remain the retiring identity is removed, and only stragglers are drained.
`livemode` cannot be re-anchored, so a mode change stays the drain the runbook
describes. A seller credential is read at each call; an unavailable one is "cannot
verify" and renews nothing. The acceptance scenario is one deal running across a
rotation window in the double.

### D8. The composition declares servicing

Composing the continuation is what declares per-period servicing in the payments
registration, and so what turns per-period publication on
(`negotiate-open-ended-compute-terms` D9). A storefront that stops composing it stops
publishing per-period options and keeps servicing its accepted per-period deals.

## Accepted gaps (recorded in the goal as unowned)

- **Pooled funding** and the lease pool that would renew N leases once.
- **Storefront–site liability**: what the storefront owes the site, with penalties
  for failing to relay a stop; the `continue` lapse policy is where it attaches.
- **A payee stop with its own effective time**, which would remove D4's reversal; the
  payments service's.

## Open questions

- The continuation's default cadence and the `reserve_ahead` floor each domain passes
  the kit; settled in design from each domain's measured real provisioning and
  teardown latency with a stated margin.
- Whether the operator stop command and the buyer's cancel share one kit operation
  for their financial convergence; settled in design.
- Where the continuation state and the decision log live — core's common schema or
  each domain's persistence — is one answer for both, under the
  `kit-owned-storefront-auth-and-persistence` boundary; settled in
  `buyer-initiated-compute-termination`'s design session.

## Implementation cadence (recommended)

Three rounds. Round 1: the compute-family delivery path with the authorization
interface, both domains composed onto it, the credential read enforcing the recorded
decision, and activation of every lease after delivery. Round 2: the kit continuation
with its state record, the financial convergence, the restart recomputation, the
servicing capability, the operator stop command, and the rotation overlap. Round 3:
the buyer's cancel with its fallback and the end-to-end scenarios in both lanes,
hostile cases included. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1 | `openspec/specs/settlement-servicing/spec.md` and architecture companion; `market-composition` spec (the loop) |
| D2 | `settlement-servicing` spec; `fulfillment` spec and architecture companion (the compute-family delivery path); `vm-storefront-fulfillment` spec; `ARCHITECTURE.md`, "Fulfillment" |
| D3 | `settlement-servicing` architecture companion |
| D4 | `settlement-servicing` spec and architecture companion; `physical-provisioning` spec |
| D5 | `ARCHITECTURE.md`, "Deciding which party is authoritative"; `settlement-servicing` architecture companion; `buyer-orchestration` spec |
| D6 | `settlement-servicing` spec; the storefront operator CLI reference |
| D7 | `settlement-servicing` spec; `DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration and cutover" |
| D8 | `settlement-configuration` spec |
