# Design

The decisions below were settled with the owner in the goal-level design of
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)
on 2026-10-28, across the goal's five changes. This change's own design session
verifies them against the code and adds the spec deltas; it does not reopen them
without a finding.

## Context

Verified against the tree on 2026-10-28; re-verify before planning.

- The site's terminate route, `POST /api/v1/contract/leases/{id}/terminate`, runs
  `LeaseLifecycleService.terminate_lease`, which proceeds only from `leased`, returns
  a `releasing` or released lease as it is, refuses `release_failed` and `unmanaged`,
  and calls `_request_release` at once — the same release the expiry sweep runs
  (`provisioning/compute/src/compute_provisioning/lease_lifecycle.py`). Truncation,
  by contrast, moves `lease_end_utc` and leaves the watchdog to notice on its next
  cycle (`kit/site/src/market_site/ledger.py`, `truncate_lease`).
- Bare metal: `POST /api/v1/fulfillments/{negotiation_id}/teardown`
  (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py`),
  authenticated by `_fulfillment_identity` as the accepted thread's buyer principal,
  refusing an introduction-settled deal; `BareMetalFulfillmentService.teardown`
  returns an already-terminating or released state unchanged, else
  `end_lease(reason="buyer_teardown")`, which calls the site's terminate through the
  reservation's recorded site and records lifecycle `TERMINATING`. The buyer reaches
  it through its own `BareMetalFulfillmentTransport.teardown`, not the canonical
  client, and the `market bare-metal teardown` verb.
- VM: `terminate_vm_lease` in `services/fulfillment_service.py` goes through
  `AggregateFulfillmentClient.terminate_lease(..., site_id=)`; its docstring says no
  route exposes the flow. The VM storefront's buyer-authenticated post-delivery
  routes are heartbeat, settle status, escrow reclaim, and the introduction read.
- The VM storefront ends a lease today only by: the admin interrupt route
  (truncation, Alkahest-only), terminal-settlement release or truncation, and the
  failure policy's release. Nothing is buyer-initiated.
- The site tells the storefront of an end through the deal-event sink
  (`provisioning/compute/service/.../deal_event_sink.py`): VM receives
  `release-started`, `started`, `usage-started`, `failed`, and `capacity-released`;
  bare metal receives `capacity-released` only. The capacity-released callback is
  sent after teardown is proven and drained from an outbox in the lease cycle.
- A reservation's `deal_ref` carries the negotiation ID (and the escrow UID for an
  Alkahest hold); the site never sees a settlement mechanism or credential
  (`ARCHITECTURE.md`, "Authority boundaries"; `settlement-servicing`, "Mechanism
  credentials remain scoped").

## Goals / Non-Goals

**Goals:** a buyer can end any compute deal, promptly and idempotently, through one
route shape in both domains; the storefront holds one durable record of why and when
a deal ended; the site reports an end when it intends it, not when it has finished.

**Non-Goals:** any payment effect; cancellation terms; seller- or site-initiated
ends beyond receiving the site's report; the Alkahest interrupt route.

## Decisions

### D1. The buyer's right to stop is universal, and its cost is the mechanism's

A buyer may end any compute deal, reserved included. What it costs is decided by the
selected settlement mechanism and nothing else: a prepaid `once` part is unaffected
(the buyer forfeits the term; a refund stays seller-initiated, as the spec requires),
an Alkahest escrow follows its own release model, and a per-period part stops at the
effective time once per-period parts exist. The storefront never computes a
cancellation consequence of its own.

*Rejected:* a stated cancellation term (refund of the unused term, or a fee) on the
listing. Nothing today needs it, and it would be a third commercial term beside the
rate and the interruption policy with no product behind it. Revisit trigger: a seller
wants to offer refundable reserved terms.

### D2. Ending a deal terminates; it never merely truncates

The route terminates the lease at the site through the terminate route, which runs
the release immediately. Truncation remains what it is: an operation for moving an
end the watchdog will act on later. The VM admin interrupt route's use of truncation
is the lazy path this rule exists to avoid, and it is not touched here.

*Rejected:* truncating to now and invoking the watchdog's cycle. The terminate route
already does both in one step, and a cycle invocation is an operator control, not a
buyer's.

### D3. One route shape in both domains, keyed by the negotiation ID

The route is buyer-authenticated against the accepted thread's buyer principal, keyed
by negotiation ID, declared in the shared settlement route contracts so the canonical
client and every storefront's authentication bind it from one declaration
(`ARCHITECTURE.md`, "Route contracts and their HTTP binding"). Bare metal's existing
route is that route; its own transport method and `market bare-metal teardown` are
kept as the verb over it. VM mounts the same contract over `terminate_vm_lease`. A
deal settled by introduction is refused as its fulfillment reads are today, by the
accepted stage's `completes_outside_settlement` declaration.

The response is durable progress: the stop intent's recorded state and the lease
state the site answered, never "released" while teardown is queued. A repeat finds
the same intent and the same lease state.

*Rejected:* keying by escrow UID (the interrupt route's choice): it binds the route to
one mechanism, and VM reservations carry no escrow UID.

### D4. A durable stop intent, with financial and physical convergence apart

The storefront records one stop intent per deal, keyed by negotiation ID: the
effective instant, the cause (`buyer_cancel` here; `seller_preemption`,
`site_withdrawal`, `funding_ended`, `deadline` are added by the later changes), who
requested it, and two independently tracked convergences — financial (what the
mechanism must do; nothing for a `once` part) and physical (the lease terminated,
then released). Each convergence is idempotent across retries and restarts; the
intent is written before any external effect and is the one place a later reader
learns why a deal ended. Stage events are emitted from it for observability and are
not its authority.

*Rejected:* recording the end only as a stage event or a lease reason string. Stage
events are best-effort and unstructured (`redesign-storefront-stage-events`); the
goal's later changes need an authoritative cause to decide what billing does.

### D5. The site reports a lease's end when it intends it, to the storefront only

The site sends a lease-ended report — effective instant, cause (expiry, termination
with its reason, force-release), reservation and site — at the moment it forms the
intent, which is when the lease enters `releasing`, before any teardown. It rides
the capacity-release outbox so it is delivered when the storefront returns, and is
signed by the site's service identity like every callback. Both compute storefronts
receive it, record it against the deal, and keep it as evidence behind an
authenticated read. The capacity-released callback after proven teardown is
unchanged and is still what reopens listings.

The report goes to the storefront only. The site knows no settlement mechanism, holds
no payee credential, and does not even hold a transaction ID, by design; the
storefront, which knows the deal's mechanism, is the party that acts on the report
financially (in `converge-ongoing-compute-leases`). The dispute authority is served by
the storefront retaining the signed report, since the transaction's attachments can
carry only the deal itself.

*Rejected:* the site calling the payments service directly, which would give the site
a mechanism dependency and a payee credential. *Rejected:* reporting only at
`torn_down`, which would bill the buyer for the seller's teardown time.

### D6. The lever must work with the storefront process down

The buyer's cancel is its own lever and needs no storefront: once per-period parts
exist the buyer's CLI stops the transaction at the payments service first and calls
this route second (decided for `converge-ongoing-compute-leases`). This change
prepares for that by making the route idempotent against an end that already
happened for another cause, so a cancel arriving after the continuation has
terminated the lease finds the intent rather than refusing.

## Open questions

- Whether the stop intent lives in `core/storefront`'s common schema (one table for
  every domain) or in each domain's persistence. The decision falls to the
  `kit-owned-storefront-auth-and-persistence` boundary (core owns market state, a
  domain's client only its own tables) and is settled in this change's design session
  once that change's contracts carve-out has or has not landed.
- Whether the lease-ended report replaces VM's `release-started` callback or is a
  second event beside it; settled in design against the event vocabulary
  `redesign-storefront-stage-events` decides, if it has decided by then.

## Implementation cadence (recommended)

Two rounds. Round 1: the site's lease-ended report through the outbox and both
storefronts' receipt of it, with the stop intent's persistence. Round 2: the shared
route contract, the VM route over `terminate_vm_lease`, bare metal's route moved onto
it, the client method and CLI verbs, and the end-to-end stages. One session per
round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1 | `openspec/specs/settlement-servicing/architecture.md` |
| D2 | `openspec/specs/site-capacity/architecture.md` |
| D3 | the storefront capability's spec that owns the shared route; `vm-storefront-fulfillment` spec |
| D4 | `docs/development/ARCHITECTURE.md`, "Release" |
| D5 | `openspec/specs/physical-provisioning/spec.md`; `ARCHITECTURE.md`, "Fulfillment status and results" |
| D6 | `openspec/specs/buyer-orchestration/spec.md` |
