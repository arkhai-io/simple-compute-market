# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and revised the same day against three rounds of independent design review of the
goal. This change's own design review may reopen any of them with a finding; its
design session verifies them against the code and adds the spec deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning.

- The site's terminate route, `POST /api/v1/contract/leases/{id}/terminate`, runs
  `LeaseLifecycleService.terminate_lease`, which proceeds only from `leased`, returns
  a `releasing` or released lease as it is, refuses `release_failed` and `unmanaged`,
  and calls `_request_release` at once — the same release the expiry sweep runs
  (`provisioning/compute/src/compute_provisioning/lease_lifecycle.py`). The caller's
  reason is not persisted on the reservation. Truncation, by contrast, moves
  `lease_end_utc` and leaves the watchdog to notice on its next cycle
  (`kit/site/src/market_site/ledger.py`, `truncate_lease`). `_request_release` has
  three outcomes: begin `releasing` (teardown or a create in flight), free the
  capacity directly (nothing dispatched or already torn down), or `release_failed`.
- Bare metal: `POST /api/v1/fulfillments/{negotiation_id}/teardown`
  (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py`),
  authenticated by `_fulfillment_identity` as the accepted thread's buyer principal,
  refusing an introduction-settled deal; `BareMetalFulfillmentService.teardown`
  returns an already-terminating or released state unchanged, else
  `end_lease(reason="buyer_teardown")`, which calls the site's terminate through the
  reservation's recorded site and records lifecycle `TERMINATING`. It refuses a
  fulfillment that has not begun. The buyer reaches it through its own
  `BareMetalFulfillmentTransport.teardown`, not the canonical client, and the
  `market bare-metal teardown` verb.
- VM: `terminate_vm_lease` in `services/fulfillment_service.py` goes through
  `AggregateFulfillmentClient.terminate_lease(..., site_id=)`; its docstring says no
  route exposes the flow. The VM storefront's buyer-authenticated post-delivery
  routes are heartbeat, settle status, escrow reclaim, and the introduction read.
- The VM storefront ends a lease today only by: the admin interrupt route
  (truncation, Alkahest-only, administrator-authenticated), terminal-settlement
  release or truncation, and the failure policy's release. Nothing is
  buyer-initiated.
- The site tells the storefront of an end through the deal-event sink
  (`provisioning/compute/service/.../deal_event_sink.py`), which has one production
  sender, `capacity_released`, sent after teardown is proven. Its outbox,
  `CapacityReleaseCallbackOutbox`, is one row per reservation keyed by
  `capacity_reservation_id`, holding attempt and delivery bookkeeping only; the
  callback's payload is rebuilt from the reservation at delivery. The VM
  storefront's `started`, `usage-started`, `release-started`, and `failed` routes
  have no sender, and `resolve-compute-family-findings` D4 removes them.
- A reservation's `deal_ref` carries the negotiation ID (and the escrow UID for an
  Alkahest hold); the site never sees a settlement mechanism or credential
  (`ARCHITECTURE.md`, "Authority boundaries"; `settlement-servicing`, "Mechanism
  credentials remain scoped").
- Retention precedent: contact exchange's `retention_seconds`, a seller-configured
  aggregate window applied by a held-and-stepped sweep, deleting in place and leaving
  a tombstone (`contact-exchange-settlement`).

## Goals / Non-Goals

**Goals:** a buyer can end any compute deal, promptly and idempotently, through one
route shape in both domains; the storefront holds one durable, auditable record of
every request to end a deal and one effective decision; the site reports an end when
it intends it, durably, with the instant the transition established.

**Non-Goals:** any payment effect; cancellation terms; the seller's contractual
preemption route; the Alkahest interrupt route.

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

A deal whose fulfillment has not begun — a hold still `reserved`, or a create in
flight — is ended too: the storefront releases the hold where nothing was dispatched
and otherwise terminates, which the site's release decision already distinguishes
(`ARCHITECTURE.md`, "Release"). Bare metal's refusal of an unbegun fulfillment is
retired.

The response is durable progress: the effective decision's state and the lease state
the site answered, never "released" while teardown is queued. A repeat finds the
same decision and the same lease state.

*Rejected:* keying by escrow UID (the interrupt route's choice): it binds the route to
one mechanism, and VM reservations carry no escrow UID.

### D4. An append-only request log and one effective decision

The storefront keeps, per deal, an **append-only log of requests to end it**: each
with a stable identity, the requesting principal and its authority (the accepted
buyer; the seller, through the preemption route of
`publish-and-preempt-spot-compute`; the site, through its lease-ended report; an
administrator, through the override below; the storefront itself, on a verified
funding end), the cause, the requested effective instant, and the evidence the request
rests on. Nothing in the log is updated or deleted on the path.

The **decision** is a deterministic fold over the log, and it carries two instants
with different rules, because they bound different things:

- The **physical end** — when the lease was or will be terminated. The request with
  the earliest lawful effective instant sets it; a later request with an earlier
  instant replaces it, and the earlier request stays in the log as superseded. Ties
  break deterministically — buyer, then seller, then site, then administrator, then
  arrival order. Once its instant has passed, or physical convergence has begun, it
  is final: no later request replaces it, so no lease is resurrected and no executed
  action is rescheduled.
- The **financial effective end** — the instant billing is corrected to. It starts
  equal to the physical end and may move only *earlier*, and only on authenticated
  evidence of an earlier end: a signed site event that arrives late, a stop in a
  verified snapshot seen late, an administrator's override with its reason. Each move
  re-runs the financial convergence from the new instant, idempotently by the
  decision and the evidence; it never moves later, so no evidence can take money back
  from the buyer, and it is never affected by physical finality.

Both are compare-and-set transactions, as the refund-versus-delivery ordering already
is in each domain's tables. Physical state is monotonic toward "ended"; financial
state is monotonic toward "the buyer pays less".

Financial and physical convergence hang off the decision and are tracked
independently, each idempotent across retries and restarts. Every external call a
decision causes is an operation the deal's journal records with its own identity —
a payment stop or reversal (`converge-ongoing-compute-leases` D5), a lease terminate,
a scheduled stop — and carries that identity in its idempotency key, so a retry
resends the same operation and a superseded decision's scheduled action, if it fires,
is refused as stale rather than executed. Stage events
are emitted from the decision for observability and are not its authority.

**Retention.** The log is dispute evidence, so its window is at least the payments
service's dispute horizon. A seller-configured window, following contact exchange's
`retention_seconds` shape and default, prunes a deal's requests only once its
decision is final and both convergences are complete; the decision row stays with the
deal. `redesign-authenticated-requests` bounds replay state the same way.

*Rejected:* one immutable intent per deal — it cannot hold a seller's notice pending
at 15:00 and a buyer's cancel at 14:30. *Rejected:* one mutable intent amended in
place — the audit trail is whatever the last writer kept, and a scheduled action
holding the old key cannot tell it is stale. *Rejected:* first request wins — it
charges a buyer for time they asked to end, and the buyer's own stop at the payments
service then makes the ledger and the storefront disagree. *Rejected:* one instant
with one finality rule — a site event proving the lease ended at 12:00 that arrives
after an administrator's 12:10 override would then be unable to correct the buyer's
charges, and holding the override open until every authority reports would block the
one lever meant to work without them.

### D5. The administrative override is a request kind with its own authority and audit

An administrator-authenticated override ends any deal whatever its terms, recorded in
the log with cause `admin_override`, the operator's stated reason, and the
administrator's identity, and reported distinctly in status and events. It exists so
that an emergency never has to be dressed as a lawful preemption, and so that a
preemption of a deal whose policy forbids it is never possible through the seller's
route (`publish-and-preempt-spot-compute`); what an override cost the buyer is read
from the mechanism's event record and the accepted policy.

### D6. The site records a lease's end as a durable event, with the transition

The ledger writes a `lease_ended` event — stable event identity, reservation, site,
the effective instant, the cause (`expired`, `renewal_lapsed`, `terminated` with the
caller's reason, `force_released`, `release_failed` with its reason), and the state
it came from — in the same transaction as the transition that ends the lease, on
every path `_request_release` and force-release take, including the direct-release
and failure outcomes that never enter `releasing`. The event is written when the
site forms the intent, before any teardown.

Delivery is a separate outbox keyed by event identity, so an end and its later
capacity release are two deliveries with two acknowledgements. The callback carries
the stored payload, signed by the site's service identity like every callback; both
compute storefronts authenticate it against the reservation's accepted site, receive
it idempotently by event identity, record it as a request in the deal's log with the
site's effective instant, and keep the signed body as evidence behind an
authenticated read. The pull path is the lease read the storefront already has: a
lost notification costs one polling interval, never the deal. The capacity-released
callback after proven teardown is unchanged and is still what reopens listings.

The report goes to the storefront only. The site knows no settlement mechanism,
holds no payee credential, and does not hold a transaction ID, by design; the
storefront, which knows the deal's mechanism, is the party that acts on the report
financially (`converge-ongoing-compute-leases`). The dispute authority is served by
the storefront retaining the signed event, since the transaction's attachments can
carry only the deal itself.

This is its own acceptance boundary within the change, testable at the site with no
storefront: write the event, crash, recover, deliver once. It is the shape
`replace-polling-with-authenticated-push`'s transactional outbox will take, with one
event kind, and that change adopts it rather than building a second.

*Rejected:* riding the per-reservation release outbox — it cannot hold two events
with separate acknowledgements, and it reconstructs its payload, losing the instant
the transition established. *Rejected:* the site calling the payments service, which
would give the site a mechanism dependency and a payee credential. *Rejected:*
reporting only at `torn_down`, which would bill the buyer for the seller's teardown
time. *Rejected:* pull only — correct, but every end would then be learned a polling
interval late rather than only a lost one.

### D7. The lever must work with the storefront process down

The buyer's cancel is its own lever and needs no storefront: once per-period parts
exist the buyer's CLI stops the transaction at the payments service first and calls
this route second (`converge-ongoing-compute-leases`). This change prepares for that
by making the route idempotent against an end that already happened for another
cause: a cancel arriving after the continuation has terminated the lease is appended
to the log and finds the final decision rather than refusing.

## Open questions

- Whether the request log and decision live in `core/storefront`'s common schema
  (one table for every domain) or in each domain's persistence. The decision falls
  to the `kit-owned-storefront-auth-and-persistence` boundary (core owns market
  state, a domain's client only its own tables) and is settled in this change's
  design session once that change's contracts carve-out has or has not landed.
- Whether `replace-polling-with-authenticated-push` is designed before this change
  is; if so, its outbox carries the `lease_ended` event and this change depends on it
  for the transport, keeping only the event's definition. It is `ready for design`
  with no one on it, so this change does not wait.

## Implementation cadence (recommended)

Two rounds. Round 1: the site's `lease_ended` event and its outbox, both storefronts'
receipt of it, and the request log and decision with their persistence and
retention. Round 2: the shared route contract, the VM route over
`terminate_vm_lease`, bare metal's route moved onto it with its unbegun-fulfillment
refusal retired, the administrative override, the client method and CLI verbs, and
the end-to-end stages. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1 | `openspec/specs/settlement-servicing/architecture.md` |
| D2 | `openspec/specs/site-capacity/architecture.md` |
| D3 | the storefront capability's spec that owns the shared route; `vm-storefront-fulfillment` spec |
| D4, D5 | `docs/development/ARCHITECTURE.md`, "Release"; the owning storefront spec |
| D6 | `openspec/specs/physical-provisioning/spec.md`; `site-capacity` spec; `ARCHITECTURE.md`, "Fulfillment status and results" |
| D7 | `openspec/specs/buyer-orchestration/spec.md` |
