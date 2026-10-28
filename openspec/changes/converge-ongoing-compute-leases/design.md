# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and revised the same day against three independent design reviews of the goal. This
change's own design review may reopen any of them with a finding; its design session
verifies them against the code as its four dependencies left it and adds the spec
deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning, since every
dependency changes it.

- VM's `VmPaymentsCoordinator.start` verifies the approval receipt
  (`check_receipt_now`, which reads nothing of the snapshot's stop state), deposits,
  inserts the delivery, spawns `_provision`, which sets `ready` or `failed` and does
  nothing after; `list_unsettled_payment_negotiations` skips deals with a delivery
  record; `delivery_facts` records `lease_end_utc = start + duration` and
  `funding_expiration_unix = mandate.expires`. Bare metal's `settle_payment` starts
  delivery once; `reconcile_payments_once` converges `accepted`, `refunding`, and
  verified-without-lifecycle deals. Neither re-reads the transaction after delivery.
  Each storefront runs its own reconciliation timer on the kit loop controller.
- Delivery start and refund intent are ordered by single-statement compare-and-set
  writes in each domain's tables (`settlement-servicing` architecture, "Delivery
  start and refund intent are ordered"); credentials are fetched uncached from the
  provider at `GET /fulfillment/{id}/result` for an `active` fulfillment.
- Refund is seller-initiated `reverse`; nothing issues `start` or `stop`.
- The buyer's settle paths (`domains/vms/buyer/.../arkhai_payments.py`, bare metal's
  `PaymentStage.settle`) approve, poll, then call the storefront; the run log records
  `payment_approved` with the transaction ID. No buyer-side stop exists.
- The storefront operator CLIs read the storefront's configuration and database
  directly for `config` and `settlement status`; no command issues a payment event.
