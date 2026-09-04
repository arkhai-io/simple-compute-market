# Implementation Tasks

## 1. Durable outbox and delivery

- [ ] 1.1 Re-verify the interaction review in `design.md`'s Context — three cross-service
      polls plus one local sweep — before designing against it.
- [ ] 1.2 Write the outbox in the same transaction as the reported state change, using
      the caller-supplied-session repository pattern `kit/fulfillment` already provides.
      An event written after commit can be lost; one written before can describe a
      rollback.
- [ ] 1.3 Deliver over the channel `service-identity-signing` establishes. Do not
      implement transport or authentication here.
- [ ] 1.4 Stable event identity, capped retry and backoff, replay, metrics, and audit
      state. A silent outbox is worse than a poll, so observability is in scope rather
      than follow-on.
- [ ] 1.5 Outbox retention bounded by age **and** reference, matching the treatment
      reservation retention gets; decide it here rather than in production.
- [ ] 1.6 Focused tests: event written transactionally; rollback leaves no event;
      retry-cap exhaustion is observable and replayable.

## 2. Receiver

- [ ] 2.1 Persist applied-event identity; replace the existing in-process deduplication,
      which does not survive the restart that at-least-once delivery makes most likely
      to matter.
- [ ] 2.2 Apply transitions idempotently. This is the stronger property: correct
      application on a duplicate does not depend on deduplication being perfect.
- [ ] 2.3 Reject events not attributable to a registered site identity.
- [ ] 2.4 Focused tests: duplicate across restart applied once; unattributable event
      rejected.

## 3. Fulfillment status and result

- [ ] 3.1 Deliver fulfillment status and result, reusing `fulfillment.result.v1` rather
      than redesigning it.
- [ ] 3.2 Retire `_poll_fulfillment_status` as the primary path; keep the pull endpoint.
- [ ] 3.3 Focused tests: completion observed without polling; pull still reaches the same
      state.

## 4. Capacity events

- [ ] 4.1 Deliver a notification that the feed head advanced. Do **not** carry event
      bodies: the feed already has a cursor, ordering, and backwards-head gap recovery,
      and reimplementing those in the transport is the design error `design.md` names.
- [ ] 4.2 Retire the poller's interval while keeping its feed read, full-reconcile
      convergence, and backwards-head handling.
- [ ] 4.3 Focused tests: a delivered notification triggers a feed read; a missed
      notification still converges on the next read; a backwards head still re-reconciles.

## 5. Projection invalidation

- [ ] 5.1 Deliver invalidation only, never a projection body — a body in the outbox
      duplicates a large payload and bypasses the existing atomic-replace and
      stale-generation semantics.
- [ ] 5.2 Retire `site_projection_poller_loop`'s interval; keep the load path.
- [ ] 5.3 Focused tests: invalidation triggers atomic re-read; a failed re-read retains
      the last complete generation and marks it stale, as today.

## 6. Scenario refactor

- [ ] 6.1 Refactor end-to-end scenarios to await delivered events rather than poll.
- [ ] 6.2 Build on the generalized fixtures from
      `bare-metal-and-credits-domain-stacks`. A second fixture set here would duplicate
      that work and guarantee drift.
- [ ] 6.3 Await facts independently rather than assuming an order between events with no
      guaranteed sequence.
- [ ] 6.4 Coordinate with `refactor-e2e-fulfillment-lifecycle`, whose three open tasks
      are all blocked on a live run that polling makes slow and timing-sensitive.

## 7. Validation

- [ ] 7.1 **Prove push is not load-bearing:** disable delivery entirely and confirm the
      system remains correct through pull and the local resume sweep, only slower. Put
      this in the suite rather than in a reviewer's memory — it is the property most
      likely to erode.
- [ ] 7.2 Confirm `fulfillment_resume_loop` is unchanged; it is a local sweep, not a
      cross-service poll, and it is the backstop that makes push safe to depend on.
- [ ] 7.3 Measure per-event verification cost against the per-poll cost it replaces.
- [ ] 7.4 Run the provisioning, storefront, and end-to-end suites. Disclose any suite not
      run.
- [ ] 7.5 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read the three pollers'
      docstrings directly; each describes polling as the delivery mechanism.
- [ ] 8.2 **Import placement.** Review imports this change adds or touches.
- [ ] 8.3 **Documentation compliance.** Confirm the delivery rules landed in
      `physical-provisioning`, the receiver rules in `storefront-publication`, the
      scenario rule in `test-compatibility`, that `ARCHITECTURE.md`'s event model no
      longer describes polling as the delivery mechanism, and that `TESTING.md` states
      scenarios await events.
- [ ] 8.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 8.5 **Roadmap currency.** Record the disposition; this change closes no roadmap
      goal's gap on its own.
- [ ] 8.6 **Promotion.** Complete the design-promotion record below.
- [ ] 8.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Events are delivered over an authenticated channel from a transactional outbox; delivery is never the correctness path; a versioned feed keeps its own ordering and recovery | `openspec/specs/physical-provisioning/spec.md` — "Authority-originated events are delivered, not polled for" |
| Pushed events are applied idempotently with durable deduplication; invalidation triggers a re-read rather than carrying a body | `openspec/specs/storefront-publication/spec.md` — "Pushed events are applied idempotently with durable deduplication" |
| Scenarios advance on delivered events rather than intervals | `openspec/specs/test-compatibility/spec.md` — "Scenarios observe delivered events rather than polling" |
| The capacity and deal event delivery model | `docs/development/ARCHITECTURE.md` |
| Scenarios await events rather than poll | `docs/development/TESTING.md` |
| Why the three flows need three push shapes, and why disabling delivery must leave the system correct | This change's `design.md` |
