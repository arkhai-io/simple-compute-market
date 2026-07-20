## Why

Split out of `pools-7-storefront-fulfillment-cutover`'s planning phase
(2026-07-21), not independently discovered. `pools-7` originally designed
a push-based, durable-outbox `SettlementResult` delivery mechanism (the
provisioning service pushes fulfillment results and credentials to the
storefront, rather than the storefront polling for them) — motivated by
wanting to avoid inter-service polling and by resilience concerns with a
polling-based credential-retrieval pathway.

That design was not implementable as scoped inside `pools-7`, for a
reason discovered only during planning: pushing anything from the
provisioning service to the storefront requires an authenticated
provisioning→storefront channel that does not exist anywhere in this
codebase. Every existing trust relationship runs the other direction —
one shared `admin_api_key` per site, storefront as the sole caller
(`StorefrontAuthMiddleware`'s docstring: *"the provisioning service is an
internal dependency of a single storefront"*). Designing that channel
properly is nontrivial on its own: a storefront connects to potentially
many provisioning services (`pools-8`'s `CapacityProjection` already
establishes this is a real one-to-many relationship), so the storefront's
receiver side must authenticate *N* distinct callers, not reuse a single
symmetric secret. Building this inside `pools-7` risked scope creep onto
an already large change, so `pools-7` ships a pull-based
`get_fulfillment_status`/`get_fulfillment_result` design for v1 (over the
existing, already-solved storefront→provisioning direction) and this
change picks up the push design as a follow-on.

## What This Change Covers

- Design and implement an authenticated provisioning→storefront channel,
  supporting one storefront authenticating pushes from multiple distinct
  provisioning services (not a single shared secret reused symmetrically).
- Add a push delivery transport for `SettlementResult` on top of
  `pools-7`'s durable fulfillment/settlement persistence layer — durable
  outbox insertion atomic with the fulfillment-state transition that
  produces a reportable result, at-least-once delivery, idempotent
  application at the storefront by stable `result_id`, retry with
  capped exponential backoff and jitter while the fulfillment remains
  active, monotonic `credential_generation` so a stale retry cannot
  clobber a newer credential set, operator metrics/alerts/audit
  history, and a manual replay mechanism.
- Credentials remain never-persisted-at-rest in this design too: the
  delivery worker obtains or refreshes credentials just-in-time,
  transmits them once over the authenticated encrypted channel, and
  discards them — same posture as `pools-7`'s pull-based fetch-on-read,
  adapted to a background worker's schedule instead of a request handler.

## Non-Goals

- Redesigning `pools-7`'s durable fulfillment/settlement persistence
  layer. This change reads from and pushes notifications about state
  that layer already makes durable; it does not change what's persisted
  or when a fulfillment transition commits.
- Removing `get_fulfillment_status`/`get_fulfillment_result`. Pull
  remains a valid, permanent reconciliation backstop even after push
  exists — useful for a storefront that lost or is restoring local state
  and needs to actively ask rather than wait for a retry to arrive.

## Dependencies and Related Changes

- Requires `pools-7-storefront-fulfillment-cutover` to have landed —
  needs the durable fulfillment/settlement aggregate and
  `get_fulfillment_status`/`get_fulfillment_result` to already exist as
  the thing this change adds push delivery on top of.

## Impact

Touches the VM provisioning service (new auth middleware/credential
issuance for the reverse direction, delivery worker, outbox table) and
the storefront (authenticated receiver endpoint, per-`result_id`
deduplication and persistence). Detailed file-level impact is a
planning-step output; this change has not yet been planned (no
`tasks.md`).
