## Context

See proposal.md — Why. What that section states as a gap is worth stating precisely as a starting point, because an earlier note in `add-bare-metal-hosted-settlement` claimed the opposite and was never checked against the code.

A post-collection funding loss is already observed and already parks the deal. Hosted obligations always carry `terminal_risk_monitoring`, so servicing keeps polling status after `collection_state` reaches `succeeded` rather than going terminal. `_escrow_status` reads a reversal, an operator review, or an escalating incident arriving after collection as `manual_required`; `_finish_status` writes that to `mechanism_status`; the next sweep drives the obligation terminal in that state; and `hosted_public_status` checks `manual_required` before `collected`, so the buyer-visible status flips. None of that needs building.

What is absent is everything after the park:

- The incident is stored and never projected. `_mechanism_state` and the status receipt both carry `result.incident.model_dump()`, but the public payload exposes only `status` and `funding_reason`. `hosted_projected_reason` reaches the incident kind only as a last-resort fallback, when the authority left no funding reason of its own — which for a real dispute it does not. So `incident_ref` and the evidence digest are unreachable from outside, and a dispute-parked obligation is indistinguishable from an operator-review-parked one.
- Nothing states the delivery consequence. `vms` truncates the lease for a pre-collection loss (`mechanism_status` `failed` → `_cleanup` → `on_terminal` → `truncate_lease_for_terminal_settlement`) and deliberately does not for a post-collection one (`_terminal_requires_lease_truncation` requires `collection_state != "succeeded"`). Both are correct; neither is visible.
- `bare_metal` is broken here. Its `on_terminal` requests `callbacks.cleanup` for every non-`collected` state, `cleanup` raises `collection cannot be excluded; physical cleanup is frozen` for a `collected` lifecycle, and `SettlementServicingWorker._terminal` catches every terminal-callback exception into a log line. A post-collection loss therefore ends as a swallowed error.

Producer-side there is nothing to wait for. Signed `v0.4.2` carries `normalized-funding-reversal.v1`, `payer-return-instructions.v1`, and `operator-recovery-redaction.v1`; `EscrowResult.incident` is a `FundingIncidentProjection` with `incident_ref`, `kind`, `state`, and `evidence_digest`; and `FundingIncidentKind` includes `ACH_RETURN`, `CARD_DISPUTE`, `POST_COLLECTION_LOSS`, `TRANSFER_REVERSAL`, and `REFUND`. The client exposes no method for `/api/v1/operator/incidents`, and it does not need to: the marketplace's route to a loss is the escrow response it already polls.

## Goals / Non-Goals

**Goals:**

- One shared projection surface for the incident and for the delivery consequence, sited so a domain cannot build a hosted status payload that omits either by forgetting to — the same argument that put `hosted_projected_reason` in the kit rather than in each domain.
- A delivery-consequence projection derivable from state the runtime already persists, so it needs no new lifecycle column and no migration.
- `bare_metal` taking the same report-and-keep-serving path the other two domains take, rather than a distinct one that happens to throw.
- Both withheld lanes reaching `complete` against a real Stripe test account.

**Non-Goals:**

- Beyond proposal.md's non-goals, at the design level: no change to `_escrow_status`, to `terminal_risk_monitoring`, or to any transition in `SettlementRuntime`. If this change edits the state machine, it has gone wrong.
- No operator UI, queue, or notification. The projection is what an operator reads; where they read it from is a separate concern.

## Decisions

**Project the incident as the authority's own object, not a marketplace summary.**
`FundingIncidentProjection` is already provider-neutral — that is the point of the producer's normalization capability — so the marketplace has nothing to add by re-deriving it and everything to lose. Passing `incident_ref`, `kind`, and `evidence_digest` through unchanged means a consumer that later learns to resolve an incident against the authority has the reference it needs, and it keeps the marketplace out of the business of interpreting provider outcomes, which `Profile-specific reclaim and loss remain authority-owned` forbids. Rejected: mapping incident kinds onto a marketplace vocabulary, which would need a new mapping to maintain per producer release and would drop `incident_ref` on the floor. Also rejected: exposing `incident.state`, which is the authority's internal resolution progress; the marketplace has no use for it and no way to keep it fresh once the obligation is terminal.

