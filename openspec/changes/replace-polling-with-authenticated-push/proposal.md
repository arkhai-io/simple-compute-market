## Why

**Supersedes and widens `provisioning-result-push-delivery`** (2026-08-06). That change
scoped itself to hardening one callback seam for Settlement Result delivery, and was
blocked on two conditions: POOLS-7 durable results, and selection of a trusted
many-to-many ownership model. The second condition was removed rather than satisfied —
many-to-many is not being pursued — and `service-identity-signing` now supplies the
trusted channel the first half always needed. Its own scope note of 2026-08-03 asked for
exactly the review this change performs: the two flows it named came "from the one
existing callback seam, not from a review of every storefront↔provisioning-service
network interaction."

That review, done 2026-08-06, found **three** cross-service polling loops in the VM
storefront, not one flow:

| Loop | What it polls for |
|---|---|
| `capacity_events_poller_loop` | tails each authority's versioned capacity-event feed, emitting deltas onto the local bus |
| `site_projection_poller_loop` | re-reads resource-pool and capacity-bucket projections on an interval |
| `_poll_fulfillment_status` | polls `get_fulfillment_status` until `active`/`failed` **or timeout** |

A fourth loop, `fulfillment_resume_loop`, sweeps local unfinished escrows and is not a
cross-service poll. It stays, and becomes the recovery backstop rather than a
duplicate of push.

Polling is not merely inefficient here. Every one of the three converts an event the
authority already knows about into a delay bounded by an interval, and the fulfillment
poller converts it into a **timeout** — which is why end-to-end scenarios across this
repository wait on convergence rather than on facts, why "observable barriers rather
than sleeps" appears as a task in three separate changes, and why
`refactor-e2e-fulfillment-lifecycle` has been parked since July on a live run it cannot
make deterministic.

## What Changes

- Deliver authority-originated events to the storefront over the authenticated channel
  `service-identity-signing` establishes, with a durable outbox written atomically with
  the state transition being reported.
- Cover all three cross-service flows — capacity events, projection invalidation, and
  fulfillment status/result — rather than results alone.
- Deliver at least once with stable event identity, capped retry and backoff, replay,
  metrics, and audit state; persist receiver deduplication and apply transitions
  idempotently across storefront restart.
- Retain every pull endpoint as the permanent reconciliation backstop. Push is an
  accelerator; correctness stays with pull and with the local resume sweep.
- Refactor end-to-end scenarios to await delivered events rather than poll for
  convergence, so a scenario's timing depends on the system doing the work rather than
  on an interval.
- Obtain sensitive material just in time; store no durable plaintext credentials in the
  outbox or storefront lifecycle tables.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: an authority delivers lifecycle, capacity, and projection
  events over its authenticated outbound channel with a durable outbox, rather than
  requiring the storefront to poll for them.
- `fulfillment`: durable optional push delivery over the pull-correct Settlement Result
  aggregate.
- `storefront-publication`: a storefront applies pushed events idempotently with
  persistent deduplication, and retains pull reconciliation as the correctness baseline.
- `test-compatibility`: end-to-end scenarios observe delivered events rather than polling
  for convergence.

## Non-Goals

- Do not replace or weaken pull reconciliation. Every pull endpoint stays.
- Do not remove `fulfillment_resume_loop`. It is a local recovery sweep, not a
  cross-service poll, and it is the backstop that makes push safe to depend on.
- Do not implement the authenticated transport itself — `service-identity-signing` owns
  it and is a hard prerequisite.
- Do not support many-to-many storefront-to-authority delivery. Removed 2026-08-06; one
  authority delivers to one storefront.
- Do not accept callback URLs or credential material from buyer-controlled terms or
  opaque deal references as authority.
- Do not change what any event means. This change moves events; the capabilities that
  own their semantics keep owning them.

## Impact

- Affected code: the provisioning service's outbox, delivery worker, and event sink; the
  VM storefront's three polling loops and a receiver; `kit/fulfillment`'s result
  aggregate for outbox correlation; e2e fixtures and scenarios.
- Affected tests: outbox and delivery worker suites, receiver deduplication across
  restart, and the e2e scenarios that currently wait on intervals.
- Affected deployment: the authenticated channel's configuration, owned by
  `service-identity-signing`; this change adds outbox retention and delivery metrics.
- Performance: signature verification now runs per delivered event rather than per poll
  — a reduction, since polls occur whether or not anything happened.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the capacity and deal event model, which
      currently describes storefront-initiated polling as the delivery mechanism.
- [x] Existing subsystem specification — `physical-provisioning`, `fulfillment`,
      `storefront-publication`, and `test-compatibility`.
- [x] `docs/development/TESTING.md` — scenarios await events rather than poll.

### Knowledge to promote

- Authority-originated events are delivered over an authenticated channel with a durable
  outbox, with pull retained as the reconciliation baseline —
  `openspec/specs/physical-provisioning/spec.md`.
- Pushed events are applied idempotently with persistent deduplication —
  `openspec/specs/storefront-publication/spec.md`.
- Scenarios observe delivered events rather than polling —
  `openspec/specs/test-compatibility/spec.md`.

## Dependencies and Related Changes

- **Hard-depends on `service-identity-signing`** for the authenticated channel. Without
  it, delivery routing derives from broadly scoped configuration and cannot be trusted.
- Hard-depends on `pools-7-storefront-fulfillment-cutover`'s durable Settlement Record,
  fulfillment result, and pull APIs, including the `fulfillment.result.v1` envelope this
  change reuses rather than redesigns.
- Unblocks the determinism `refactor-e2e-fulfillment-lifecycle`,
  `bare-metal-and-credits-domain-stacks`, and
  `market-platform-compute-40-multi-domain-proof` each need — all three carry a task
  requiring observable barriers rather than sleeps, and all three are gated on live runs
  that polling makes slow and timing-sensitive.
- `pools-8-capacity-projection-and-listing-hints` owns projection semantics; this change
  changes how a storefront learns a projection changed, not what one means.
