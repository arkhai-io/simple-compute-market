## Why

POOLS-7 uses storefront-initiated pull status/result reconciliation as its correctness baseline. An existing provisioning→storefront callback delivers capacity-release events, but it uses process-local deduplication and broadly scoped URL/admin-key routing and cannot provide durable, authenticated, replayable Settlement Result delivery to several storefront owners.

## What Changes

- Harden the existing lifecycle callback seam into an authenticated provisioning-to-storefront delivery channel with operator-trusted owner/site credential bindings.
- Add a durable outbox written atomically with reportable POOLS-7 fulfillment-result transitions.
- Deliver Settlement Results at least once with stable event/result identity, capped retry/backoff, replay, metrics, and audit state.
- Persist receiver deduplication and apply transitions idempotently across storefront restart.
- Use monotonic credential generations so stale delivery cannot replace newer access material.
- Obtain sensitive credentials just in time and avoid durable plaintext credential storage in outbox or storefront lifecycle tables.
- Retain pull status/result endpoints as the permanent reconciliation and recovery backstop.
- State: **Deferred follow-on; blocked until POOLS-7 durable results land and trusted many-to-many ownership/authentication is selected.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `fulfillment`: Add durable optional push delivery over the pull-correct Settlement Result aggregate.
- `physical-provisioning`: Authenticate and route lifecycle/result events using trusted owner/site bindings rather than process-global or opaque deal metadata.
- `storefront-publication`: Persistently deduplicate and apply result notifications while retaining pull reconciliation.

## Dependencies and Related Changes

- Hard-depends on `pools-7-storefront-fulfillment-cutover` durable Settlement Record, fulfillment result, and pull APIs — including the `fulfillment.result.v1` envelope Section 8 defines, which this change reuses rather than redesigns.
- Hard-depends on `add-storefront-principal-authentication` (proposed 2026-07-25) for the owner/site identity half of "operator-trusted owner/site credential bindings" — that change resolves *which storefront owns this record*; this change still separately owns *how provisioning authenticates itself back to that storefront* (the reverse-transport mechanism), which remains this change's own open decision.
- Uses the many-to-many storefront/provisioner ownership model proven by `market-platform-compute-40-multi-domain-proof`, but Compute-40 does not block on push delivery.
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
- Deployment gains distinct scoped reverse-delivery credentials or identities for each authorized relationship.
- Wire and persistence schemas remain design-gated until POOLS-7 result envelopes are final.
