## Context

`StorefrontLifecycleEventSink` already sends `capacity_released` from provisioning to a storefront selected from reservation deal metadata or a process default. It can use a storefront admin key and suppresses duplicate event IDs only in process memory. This proves transport reachability, not durable many-owner authentication or result delivery.

POOLS-7 deliberately makes pull status/result APIs authoritative. Push is optional acceleration over the same durable aggregate and must converge with pull after outage, restart, or lost delivery.

## Goals / Non-Goals

**Goals:**
- Authenticate every provisioning-to-storefront relationship from operator-trusted configuration.
- Deliver reportable results at least once from a durable transactional outbox.
- Deduplicate and apply notifications durably at the receiver.
- Preserve just-in-time credential handling and pull reconciliation.

**Non-Goals:**
- Select a final credential mechanism before the many-to-many trust topology is approved.
- Put URLs/secrets in buyer-controlled payloads.
- Make push a correctness prerequisite.

## Decisions

### Harden the existing callback transport

Capacity-release and Settlement Result notifications should share a narrow versioned delivery envelope, transport client, authentication verifier, retry machinery, and receiver deduplication where their guarantees match. Their authoritative state transitions remain separate: capacity release is site state, while result application is fulfillment/storefront state.

Creating an unrelated second reverse client was rejected because it would duplicate ownership, authentication, retry, and observability mechanisms.

### Resolve destination and credentials from trusted bindings

A provisioning authority stores or resolves an operator-configured owner binding keyed by a durable storefront/relationship identity recorded at acceptance. Opaque `deal_ref` may carry correlation IDs but not authoritative URL or secret values. The receiver authenticates a scoped provisioning/site identity and authorizes only the intended seller relationship.

The exact mechanism—mTLS identity, asymmetric signed request, or scoped rotated token—remains open. Reusing one storefront admin key for every provisioner is not accepted because compromise cannot be isolated and receiver attribution is weak.

### Write outbox state with the result transition

When POOLS-7 commits a reportable result generation, it inserts an immutable outbox event in the same database transaction. Stable `event_id`, `result_id`, owner binding, result generation, non-secret payload/reference, attempt state, and timestamps survive restart. Workers claim rows with leases, deliver, record acknowledgment, and retry with capped exponential backoff and jitter.

Credentials are fetched/refreshed just in time. Plaintext access secrets are neither embedded in durable outbox payloads nor retained by the storefront after their intended retrieval semantics.

### Deduplicate durably at the storefront

The receiver authenticates before parsing/applying domain result data. It inserts stable event identity and applies the local transition atomically. Replays return the prior acknowledgment. A lower `credential_generation` cannot overwrite a newer applied generation.

### Keep pull as reconciliation authority

A storefront recovering missing local state queries POOLS-7 status/result endpoints. A push notification is a prompt to converge, not a second result authority. Receiver/application conflict resolves against durable provisioning result identity and monotonic generation.

### Defer implementation tasks

The change remains taskless until POOLS-7 finalizes result envelopes and the operator selects reverse authentication/credential rotation. Planning work should next compare mechanisms against deployment topology, compromise isolation, rotation, replay protection, and local development support. **Before that planning work locks in a scope (2026-08-03 note, see `proposal.md`):** first review every storefront↔provisioning-service network interaction, not only the two flows (capacity-release, Settlement Result) this document was originally scoped around from the one existing callback seam.

## Risks / Trade-offs

- **[Credential compromise fans out]** → Scope identity per relationship/site and support independent rotation/revocation.
- **[Outbox stores sensitive results]** → Persist non-secret normalized result/reference only and fetch ephemeral credentials just in time.
- **[Push and pull race]** → Use stable result identity and monotonic generation with idempotent convergence.
- **[Receiver outage creates backlog]** → Cap retries, expose age/depth metrics, and provide audited manual replay.
- **[Existing capacity callback remains weaker during migration]** → Migrate it to the shared trusted binding or explicitly quarantine it as compatibility behavior with a removal gate.

## Open Questions

- Which reverse authentication mechanism satisfies hosted, local Compose, and Helm deployments without one shared symmetric secret?
- Where is storefront-owner binding created and rotated, and which service is authoritative for its public destination? (Partially scoped out 2026-07-25: `add-storefront-principal-authentication` owns *identity* — which storefront a record belongs to, expressed as `owner_principal` — as a new hard dependency of this change. This change still owns the reverse-direction *transport* authentication mechanism itself, which that change does not decide.)
- Can ephemeral access material be regenerated deterministically, or does delivery require a bounded encrypted transient store?

## Permanent Documentation Promotion

Accepted delivery guarantees belong in `openspec/specs/fulfillment/spec.md` and `architecture.md`; reverse ownership/authentication belongs in `openspec/specs/physical-provisioning/spec.md` and `architecture.md`; receiver idempotency belongs in `openspec/specs/storefront-publication/spec.md` and `architecture.md`; deployment credential topology belongs in `openspec/specs/deployment-state/architecture.md` if selected.