- A stored receipt is re-verified at restart against the current `service_identity`
  and `livemode`, which is why a rotation drains open deals today
  (`DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration and cutover").

## Goals / Non-Goals

**Goals:** a per-period deal is served exactly while it is funded and wanted, with a
fail-safe on each side that needs no cooperation from the other; no access after an
authoritative stop; both compute domains get it through one implementation; running
deals survive a service-identity rotation.

**Non-Goals:** the site's renewal primitive; seller preemption; pooled funding; the
liability ledger; push delivery.

## Decisions

### D1. One continuation in the mechanism kit, over every approved non-terminal deal

A per-period deal's continuation lives in `kit/arkhai-payments`' seller stage and
runs as a storefront lifecycle loop on the kit loop controller, so the end-to-end
stages can hold and step it. It covers every approved deal that is not terminal —
from approval, through provisioning, through delivery, to the end — not only
delivered ones. Each compute domain contributes its delivery predicate (the
fulfillment is active and credentials are retrievable), its lease handle (reservation
and site), and its teardown hook (terminate at the site), and nothing else; the kit
owns the snapshot reads, the gate, the renewals, the stops, the corrections, and the
restart recomputation, and depends on nothing of the compute domains or the
provisioning service — those arrive as injected, mechanism-neutral operations, per the
layer and scope rules.

Per cycle, per deal, in this order:

1. **Verify.** Fetch the snapshot and verify it under the kit's rules
   (`settle-ongoing-compute-through-arkhai-payments` D4): proof, binding to the
   transaction and mandate, parts, freshness, sequence against the high-water mark
   persisted in the decision row. A snapshot that cannot be fetched or verified ends
   the cycle for this deal: renew nothing, terminate nothing, issue nothing; the
   site's lapse policy decides what an unrenewed lease does.
2. **Interpret.** A `stop` in the snapshot, or a `fundedThrough` not ahead of now, is
   a verified end: append a request to the deal's log (`buyer_cancel`,
   `funding_ended`, `site_withdrawal`, `seller_preemption` by the stop's cause and
   what the log already holds), with the stop's effective instant.
3. **Act.** On a verified end, terminate the lease at once through the terminate
   route and run the financial convergence (D4). Otherwise, if delivery is verified
   and no `start` is in the events, run the delivery gate (D2) and issue `start`;
   then renew the lease to `fundedThrough`, capped by the agreed end.

On restart the loop recomputes every deal's state from its verified snapshot and its
decision log, issuing nothing already in the events. The polling cadence plus the
domain's teardown time must fit inside the option's `reserve_ahead`; the storefront
refuses to publish a per-period option whose `reserve_ahead` is shorter than that
floor, derived from real provisioning and teardown latency plus polling, transport,
and clock tolerance, never from the mock profile.

*Rejected:* a continuation over delivered deals only — the approval-to-delivery
window is where a payer stop and a historical receipt disagree.

### D2. The delivery authorization gate

Delivery is a gated transition. Before any protected effect — committing the hold,
dispatching the create, and again immediately before credentials become readable to
the buyer — the current verified snapshot must show no stop and funding ahead, and
the gate refuses if either fails. `start` is issued only inside the gate, after
delivery is verified and before credentials are exposed, with the service's refusal
of `start` on a stopped transaction (`transaction_stopped`) as the final check. Two
invariants the acceptance tests exercise: *no access is granted after an
authoritative stop*, and *every accepted `start` corresponds to a durable delivery
authorization decision*. The stop intent is serialized against delivery start by
compare-and-set, as refund intent already is.

A deal found stopped before delivery takes the undelivered path: refuse access;
release the hold where nothing was dispatched, else terminate (the site's release
decision already distinguishes them); then `stop` and `reverse` the reserved batch.
The minimum charge is reversed when the seller failed to deliver and kept when the
buyer stopped a provision in flight, at the seller's policy. A deal found stopped
during provisioning takes the same path once the create settles. A seller treating
approval as delivery — issuing `start` before the fulfillment is active — is refused
by the gate's own ordering, which is what protects the buyer from paying for
provisioning time.

*Rejected:* one gate at delivery start only — it leaves the whole provisioning
window, on bare metal the long one, in which a stop lands and the buyer still gets
access. *Rejected:* scoping the payer's stop authority by phase — not expressible in
the contract, and it would leave a buyer whose seller never delivers unable to end
the reservation of their own funds.

### D3. The site's lease-ended event, the lapse policy, and the division of labour

The storefront renews only on *verified* funding and terminates on a *verified* end,
so a lapse the site sees is only ever the unverifiable case — the payments service
unreachable, or the storefront itself down. Under the site's `continue` policy an
exhausted buyer is still cut off, because exhaustion is verified and terminated by the
storefront. What the storefront does with the site's `lease_ended` event is D4; what
the site does with a lapse is `renewable-compute-lease-deadlines` D4.

### D4. Billing ends with the lease, corrected inside the contract when learned late

On every `lease_ended` event — expiry at the agreed end, a lapsed deadline,
termination, force-release — and on every verified end of its own, the storefront
runs the financial convergence of the decision: compute the periods earned on the
rate part after the decision's effective instant from the verified snapshot's
`periodsEarned`, reverse them on the part, then issue the stop, each keyed by the
decision. If the events already hold a stop, only the reversal runs. The reversal is
recorded as done before the stop is issued, so a crash between them is recoverable
either way — if the service accepts a reverse after the stop the recovery re-issues
it, and if not, the record is what shows the reversal preceded the stop. The
guarantee: *charges after a deal's effective end are reversed before they are
collected.*

The pull path is the lease read the storefront already has: every cycle reads each
live deal's lease state, so a lost event costs one polling interval, never the deal.

*Rejected:* relying on payee backdating — not in the contract. *Rejected:* ending
billing at receipt and leaving the rest to dispute — it makes the buyer bear the
seller's outage.

### D5. Stopping payment first is always safe for the buyer; reclaiming first for the seller

Each party holds one lever it can pull without anyone's cooperation, and the
storefront reconciles whichever came first:

- The **buyer's** cancel stops the transaction at the payments service first — the
  mandate names the payer as a stop authority — then calls the end-deal route for
  prompt teardown. The payer stop is authoritative the moment the service records
  it; a buyer who never calls the storefront is still not paying, and the
  continuation terminates the lease within a polling interval.
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
snapshot, stored as the deal's evidence of approval in place of the bare receipt,
vouches for the embedded receipt, and the deal needs the retiring key for nothing
after. System status reports deals not yet re-anchored; when none remain the retiring
identity is removed, and only stragglers are drained. `livemode` cannot be
re-anchored, so a mode change stays the drain the runbook describes. A seller
credential is read at each call; an unavailable one is "cannot verify" and renews
nothing. The acceptance scenario is one deal running across a rotation window in
the double.

### D8. The composition declares servicing

Composing the continuation is what declares per-period servicing in the payments
registration, and so what turns per-period publication on
(`negotiate-open-ended-compute-terms` D9). A storefront that stops composing it stops
publishing per-period options and keeps servicing its accepted per-period deals.

## Accepted gaps (recorded in the goal as unowned)

- **Pooled funding** and the lease pool that would renew N leases once.
- **Storefront–site liability**: what the storefront owes the site, with penalties
  for failing to relay a stop; the `continue` lapse policy is where it attaches.
- **A payee stop with its own effective time**, which would make D4's reversal the
  fallback; the payments service's.

## Open questions

- The continuation's default cadence and the `reserve_ahead` floor each domain passes
  the kit; settled in design from each domain's measured real provisioning and
  teardown latency with a stated margin.
- Whether the operator stop command and the buyer's payer-stop-first cancel share one
  kit operation; settled in design.

## Implementation cadence (recommended)

Two rounds. Round 1: the kit continuation with the gate, the financial convergence,
the restart recomputation, the servicing capability, both domains' hooks, the
operator stop command, and the rotation overlap. Round 2: the buyer's payer-stop-first
cancel and the end-to-end scenarios in both lanes, hostile cases included. One
session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2 | `openspec/specs/settlement-servicing/spec.md` and architecture companion; `market-composition` spec (the loop) |
| D3 | `settlement-servicing` architecture companion |
| D4 | `settlement-servicing` spec and architecture companion; `physical-provisioning` spec |
| D5 | `ARCHITECTURE.md`, "Deciding which party is authoritative"; `settlement-servicing` architecture companion |
| D6 | `settlement-servicing` spec; the storefront operator CLI reference |
| D7 | `settlement-servicing` spec; `DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration and cutover" |
| D8 | `settlement-configuration` spec |
