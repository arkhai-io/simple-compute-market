# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
revised the same day against three independent design reviews of the goal, and again
against a second review of the revision, which raised nothing structural here. This
change's own design review may reopen any of them with a finding; its design session
verifies them against the code as its dependencies left it and adds the spec deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning, since every
dependency changes it.

- `AdminController.interrupt_deal`
  (`domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`):
  administrator key, resource the escrow UID; `load_escrow`; `_deal_is_interruptible`
  requires `settlement_plan.service_terms.interruptible`, which only
  `market_alkahest.proposals` writes, for a splitter-gated proposal;
  `_find_live_reservation_for_escrow` lists every site's reservations by
  `escrow_uid` and keeps reserved, provisioning, leased, or releasing rows; the
  action is `capacity_runtime.truncate_lease` to the interrupt time, then a stage
  event `deal_interrupted` with `settlement_action="splitter_declaration_pending"`;
  `seller_amount` and `refund_amount` are echoed, not acted on. VM reservations
  commit with `deal_ref={"negotiation_id": …}`, and the ledger records `escrow_uid`
  only from `deal_ref["escrow_uid"]`, so the lookup matches an admin-reserved hold
  and not a negotiated deal. The typed client's `admin_interrupt_deal` has no CLI
  caller and no scenario; `Stage10a` deliberately expires rather than interrupts.
- The storefront kit's deal controls are the stage-event read, evaluate-negotiate,
  and force-accept; no end-deal control exists in the kit.
- Bare metal: no seller-side end; `end_lease` is reached from buyer teardown and from
  Alkahest's terminal states.
- Seller authentication: storefront routes authenticate the seller by signature
  (`seller_auth.py`, e.g. the refund route); administrator routes by the admin key
  and the admin v2 contract.

## Goals / Non-Goals

**Goals:** a seller can end a spot deal under the policy the buyer accepted, with the
notice promised, in both domains; a seller cannot dress an on-demand breach as a
preemption; spot is proven in the pipeline.

**Non-Goals:** strategy automation; push notice; Alkahest deals.

## Decisions

### D1. Preemption is seller-authenticated, negotiation-keyed, and judged against the Agreement

The route is declared in the shared route contracts beside the buyer's end-deal route,
authenticated by the seller's signature as the refund route is, keyed by negotiation
ID, and mechanism-neutral. It reads `interruption_policy` from the accepted
Agreement's `provision_terms` and refuses, with a distinct reason, a deal whose policy
has `seller_may_interrupt: false`. It never reads the listing as currently stored,
so a seller changing its policy after acceptance changes nothing for the deal, as
`settlement-servicing` already requires of every other accepted term.

*Rejected:* extending the admin interrupt route. It is administrator-authenticated,
escrow-keyed, Alkahest-only, and truncates.

### D2. The effective time is now plus the notice; the stop is scheduled locally

The route fixes `effective_at = now + notice_seconds` and appends a request with cause
`seller_preemption` and that instant to the deal's log; the decision fold makes it the
effective end unless an earlier lawful request exists or arrives. The payments
contract cannot carry a future-effective stop, so the storefront durably schedules
the stop at the instant and issues an ordinary immediate `stop`, keyed by the
decision, when it arrives — and terminates the lease at the site then, through the
terminate route. If the storefront is down when the instant passes, the stop is late
and is corrected as any late stop is (`converge-ongoing-compute-leases` D4). A
scheduled stop whose decision was superseded — a buyer who cancels during the notice
window ends the deal at their own earlier instant — is refused as stale by its key
and never executes. Until the instant, a pending end and its effective time are
observable through the deal's status; the design does not promise the buyer is told,
and a push notice is deferred. A repeat returns the same decision.

*Rejected:* issuing the stop at once with a future effective time — not in the
contract. *Rejected:* issuing it at once with no time — it stops billing while the
buyer still holds the instance for the notice period.

### D3. The override is `buyer-initiated-compute-termination`'s, not this change's

The administrative override — any deal, whatever its policy, cause `admin_override`,
the operator's reason and identity, reported distinctly — is a request kind of the
decision log that `buyer-initiated-compute-termination` D5 introduces. This change
adds only the seller's contractual route over that arbitration, so a preemption of a
deal whose policy forbids it is never possible through it, and an emergency never
produces a record that looks like a lawful preemption. On-demand means no
discretionary preemption, not immunity from infrastructure: a site withdrawal of an
on-demand lease is an exceptional end attributed to its cause, reconciled to its
effective instant, with the remedy following the policy and the dispute authority.

### D4. Spot and on-demand differ only in the policy and the rate

No code path branches on a class. A spot listing is a per-period option with
`seller_may_interrupt: true` at its own asking rate, published beside the on-demand
listing from the same pool; settlement, the continuation, renewal, the lease, and the
buyer's cancel are the on-demand ones. The only spot-specific behaviour in the
repository is that the preemption route admits it.

### D5. The Alkahest interrupt route is left to Alkahest's owners

Its `escrow_uid` lookup defect and its unsubmitted splitter declaration are recorded
as unowned under `automate-seller-spot`'s lesser goal, which already owns the splitter
execution. This change neither fixes nor removes the route; a later Alkahest change
may move its deals onto the shared preemption route once the splitter declaration
is a financial convergence the stop intent can carry.

## Open questions

- Whether the pending end during the notice window is served by the existing status
  reads or needs a field of its own; settled in design against the status models
  `buyer-initiated-compute-termination` left.
- Where the durable schedule lives — a due instant on the decision row the
  continuation's cycle reads, or a loop of its own; settled in design, the former
  preferred since the continuation already runs per deal.
- Whether the operator CLI's preemption verb lives in the storefront CLI only or also
  in a seller-side tool; settled in design.

## Implementation cadence (recommended)

One round: the route and override in both domains, the client method and CLI verb,
the scheduled stop in the continuation, and the spot scenarios in both lanes. One
session.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2 | the storefront capability spec that owns the shared routes; `settlement-servicing` spec; `ARCHITECTURE.md`, "Release" |
| D3 | `storefront-publication` architecture companion (the on-demand promise) |
| D4 | `storefront-publication` architecture companion |
| D5 | the change index, under `automate-seller-spot`'s lesser goal |
