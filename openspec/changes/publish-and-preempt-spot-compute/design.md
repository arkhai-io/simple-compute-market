# Design

The decisions below were settled with the owner in the goal-level design of
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)
on 2026-10-28, across the goal's five changes. This change's own design session
verifies them against the code as its dependencies left it and adds the spec deltas;
it does not reopen them without a finding.

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

### D2. The effective time is now plus the notice, and the stop is scheduled from it

The route fixes `effective_at = now + notice_seconds`, records the stop intent with
cause `seller_preemption` and that instant, issues the payee stop effective then
(immediately when the notice is zero), and the continuation terminates the lease at
the site when the instant arrives, through the terminate route. Until then the deal's
status read shows the pending end and its effective time, which is the buyer's
notice. A repeat returns the same intent. A buyer who cancels during the notice
window ends the deal at their own earlier instant.

### D3. An override is a different act with its own cause

An administrator-authenticated override ends any deal whatever its policy, records
cause `admin_override` with the operator's stated reason, and is reported distinctly
in status and events. A preemption of an on-demand deal is therefore never possible
through the preemption route, and an emergency never produces a record that looks
like a lawful preemption; what a breach cost the buyer is read from the mechanism's
event record and the policy.

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
- Whether the operator CLI's preemption verb lives in the storefront CLI only or also
  in a seller-side tool; settled in design.

## Implementation cadence (recommended)

One round: the route and override in both domains, the client method and CLI verb,
the scheduled stop in the continuation, and the spot scenarios in both lanes. One
session.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2, D3 | the storefront capability spec that owns the shared routes; `settlement-servicing` spec; `ARCHITECTURE.md`, "Release" |
| D4 | `storefront-publication` architecture companion |
| D5 | the change index, under `automate-seller-spot`'s lesser goal |