**Derive `fulfillment_blocked` rather than store it.**
The record already distinguishes the two cases: a loss that took capacity service back leaves `collection_state != "succeeded"` with a terminal non-collected outcome, and a post-collection loss leaves `collection_state == "succeeded"`. That is the same predicate `_terminal_requires_lease_truncation` already uses to decide whether to truncate, which is not a coincidence — the projection should say what the domain did, and it can only be trusted to if both read the same thing. Rejected: a persisted boolean written by the terminal callback, which adds a column, a migration, and a second source of truth that can disagree with the lease.

**Name it for what it is, not for what it sounds like.**
`fulfillment_blocked` reads as "fulfillment was prevented", and for the `ach_return` lane it usually was not: the runtime fulfills at authoritative funding, and a return arrives after. The spec therefore defines it as delivery not surviving the loss, covering both never-fulfilled and fulfilled-then-torn-down. The alternative — actually preventing fulfillment by holding delivery until the ACH return window closes — was considered and rejected: it would delay every ACH deal by the return window to serve an assertion in a test harness, and the accepted deadline is the marketplace's existing instrument for that if it is ever wanted.

**A post-collection loss reports and keeps serving.**
`vms` already decided this and documented it; this change confirms it as the requirement rather than reversing it. A dispute is not an adjudication, the buyer may win it, and pulling a running machine out from under them on an unresolved reversal is worse than the loss it answers. It also matches what the harness asserts for the lane — `operator_incident_observed`, not `fulfillment_blocked` — which is the lane's own reading of the same question. Rejected: revoking on post-collection loss, which recovers hardware at the cost of a wrong eviction whenever a dispute goes the buyer's way. Rejected: a per-domain remediation hook, which defers the same policy decision into three places instead of making it once.

**Fix `bare_metal` by not asking, rather than by catching.**
Its `on_terminal` should request cleanup only where cleanup is permitted — an uncollected terminal state — mirroring the predicate `vms` uses. Catching the `BareMetalHostedLifecycleError` at the call site would silence the symptom while leaving the worker asking for something the lifecycle exists to refuse, and would leave the next reader unable to tell a frozen cleanup from a real failure.

## Risks / Trade-offs

- **The two new fields land on a payload other consumers already parse** → Both are additive and optional; no existing field is renamed, retyped, or removed, and nothing is dropped from persistence. A consumer that ignores them sees exactly what it sees today.
- **`fulfillment_blocked` is derived, so a domain that tears down outside the terminal callback would make it lie** → The predicate is shared with the truncation decision rather than duplicated, so the two cannot drift without a deliberate edit to one surface. A domain that acquires its own teardown path is a spec change, not a silent divergence.
- **Confirming "keep serving" means a seller can lose the money and keep serving the machine** → That is the accepted trade, and it is bounded: the authority's operator recovery is the remedy, and the obligation is parked and readable rather than silently complete. The alternative risks evicting a buyer who wins the dispute.
- **Neither lane has ever run, so the harness capabilities are unproven** → The bridge already dispatches all three actions and answers `available: false` for each, so the failure mode is a clean `ProcessUnavailable` rather than a false pass. Both lanes run under a development run before any protected run is attempted.
- **`induce_test_post_collection_loss` depends on the producer's test-mode helper** → If the released authority exposes no exact helper, the lane reports `ProcessUnavailable` and stays unqualified while the projection work still lands and is unit-covered. That is a partial outcome, not a blocked change.

## Migration Plan

No data migration. Deployment is a marketplace release; the two new payload fields appear on the next status projection for every obligation, terminal or live, because they are derived from state already stored. Rollback is the previous marketplace release — nothing persisted by this change needs undoing.

Qualification is ordered and cannot be compressed: both lanes pass under a development run against the real Stripe test account first; then a marketplace release is cut from the implementing commit, because a protected run executes the released commit; then the protected run is the acceptance signal.

## Open Questions

- Whether a `REFUND` or `TRANSFER_REVERSAL` incident arriving post-collection should read differently to a `CARD_DISPUTE` for an operator. All three project identically here, which is correct for this change — the kind is projected, so an operator can already tell them apart — and any per-kind handling is a later change with its own evidence.
