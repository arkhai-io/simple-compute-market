# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and split out of `converge-ongoing-compute-leases` on the goal's fourth review round.
This change's own design review may reopen any of them with a finding; its design
session verifies them against the code as its two dependencies left it and adds the
spec deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning.

- VM's `VmPaymentsCoordinator.start` verifies the approval receipt
  (`check_receipt_now`, which reads nothing of the snapshot's stop state), deposits,
  inserts the delivery, spawns `_provision`, which sets `ready` or `failed` and does
  nothing after; `delivery_facts` records `lease_end_utc = start + duration` from the
  Agreement. VM persists credentials into its delivery record, which the buyer's
  result read returns. On resume, `fulfillment_resume_runtime.py:95` and `:264`
  substitute 3600 for a missing `duration_seconds`.
- Bare metal's `settle_payment` starts delivery once; its `fulfillment_service.py`
  commits `lease_start = now`, `lease_end = now + duration`, ignoring the Agreement's
  `start_utc`, and dispatches; `/fulfillments/{negotiation_id}/access` and `/result`
  expose delivery independently.
- Delivery start and refund intent are ordered by single-statement compare-and-set
  writes in each domain's tables; credentials are fetched uncached from the provider
  at `GET /fulfillment/{id}/result` for an `active` fulfillment.
- Refund is seller-initiated `reverse`, which the storefront already issues when a
  provision fails under its own hands.
- `kit-owned-listing-and-fulfillment-lifecycles` carries a proposed unified
  fulfillment path for the compute family, not yet designed; it records that this
  change takes the protected transitions, activation, and the access rule.

## Goals / Non-Goals

**Goals:** both compute domains deliver through one implementation with one window;
every lease is activated after delivery; a mechanism can refuse a transition before
it happens; a deal that is never delivered costs the buyer nothing; no credential is
disclosed after a locally committed end.

**Non-Goals:** the per-period hook implementation; the continuation; the site's
deadline.

## Decisions

### D1. The window comes from the Agreement, in both domains

The path derives the lease window from the accepted Agreement — `lease_start_utc =
start_utc`, `lease_end_utc = start_utc + duration_seconds` — commits against that
absolute end, and commits the same window on resume or retry, which the site's
repeated-commit rule returns unchanged. Bare metal's commit from `now` is retired,
and VM's two resume-time substitutions of an hour with it: a slow settlement shortens
served time rather than shifting the end past the seller's bound, which is what an
absolute `available_until_utc` requires. When settlement completes so late that no
window remains, the path refuses delivery and takes the undelivered path (D5). The
buyer is told what an absolute end means before approving
(`negotiate-open-ended-compute-terms` D12).

### D2. Every compute commit caller becomes an activation caller, once

After delivery the path activates the lease through the one call
`renewable-compute-lease-deadlines` adds — a reserved deal to its agreed end, a
per-period deal to the horizon the hook names — so VM's `_commit_capacity_hold` and
`_commit_fresh_reservation`, its resume path, bare metal's `fulfillment_service`, and
the Alkahest delivery paths are rewired here and nowhere else. Activation is
idempotent at the site, so a lost acknowledgement is retried under the same call.

### D3. A delivery authorization hook, with a default that does nothing

`authorize_delivery(deal, phase)` is called before each of `commit`, `dispatch`,
`start`, and `disclose`; it reads what it needs, applies its rule, records its
decision durably *before* answering, and the path keeps the transition. The path
supplies the interface and a default implementation that answers yes at once with
nothing to do — every prepaid deal's — and `converge-ongoing-compute-leases` supplies
the per-period one, which at `start` issues the mechanism's `start` with the delivery
evidence the path hands it. Callers walked: VM's and bare metal's delivery paths call
the hook through the path; the continuation implements it; the operator's status read
shows its recorded decisions; nothing else calls it. The hook's phases, its
decision record, and the evidence the path hands it at `start` — the commit
acknowledged, the dispatch begun — are the interface other changes import.

*Rejected:* gating inside the polling continuation; routing the transitions through
the kit as hooks; one gate at delivery start only.

### D4. The delivery state machine

The final transition spans three authorities and cannot be one transaction, so the
deal's delivery record carries a state, each step written before the effect it
precedes and advanced by the acknowledgement it waits for, with a recovery
obligation per boundary:

| State | Written when | Recovery |
|---|---|---|
| `authorized` | the `disclose` gate passed; nothing external yet | re-run the gate; a refusal now takes the undelivered path |
| `dispatched` | the create is dispatched | adopt the fulfillment the provider reports, or re-dispatch under the same identity |
| `started` | the hook's `start` phase answered — immediately for a prepaid deal; for a per-period deal once the mechanism's `start` is in the events | re-run the hook, which resolves its own operation from the events |
| `activated` | the site acknowledged activation | re-activate, idempotent; a site answering that the lease expired is the started-but-undelivered case, handed to the hook to stop and correct from the start instant |
| `available` | the durable transition: credentials retrievable, the deal served — written by the storefront when delivery is verified, independent of any buyer read | advance |
| `active` | steady state | — |

The acceptance test is a crash injected between each adjacent pair followed by a
restart, in both domains, with the double for the per-period case. The ordering is
`start` before `activated` before `available`, so a buyer never holds credentials to
a resource whose billing has not begun and whose lease is not activated.

*Rejected:* ordering the effects so `start` is last — a buyer with access and no
`start` is served free until recovery.

### D5. The undelivered path is committed behaviour

A deal that reaches no `available` is ended by the path, not by a configurable
failure action: where nothing was dispatched the hold is released, else the lease is
terminated through the end-deal route's decision log
(`buyer-initiated-compute-termination`); a prepaid deal is refunded in full through
the existing seller-initiated reverse, journaled; a per-period deal is handed to its
hook, which stops and returns the reserved batch, the minimum spend following its
committed refund rule. The triggers: the hook refusing a phase; the site's
`lease_ended` with cause `renewal_lapsed` in the awaiting-activation phase, which is
how the storefront learns that the activation deadline expired — a site decision, not
a storefront-detected failure; settlement completing with no window left (D1); and
the provisioning failure the storefront already handles.

*Rejected:* a storefront-side provisioning timer — it duplicates a clock the site
owns, races the site's claim, and refunds nothing when the storefront is the thing
that died. *Recommendation left to `negotiate-open-ended-compute-terms`' session:* a
prorated refund of provisioning time on prepaid deals, which would make provisioning
unbilled under both billing kinds.

### D6. No disclosure after a locally committed end

The credential read route enforces the recorded delivery state and the decision log
on every read — never a live snapshot — serialized with local termination by the
decision row's compare-and-set. Absolute, and local; the other three access
guarantees are the continuation's (`converge-ongoing-compute-leases` D4).

## Open questions

- The home of the path: the family kit, or `kit/fulfillment` if it proves
  family-neutral; settled in design.
- Whether the delivery record is the continuation record's delivery state
  (`converge-ongoing-compute-leases` D2) or its own row the continuation reads;
  settled in design, the former preferred since every per-period deal has one.

## Implementation cadence (recommended)

Two rounds. Round 1: the path with the window derivation, the hook interface and its
default, the state machine, and both domains composed onto it, with the credential
read enforcing the recorded state. Round 2: activation of every lease, the
undelivered path with the prepaid refund, and the lane scenarios — reserved
activation past the allowance, a crash before activation expiring at it with the
refund, delayed settlement against an absolute bound, the crash matrix, credits
unchanged. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2, D4 | `openspec/specs/fulfillment/spec.md` and architecture companion; `vm-storefront-fulfillment` spec; `physical-provisioning` spec; `ARCHITECTURE.md`, "Fulfillment" |
| D3 | `fulfillment` spec (the hook's interface); `settlement-servicing` spec |
| D5 | `settlement-servicing` spec; `ARCHITECTURE.md`, "Release" |
| D6 | `fulfillment` spec; `ARCHITECTURE.md`, "Deciding which party is authoritative" |
