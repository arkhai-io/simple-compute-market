## Why

POOLS-7 uses storefront-initiated pull status/result reconciliation as its correctness baseline. An existing provisioning→storefront callback delivers capacity-release events, but it uses process-local deduplication and broadly scoped URL/admin-key routing, and cannot provide durable, authenticated, replayable Settlement Result delivery even for the single storefront an authority serves.

**Amended 2026-08-06.** This change was previously motivated by delivery to several storefront owners. There are no plans to support many-to-many storefront-to-authority ownership, so the multi-owner framing is removed. The durability, authentication, and replay problems are unchanged and remain worth solving for one relationship: the current callback's process-local deduplication does not survive restart, and its routing derives from broadly scoped configuration rather than a verified binding.

## What Changes

- Harden the existing lifecycle callback seam into an authenticated provisioning-to-storefront delivery channel with operator-trusted owner/site credential bindings.
- Add a durable outbox written atomically with reportable POOLS-7 fulfillment-result transitions.
- Deliver Settlement Results at least once with stable event/result identity, capped retry/backoff, replay, metrics, and audit state.
- Persist receiver deduplication and apply transitions idempotently across storefront restart.
- Use monotonic credential generations so stale delivery cannot replace newer access material.
- Obtain sensitive credentials just in time and avoid durable plaintext credential storage in outbox or storefront lifecycle tables.
- Retain pull status/result endpoints as the permanent reconciliation and recovery backstop.
- State: **Deferred follow-on; blocked until POOLS-7 durable results land.** The former second blocking condition — selection of a trusted many-to-many ownership/authentication model — is **removed, not pending** (2026-08-06): that model is not being pursued, so waiting on it would block this change indefinitely.
- **Scope-review note, added 2026-08-03 (before implementation planning begins):** the two data flows above (capacity-release, Settlement Result) were identified from the one existing callback seam, not from a review of every storefront↔provisioning-service network interaction. Before finalizing what this change's delivery channel covers, review all such interactions — including the site-authority resource-pool/capacity-bucket projection polling `site_projection_cache.py` performs (`ProjectionCache`/`capacity_events_poller_loop`), which POOLS-8 is (2026-08-03) redesigning independently of this change's current scope — for other genuine push opportunities over the same authenticated transport, rather than assuming the two flows already identified are the complete set.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `fulfillment`: Add durable optional push delivery over the pull-correct Settlement Result aggregate.
- `physical-provisioning`: Authenticate and route lifecycle/result events using trusted owner/site bindings rather than process-global or opaque deal metadata.
- `storefront-publication`: Persistently deduplicate and apply result notifications while retaining pull reconciliation.

## Dependencies and Related Changes

- Hard-depends on `pools-7-storefront-fulfillment-cutover` durable Settlement Record, fulfillment result, and pull APIs — including the `fulfillment.result.v1` envelope Section 8 defines, which this change reuses rather than redesigns.
- Depends on `service-identity-signing` for the owner/site identity half, **if that change proceeds** — its own driving use case weakened when many-to-many was dropped (see its 2026-08-06 note), so this change should confirm the identity half still has an owner before planning against it. Previously recorded as a hard dependency of "operator-trusted owner/site credential bindings" — that change resolves *which storefront owns this record*; this change still separately owns *how provisioning authenticates itself back to that storefront* (the reverse-transport mechanism), which remains this change's own open decision.
- ~~Uses the many-to-many storefront/provisioner ownership model proven by `market-platform-compute-40-multi-domain-proof`.~~ **Removed 2026-08-06:** that change was rewritten and no longer proves many-to-many ownership; its topology is one multi-domain storefront against two authorities. Compute-40 still does not block push delivery, and its pull reconciliation remains the correctness baseline this change hardens rather than replaces.
- May share one generic outbox/receiver transport with the existing capacity-release callback; event-specific state transitions remain capability-owned.

## Non-Goals

- Do not replace or weaken pull reconciliation.
- Do not redesign POOLS-7 scheduling, assignment, provider dispatch, or result persistence.
- Do not accept callback URL or credential material from buyer-controlled terms or opaque agreement/deal references as authority.
- Do not store plaintext access credentials durably merely to make retries easy.
- Do not add implementation tasks until authentication topology and credential lifecycle decisions are accepted.

## Impact

- Provisioning services gain trusted owner bindings, durable outbox/worker state, and operator replay/metrics.
- Storefronts gain an authenticated receiver and durable event/result deduplication.
- Deployment gains a scoped reverse-delivery credential or identity for the authority-to-storefront relationship, replacing routing derived from broadly scoped configuration. **Amended 2026-08-06:** previously phrased as one per authorized relationship, which assumed several.
- Wire and persistence schemas remain design-gated until POOLS-7 result envelopes are final.
