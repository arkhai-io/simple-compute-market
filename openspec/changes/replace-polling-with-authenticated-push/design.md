# Design

## Context

Interaction review performed 2026-08-06; re-verify before implementing.

Cross-service polling loops in the VM storefront:

- `capacity_client.capacity_events_poller_loop` — one poller per configured site,
  positioning at the feed head, running a full listing reconcile to converge with
  anything missed while down, then polling for new versions and emitting each as a
  site-tagged `CapacityDelta`. Already handles a feed head moving backwards by
  re-reconciling.
- `site_projection_cache.site_projection_poller_loop` — re-reads projections on
  `capacity.poll_interval`, defaulting to 5 seconds.
- `fulfillment_service._poll_fulfillment_status` — polls until `active`/`failed` or
  **timeout**, treating every other state as in progress.

Not a cross-service poll, and staying:

- `fulfillment_resume_runtime.fulfillment_resume_loop` — sweeps *local* unfinished
  accepted escrows on an interval.

Out of scope, different boundary: `settle_controller`'s buyer-facing settle-status poll
and `system_controller`'s startup wait.

The existing provisioning-to-storefront seam is `StorefrontLifecycleEventSink.deliver`,
which handles exactly one event kind (`capacity_released`), deduplicates in process
memory, and resolves its target from global configuration.

## Goals / Non-Goals

**Goals:** events arrive when they happen; correctness unchanged; scenarios stop waiting
on intervals.

**Non-Goals:** transport, event semantics, many-to-many delivery, removing pull.

## Decisions

### Push accelerates; pull and the local sweep remain correctness

This is the decision everything else depends on, and the one most likely to erode.

A durable outbox with retries still has failure modes an interval-based poll does not:
a receiver that rejects malformed input, an outbox drained against a storefront that
was restoring from backup, a delivery worker wedged behind a poison message. Making
push the correctness path would trade a bounded staleness window for an unbounded one.

So every pull endpoint stays, `fulfillment_resume_loop` stays, and the acceptance test
for this change is that **disabling delivery entirely leaves the system correct and
merely slower**. If that stops being true, push has quietly become load-bearing.

### The outbox is written in the same transaction as the state change it reports

An event written after its transaction commits can be lost; an event written before can
describe a transition that rolled back. Atomicity with the reported transition is what
makes at-least-once delivery meaningful rather than approximate.

This constrains where the outbox lives: it must share a transaction with the settlement
and capacity writes, which `kit/fulfillment`'s repository already supports by taking a
caller-supplied session and never committing.

### Three flows, three different push shapes

They are not one mechanism applied three times, and treating them as one is the likely
design error.

**Capacity events** are already a versioned feed with a head cursor and an established
gap-recovery behavior. Push carries a notification that the head moved; the receiver
still reads the feed. That preserves ordering and the existing backwards-head handling
rather than reimplementing them in the transport.

**Projection invalidation** is not an event stream at all — the storefront re-reads a
generation and replaces it atomically. Push should carry *invalidation*, not the
projection body, so a large projection is not duplicated into an outbox and so the
existing atomic-replace and stale-generation semantics are untouched.

**Fulfillment status and result** is the only one where the payload is the point, and
where `fulfillment.result.v1` already exists to carry it.

Recorded because a single generic "event push" would push projection bodies through an
outbox and re-derive capacity ordering in the transport, and both would be worse than
the polling they replace.

### Deduplication is persistent, on the receiver

The existing sink deduplicates in process memory, which does not survive restart — the
exact window at-least-once delivery makes most likely to matter. The receiver persists
seen event identity and applies transitions idempotently.

Idempotent application is the stronger property and the one to build for: a receiver
that applies correctly on a duplicate does not depend on its deduplication being
perfect.

### Scenarios await delivered events, and this is the change's most visible benefit

Today an end-to-end scenario waits for a poll interval to elapse and then re-checks,
so its runtime is a function of interval and its reliability is a function of timeout
margin. That is why three separate changes each carry a task requiring observable
barriers rather than sleeps, and why the e2e refactor has been parked on a live run
since July.

With delivery, a scenario awaits the event the system emits when the work is done. The
scenario becomes a statement about the system rather than about timing.

The fixtures to build against are the generalized ones from
`bare-metal-and-credits-domain-stacks` — building a second set here would duplicate that
work and guarantee drift.

## Risks / Trade-offs

- **[Push silently becomes load-bearing]** → The named erosion. The disable-delivery
  acceptance test is what catches it, and it belongs in the suite rather than in a
  reviewer's memory.
- **[A generic transport flattens the three flows]** → Named above; capacity keeps its
  feed, projections carry invalidation only.
- **[Outbox growth is unbounded]** → Retention needs the same age-and-reference
  treatment as reservation retention, decided here rather than discovered in production.
- **[Delivery failure is invisible]** → Metrics and audit state are in scope, not
  follow-on. A silent outbox is worse than a poll.
- **[Scenarios become event-order-dependent]** → Awaiting a specific event is
  deterministic; awaiting events in an assumed order may not be. Scenarios should await
  facts, not sequences.
- **[Verification cost per event]** → Lower than per poll, since polls run whether or
  not anything happened, but it should be measured rather than asserted.

## Migration Plan

1. Durable outbox written transactionally with reported transitions, plus delivery
   worker, retention, and metrics.
2. Receiver with persistent deduplication and idempotent application.
3. Fulfillment status and result delivery; retire `_poll_fulfillment_status` as the
   primary path.
4. Capacity-event head notification; retire `capacity_events_poller_loop`'s interval,
   keeping its feed read and gap recovery.
5. Projection invalidation; retire `site_projection_poller_loop`'s interval.
6. Scenario refactor onto delivered events.

Each of 3, 4, and 5 is independently deployable: the corresponding poll is disabled only
after its push path is proven, and can be re-enabled by configuration.

## Open Questions

- **Should the retired polls remain configurable, or be removed once push is proven?**
  Keeping them costs a code path that is rarely exercised and therefore rots; removing
  them makes the disable-delivery acceptance test harder to state. Deferrable, and worth
  deciding once one flow has run in production.
- **Does projection invalidation need per-family granularity?** Resource pools and
  capacity buckets already load and version independently. Deferrable — coarse
  invalidation is correct and merely re-reads more than necessary.
